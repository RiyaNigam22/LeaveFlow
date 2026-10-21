"""Leave request use-cases. Each function runs inside the caller's transaction (session_scope)
and orchestrates: validation -> workflow engine -> balances -> notifications -> audit log."""
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from database.models import ApprovalStep, Employee, LeaveRequest, LeaveType
from services import audit_service, balance_service, notification_service as ns, rules_service
from utils.dates import fmt_date, now_utc, to_local, today_local
from utils.errors import BusinessRuleError
from workflows import engine
from workflows.engine import Actor, Transition
from workflows.states import OPEN_STATUSES, RequestStatus, Stage, STAGE_LABEL

AUDIT_FIELDS = ["status", "start_date", "end_date", "working_days"]


def _describe(request: LeaveRequest) -> str:
    return (f"{request.leave_type.name} ({fmt_date(request.start_date)} – {fmt_date(request.end_date)}, "
            f"{request.working_days} working day(s))")


def _employee_user_id(request: LeaveRequest) -> int | None:
    return request.employee.user.id if request.employee.user else None


def _notify_step_approvers(session: Session, request: LeaveRequest, step: ApprovalStep, now) -> None:
    label = STAGE_LABEL[Stage(step.stage)]
    title = f"{label} approval required"
    msg = f"{request.employee.full_name} requested {_describe(request)}."
    if step.approver_employee_id:
        approver = session.get(Employee, step.approver_employee_id)
        if approver.user:
            ns.notify(session, approver.user.id, title, msg, ns.APPROVAL_REQUIRED, request.id, now)
    else:
        ns.notify_hr(session, title, msg, ns.APPROVAL_REQUIRED, request.id,
                     exclude_user_id=_employee_user_id(request), now=now)


def _load_for_update(session: Session, request_id: int) -> LeaveRequest:
    request = session.scalars(select(LeaveRequest).where(LeaveRequest.id == request_id)
                              .with_for_update(of=LeaveRequest)).first()
    if request is None:
        raise BusinessRuleError("The request could not be found.")
    return request


def _local_today(now: datetime | None) -> date:
    return to_local(now).date() if now else today_local()


# --- submit -------------------------------------------------------------------------------

def submit_leave_request(session: Session, actor: Actor, leave_type_id: int, start: date, end: date,
                         reason: str | None = None, document: tuple[str, bytes] | None = None,
                         now: datetime | None = None) -> LeaveRequest:
    now = now or now_utc()
    employee = session.get(Employee, actor.employee_id)
    leave_type = session.get(LeaveType, leave_type_id)
    if employee is None or leave_type is None:
        raise BusinessRuleError("The selected employee or leave type is not valid.")
    if document and len(document[1]) > config.MAX_DOCUMENT_MB * 1024 * 1024:
        raise BusinessRuleError(f"The attached document exceeds the {config.MAX_DOCUMENT_MB} MB limit.")

    result = rules_service.validate_leave_request(
        session, employee, leave_type, start, end, has_document=document is not None,
        today=_local_today(now), lock_balance=True)
    if not result.valid:
        raise BusinessRuleError(result.errors[0], result.errors)

    request = LeaveRequest(
        employee_id=employee.id, leave_type_id=leave_type.id, start_date=start, end_date=end,
        working_days=result.working_days, reason=(reason or "").strip() or None,
        document_name=document[0] if document else None,
        document_content=document[1] if document else None,
        status=RequestStatus.DRAFT.value, created_at=now)
    session.add(request)
    session.flush()

    transition = engine.submit(request, employee, result.stages if leave_type.requires_approval else (), now)
    balance_service.reserve(session, request)
    audit_service.log(session, actor.user_id, "LEAVE_SUBMITTED", "LeaveRequest", request.id,
                      new={**{f: getattr(request, f) for f in AUDIT_FIELDS}, "leave_type": leave_type.name,
                           "stages": [s.value for s in result.stages]}, now=now)

    if transition.new_status == RequestStatus.APPROVED:
        balance_service.commit_used(session, request)
        ns.notify(session, actor.user_id, "Leave approved",
                  f"{_describe(request)} does not require approval and is confirmed.", ns.APPROVED, request.id, now)
        audit_service.log(session, actor.user_id, "REQUEST_AUTO_APPROVED", "LeaveRequest", request.id,
                          old={"status": "SUBMITTED"}, new={"status": "APPROVED"}, now=now)
    else:
        step = transition.next_step
        who = "HR" if not step.approver_employee_id else "your manager"
        if step.stage == Stage.DEPARTMENT_HEAD.value:
            who = "the department head"
        ns.notify(session, actor.user_id, "Leave request submitted",
                  f"Your request for {_describe(request)} has been submitted to {who}.", ns.SUBMITTED, request.id, now)
        _notify_step_approvers(session, request, step, now)
    session.flush()
    return request


# --- decisions -------------------------------------------------------------------------------

def approve_request(session: Session, actor: Actor, request_id: int, comment: str | None = None,
                    now: datetime | None = None) -> Transition:
    now = now or now_utc()
    request = _load_for_update(session, request_id)
    old_status = request.status
    tr = engine.approve(request, actor, comment, now)
    emp_uid = _employee_user_id(request)
    if tr.is_final:
        balance_service.commit_used(session, request)
        audit_service.log(session, actor.user_id, "REQUEST_APPROVED", "LeaveRequest", request.id,
                          old={"status": old_status}, new={"status": request.status, "comment": comment}, now=now)
        ns.notify(session, emp_uid, "Leave request approved", f"Your request for {_describe(request)} was approved.",
                  ns.APPROVED, request.id, now)
        if request.leave_type.tracks_balance:
            bal = balance_service.get_or_create_balance(session, request.employee_id, request.leave_type,
                                                        request.start_date.year)
            ns.notify(session, emp_uid, "Leave balance updated",
                      f"{request.leave_type.name}: {bal.available} day(s) remaining for {bal.year}.",
                      ns.BALANCE_UPDATED, request.id, now)
            audit_service.log(session, actor.user_id, "BALANCE_UPDATED", "LeaveBalance", bal.id,
                              new={"used": bal.used, "pending": bal.pending, "available": bal.available}, now=now)
    else:
        audit_service.log(session, actor.user_id, "STEP_APPROVED", "LeaveRequest", request.id,
                          old={"status": old_status}, new={"status": request.status, "stage": tr.step.stage,
                                                           "comment": comment}, now=now)
        nxt_label = STAGE_LABEL[Stage(tr.next_step.stage)]
        ns.notify(session, emp_uid, "Leave request progressed",
                  f"Your request for {_describe(request)} was approved by {STAGE_LABEL[Stage(tr.step.stage)]} "
                  f"and is now awaiting {nxt_label} approval.", ns.INFO, request.id, now)
        _notify_step_approvers(session, request, tr.next_step, now)
    session.flush()
    return tr


def reject_request(session: Session, actor: Actor, request_id: int, reason: str,
                   now: datetime | None = None) -> Transition:
    now = now or now_utc()
    request = _load_for_update(session, request_id)
    old_status = request.status
    tr = engine.reject(request, actor, reason, now)
    balance_service.release(session, request)
    audit_service.log(session, actor.user_id, "REQUEST_REJECTED", "LeaveRequest", request.id,
                      old={"status": old_status}, new={"status": request.status, "reason": reason.strip()}, now=now)
    ns.notify(session, _employee_user_id(request), "Leave request rejected",
              f"Your request for {_describe(request)} was rejected. Reason: {reason.strip()}",
              ns.REJECTED, request.id, now)
    session.flush()
    return tr


def cancel_request(session: Session, actor: Actor, request_id: int, now: datetime | None = None) -> Transition:
    now = now or now_utc()
    request = _load_for_update(session, request_id)
    old_status = request.status
    active = engine.pending_step(request)
    tr = engine.cancel(request, actor, now)
    balance_service.release(session, request)
    audit_service.log(session, actor.user_id, "REQUEST_CANCELLED", "LeaveRequest", request.id,
                      old={"status": old_status}, new={"status": request.status}, now=now)
    ns.notify(session, actor.user_id, "Leave request cancelled",
              f"Your request for {_describe(request)} was cancelled.", ns.CANCELLED, request.id, now)
    if active is not None:
        label = f"{request.employee.full_name} cancelled {_describe(request)}."
        if active.approver_employee_id:
            approver = session.get(Employee, active.approver_employee_id)
            if approver.user:
                ns.notify(session, approver.user.id, "Pending request cancelled", label, ns.CANCELLED, request.id, now)
        else:
            ns.notify_hr(session, "Pending request cancelled", label, ns.CANCELLED, request.id,
                         exclude_user_id=actor.user_id, now=now)
    session.flush()
    return tr


def override_request(session: Session, actor: Actor, request_id: int, target: RequestStatus, reason: str,
                     now: datetime | None = None) -> Transition:
    now = now or now_utc()
    request = _load_for_update(session, request_id)
    old_status = request.status
    tr = engine.override(request, actor, target, reason, now)
    if RequestStatus(old_status) == RequestStatus.APPROVED:
        balance_service.revoke_used(session, request)       # approved -> cancelled
    elif target == RequestStatus.APPROVED:
        balance_service.commit_used(session, request)       # open -> approved
    else:
        balance_service.release(session, request)           # open -> rejected / cancelled
    audit_service.log(session, actor.user_id, "ADMIN_OVERRIDE", "LeaveRequest", request.id,
                      old={"status": old_status}, new={"status": request.status, "reason": reason.strip()}, now=now)
    ns.notify(session, _employee_user_id(request), "Request updated by HR",
              f"HR changed your request for {_describe(request)} to {target.value.title()}. Reason: {reason.strip()}",
              ns.OVERRIDE, request.id, now)
    session.flush()
    return tr


# --- read helpers ------------------------------------------------------------------------------

def get_request(session: Session, request_id: int) -> LeaveRequest | None:
    return session.get(LeaveRequest, request_id)


def can_view(session: Session, actor: Actor, request: LeaveRequest) -> bool:
    if actor.is_hr or request.employee_id == actor.employee_id:
        return True
    if request.employee.manager_id == actor.employee_id:
        return True
    return any(s.approver_employee_id == actor.employee_id for s in request.steps)


def can_cancel(actor: Actor, request: LeaveRequest) -> bool:
    return request.employee_id == actor.employee_id and RequestStatus(request.status) in OPEN_STATUSES


def submission_message(request: LeaveRequest) -> str:
    """User-facing confirmation text for a freshly submitted request."""
    if request.status == RequestStatus.APPROVED.value:
        return "Your request has been confirmed – this leave type does not require approval."
    step = engine.pending_step(request)
    if step.stage == Stage.DEPARTMENT_HEAD.value:
        return "Your request has been submitted to the department head."
    if step.stage == Stage.HR.value or step.approver_employee_id is None:
        return "Your request has been submitted to HR."
    return "Your request has been submitted to your manager."


def direct_reports(session: Session, manager_employee_id: int) -> list[Employee]:
    return list(session.scalars(select(Employee).where(
        Employee.manager_id == manager_employee_id, Employee.is_active.is_(True)).order_by(Employee.first_name)))


def team_conflicts(session: Session, request: LeaveRequest) -> list[str]:
    """Colleagues under the same manager who are away (approved/pending) during the request's dates."""
    if request.employee.manager_id is None:
        return []
    from workflows.states import ACTIVE_STATUSES
    rows = session.execute(
        select(Employee.first_name, Employee.last_name).join(LeaveRequest, LeaveRequest.employee_id == Employee.id)
        .where(Employee.manager_id == request.employee.manager_id, Employee.id != request.employee_id,
               LeaveRequest.status.in_([s.value for s in ACTIVE_STATUSES]),
               LeaveRequest.start_date <= request.end_date, LeaveRequest.end_date >= request.start_date).distinct())
    return [f"{f} {l}" for f, l in rows]
