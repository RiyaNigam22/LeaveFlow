"""Workflow engine: builds approval chains and applies state transitions to requests and steps.

It deliberately knows nothing about balances, notifications or auditing – leave_service
orchestrates those around the Transition objects returned here.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

import config
from database.models import ApprovalStep, Employee, LeaveRequest
from utils.dates import now_utc
from utils.errors import BusinessRuleError, PermissionDenied
from workflows.states import (
    PENDING_STATUSES, STAGE_LABEL, STAGE_PENDING_STATUS, RequestStatus, Stage, StepStatus,
    assert_transition, is_cancellable_by_employee,
)


@dataclass(frozen=True)
class Actor:
    user_id: int
    employee_id: int
    role: str

    @classmethod
    def from_session(cls, user: dict) -> "Actor":
        return cls(user["user_id"], user["employee_id"], user["role"])

    @property
    def is_hr(self) -> bool:
        return self.role == config.ROLE_HR


@dataclass
class Transition:
    old_status: RequestStatus
    new_status: RequestStatus
    step: ApprovalStep | None = None        # the step that was decided (if any)
    next_step: ApprovalStep | None = None   # the step that became active (if any)

    @property
    def is_final(self) -> bool:
        return self.new_status in (RequestStatus.APPROVED, RequestStatus.REJECTED, RequestStatus.CANCELLED)


# --- helpers -----------------------------------------------------------------------

def pending_step(request: LeaveRequest) -> ApprovalStep | None:
    return next((s for s in request.steps if s.status == StepStatus.PENDING.value), None)


def can_decide(actor: Actor, request: LeaveRequest, step: ApprovalStep | None) -> bool:
    """Who may approve/reject the active step. Nobody may decide on their own request."""
    if step is None or step.status != StepStatus.PENDING.value:
        return False
    if actor.employee_id == request.employee_id:
        return False
    if step.approver_employee_id is not None:
        return actor.employee_id == step.approver_employee_id
    return actor.is_hr  # unassigned step = any HR/Admin


def _status(request: LeaveRequest) -> RequestStatus:
    return RequestStatus(request.status)


def _set_status(request: LeaveRequest, new: RequestStatus) -> RequestStatus:
    old = _status(request)
    assert_transition(old, new)
    request.status = new.value
    return old


def _activate(step: ApprovalStep, now: datetime) -> None:
    step.status = StepStatus.PENDING.value
    step.activated_at = now


def _activate_next(request: LeaveRequest, now: datetime) -> ApprovalStep | None:
    nxt = next((s for s in request.steps if s.status == StepStatus.WAITING.value), None)
    if nxt:
        _activate(nxt, now)
    return nxt


# --- building the approval chain -------------------------------------------------------

def _approver_for(employee: Employee, stage: Stage) -> int | None | str:
    """Employee id of the assigned approver, None for 'any HR user', or 'SKIP'."""
    if stage == Stage.MANAGER:
        mgr = employee.manager
        return mgr.id if mgr and mgr.is_active and mgr.id != employee.id else None  # fallback: HR
    if stage == Stage.DEPARTMENT_HEAD:
        head = employee.department.head if employee.department else None
        return head.id if head and head.is_active and head.id != employee.id else "SKIP"
    return None


def resolve_chain(employee: Employee, stages: tuple[Stage, ...]) -> list[tuple[Stage, int | None, str | None]]:
    """Resolve each required stage to (stage, approver_employee_id or None for 'any HR', skip_reason or None)."""
    chain, seen = [], set()
    for stage in stages:
        approver = _approver_for(employee, stage)
        if approver == "SKIP":
            chain.append((stage, None, "Not required: no department head assigned, or requester is the department head."))
        elif approver is not None and approver in seen:
            chain.append((stage, approver, "Not required: same approver already covers an earlier stage."))
        else:
            if approver is not None:
                seen.add(approver)
            chain.append((stage, approver, None))
    return chain


def build_steps(request: LeaveRequest, employee: Employee, stages: tuple[Stage, ...]) -> list[ApprovalStep]:
    steps = []
    for order, (stage, approver, skip_reason) in enumerate(resolve_chain(employee, stages), start=1):
        steps.append(ApprovalStep(
            step_order=order, stage=stage.value, approver_employee_id=approver,
            status=StepStatus.SKIPPED.value if skip_reason else StepStatus.WAITING.value, comments=skip_reason))
    request.steps = steps
    return steps


def describe_chain(session: Session, employee: Employee, stages: tuple[Stage, ...]) -> str:
    """Human-readable approval path, e.g. 'Karthik Rao (Manager) → HR team → Vikram Nair (Department Head)'."""
    parts = []
    for stage, approver, skip in resolve_chain(employee, stages):
        if skip:
            continue
        who = session.get(Employee, approver).full_name if approver else "HR team"
        parts.append(f"{who} ({STAGE_LABEL[stage]})" if approver else f"{STAGE_LABEL[stage]}: {who}")
    return " → ".join(parts) if parts else "No approval required"


# --- transitions -------------------------------------------------------------------------

def submit(request: LeaveRequest, employee: Employee, stages: tuple[Stage, ...], now: datetime | None = None) -> Transition:
    """DRAFT -> SUBMITTED -> first pending stage (or straight to APPROVED when no approval is needed)."""
    now = now or now_utc()
    old = _set_status(request, RequestStatus.SUBMITTED)
    request.submitted_at = now
    build_steps(request, employee, stages)
    first = _activate_next(request, now)
    if first is None:
        _set_status(request, RequestStatus.APPROVED)
        request.decided_at = now
        request.decision_reason = "Auto-approved: no approval required."
    else:
        _set_status(request, STAGE_PENDING_STATUS[Stage(first.stage)])
    return Transition(old, _status(request), next_step=first)


def approve(request: LeaveRequest, actor: Actor, comment: str | None = None, now: datetime | None = None) -> Transition:
    now = now or now_utc()
    step = pending_step(request)
    if not can_decide(actor, request, step):
        raise PermissionDenied("You are not authorised to approve this request at its current stage.")
    old = _status(request)
    step.status = StepStatus.APPROVED.value
    step.decided_at = now
    step.acted_by_user_id = actor.user_id
    step.comments = comment or None
    nxt = _activate_next(request, now)
    if nxt:
        _set_status(request, STAGE_PENDING_STATUS[Stage(nxt.stage)])
    else:
        _set_status(request, RequestStatus.APPROVED)
        request.decided_at = now
        request.decision_reason = comment or None
    return Transition(old, _status(request), step=step, next_step=nxt)


def reject(request: LeaveRequest, actor: Actor, reason: str, now: datetime | None = None) -> Transition:
    now = now or now_utc()
    if not reason or not reason.strip():
        raise BusinessRuleError("A reason is required to reject a request.")
    step = pending_step(request)
    if not can_decide(actor, request, step):
        raise PermissionDenied("You are not authorised to reject this request at its current stage.")
    old = _set_status(request, RequestStatus.REJECTED)
    step.status = StepStatus.REJECTED.value
    step.decided_at = now
    step.acted_by_user_id = actor.user_id
    step.comments = reason.strip()
    for s in request.steps:
        if s.status == StepStatus.WAITING.value:
            s.status = StepStatus.CANCELLED.value
    request.decided_at = now
    request.decision_reason = reason.strip()
    return Transition(old, RequestStatus.REJECTED, step=step)


def cancel(request: LeaveRequest, actor: Actor, now: datetime | None = None) -> Transition:
    """Employee cancels their own request while it is still open."""
    now = now or now_utc()
    if request.employee_id != actor.employee_id:
        raise PermissionDenied("You can only cancel your own requests.")
    if not is_cancellable_by_employee(_status(request)):
        raise BusinessRuleError("Only pending requests can be cancelled.")
    return _close_open_request(request, RequestStatus.CANCELLED, "Cancelled by employee.", now)


def override(request: LeaveRequest, actor: Actor, target: RequestStatus, reason: str,
             now: datetime | None = None) -> Transition:
    """HR/Admin forces a final decision. Requires a reason; cannot be used on one's own request."""
    now = now or now_utc()
    if not actor.is_hr:
        raise PermissionDenied("Only HR/Admin users can override requests.")
    if actor.employee_id == request.employee_id:
        raise PermissionDenied("You cannot override your own request.")
    if not reason or not reason.strip():
        raise BusinessRuleError("A reason is required for an override.")
    if target not in (RequestStatus.APPROVED, RequestStatus.REJECTED, RequestStatus.CANCELLED):
        raise BusinessRuleError("An override must result in Approved, Rejected or Cancelled.")
    return _close_open_request(request, target, reason.strip(), now, actor.user_id)


def _close_open_request(request, target, reason, now, acting_user_id=None) -> Transition:
    old = _set_status(request, target)
    for s in request.steps:
        if s.status in (StepStatus.PENDING.value, StepStatus.WAITING.value):
            s.status = StepStatus.SKIPPED.value if acting_user_id else StepStatus.CANCELLED.value
            s.comments = reason
            s.decided_at = now if acting_user_id else s.decided_at
            s.acted_by_user_id = acting_user_id
    request.decided_at = now
    request.decision_reason = reason
    return Transition(old, target)


# --- queries -----------------------------------------------------------------------------------

def queue_for_actor(session: Session, actor: Actor) -> list[ApprovalStep]:
    """Active steps the actor can decide, oldest first."""
    cond = ApprovalStep.approver_employee_id == actor.employee_id
    if actor.is_hr:
        cond = or_(cond, ApprovalStep.approver_employee_id.is_(None))
    stmt = (select(ApprovalStep).join(LeaveRequest)
            .options(joinedload(ApprovalStep.request).joinedload(LeaveRequest.employee).joinedload(Employee.department),
                     joinedload(ApprovalStep.request).joinedload(LeaveRequest.leave_type))
            .where(ApprovalStep.status == StepStatus.PENDING.value, cond,
                   LeaveRequest.employee_id != actor.employee_id,
                   LeaveRequest.status.in_([s.value for s in PENDING_STATUSES]))
            .order_by(ApprovalStep.activated_at))
    return list(session.scalars(stmt).unique())


def stage_label(stage: str) -> str:
    return STAGE_LABEL[Stage(stage)]
