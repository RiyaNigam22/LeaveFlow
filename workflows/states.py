"""Pure workflow definitions: statuses, stages, legal transitions and approval-level selection.

Nothing in this module touches the database or the UI, so it is trivially testable.
"""
from dataclasses import dataclass
from enum import Enum

from utils.errors import WorkflowError


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    MANAGER_PENDING = "MANAGER_PENDING"
    HR_PENDING = "HR_PENDING"
    DEPARTMENT_HEAD_PENDING = "DEPARTMENT_HEAD_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Stage(str, Enum):
    MANAGER = "MANAGER"
    HR = "HR"
    DEPARTMENT_HEAD = "DEPARTMENT_HEAD"


class StepStatus(str, Enum):
    WAITING = "WAITING"      # not yet active
    PENDING = "PENDING"      # active, awaiting a decision
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"      # not required (no distinct approver / overridden)
    CANCELLED = "CANCELLED"


STAGE_ORDER: tuple[Stage, ...] = (Stage.MANAGER, Stage.HR, Stage.DEPARTMENT_HEAD)

STAGE_LABEL = {
    Stage.MANAGER: "Manager",
    Stage.HR: "HR",
    Stage.DEPARTMENT_HEAD: "Department Head",
}

STAGE_PENDING_STATUS = {
    Stage.MANAGER: RequestStatus.MANAGER_PENDING,
    Stage.HR: RequestStatus.HR_PENDING,
    Stage.DEPARTMENT_HEAD: RequestStatus.DEPARTMENT_HEAD_PENDING,
}
PENDING_STATUS_STAGE = {v: k for k, v in STAGE_PENDING_STATUS.items()}

PENDING_STATUSES = frozenset(STAGE_PENDING_STATUS.values())
OPEN_STATUSES = frozenset({RequestStatus.SUBMITTED, *PENDING_STATUSES})
# Statuses that block new overlapping requests and reserve balance.
ACTIVE_STATUSES = frozenset({*OPEN_STATUSES, RequestStatus.APPROVED})
FINAL_STATUSES = frozenset({RequestStatus.APPROVED, RequestStatus.REJECTED, RequestStatus.CANCELLED})

_S = RequestStatus
ALLOWED_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    _S.DRAFT: frozenset({_S.SUBMITTED, _S.CANCELLED}),
    _S.SUBMITTED: frozenset({*PENDING_STATUSES, _S.APPROVED, _S.CANCELLED}),
    _S.MANAGER_PENDING: frozenset({_S.HR_PENDING, _S.DEPARTMENT_HEAD_PENDING, _S.APPROVED, _S.REJECTED, _S.CANCELLED}),
    _S.HR_PENDING: frozenset({_S.DEPARTMENT_HEAD_PENDING, _S.APPROVED, _S.REJECTED, _S.CANCELLED}),
    _S.DEPARTMENT_HEAD_PENDING: frozenset({_S.APPROVED, _S.REJECTED, _S.CANCELLED}),
    _S.APPROVED: frozenset({_S.CANCELLED}),  # only via HR override
    _S.REJECTED: frozenset(),
    _S.CANCELLED: frozenset(),
}


def as_status(value) -> RequestStatus:
    return value if isinstance(value, RequestStatus) else RequestStatus(value)


def can_transition(current, target) -> bool:
    return as_status(target) in ALLOWED_TRANSITIONS[as_status(current)]


def assert_transition(current, target) -> None:
    if not can_transition(current, target):
        raise WorkflowError(
            f"A request in status {as_status(current).value} cannot move to {as_status(target).value}."
        )


def is_cancellable_by_employee(status) -> bool:
    """Employees may cancel requests that are not yet finalised."""
    return as_status(status) in OPEN_STATUSES


# --- approval-level selection -------------------------------------------------

@dataclass(frozen=True)
class ApprovalRuleSpec:
    """Applies when working_days > min_days. The rule with the highest matching min_days wins."""
    min_days: int
    stages: tuple[Stage, ...]


def parse_stages(value: str) -> tuple[Stage, ...]:
    """'MANAGER,HR' -> (Stage.MANAGER, Stage.HR), always returned in canonical order."""
    wanted = {Stage(s.strip()) for s in value.split(",") if s.strip()}
    return tuple(s for s in STAGE_ORDER if s in wanted)


def select_stages(working_days: int, rules: list[ApprovalRuleSpec]) -> tuple[Stage, ...]:
    matching = [r for r in rules if working_days > r.min_days]
    if not matching:
        raise WorkflowError("No approval rule is configured for this request duration.")
    return max(matching, key=lambda r: r.min_days).stages
