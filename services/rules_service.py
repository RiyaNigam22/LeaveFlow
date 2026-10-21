"""Centralised leave-request validation and business rules.

All thresholds come from the database (leave_types, approval_rules, holidays, system_settings);
no business rule is hard-coded in UI code. The small pure functions at the top are unit-tested
independently of the database.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    ApprovalRule, Employee, Holiday, LeaveRequest, LeaveType, SystemSetting,
)
from services import balance_service
from utils.dates import (
    DEFAULT_WEEKEND_DAYS, count_working_days, ranges_overlap, today_local,
)
from workflows.states import ACTIVE_STATUSES, ApprovalRuleSpec, Stage, parse_stages, select_stages

DEFAULT_SETTINGS = {
    "WEEKEND_DAYS": ("5,6", "Weekend weekdays, Monday=0 … Sunday=6"),
    "MAX_BACKDATE_DAYS": ("7", "How many days in the past a request may start"),
    "MAX_ADVANCE_DAYS": ("365", "How far in the future a request may start"),
    "SLA_HOURS_PER_STAGE": ("48", "Target hours for an approver to act on a pending stage"),
}


# --- pure rule helpers -----------------------------------------------------------

def parse_weekend_days(value: str) -> tuple[int, ...]:
    try:
        days = tuple(sorted({int(x) for x in value.split(",") if x.strip() != ""}))
    except ValueError:
        return DEFAULT_WEEKEND_DAYS
    return days if all(0 <= d <= 6 for d in days) else DEFAULT_WEEKEND_DAYS


def find_overlap(start: date, end: date, existing: list[tuple[date, date, str]]) -> tuple[date, date, str] | None:
    """Return the first (start, end, status) in `existing` that overlaps [start, end]."""
    for s, e, status in existing:
        if ranges_overlap(start, end, s, e):
            return s, e, status
    return None


def has_sufficient_balance(requested: int, available: Decimal) -> bool:
    return Decimal(requested) <= Decimal(available)


def document_required(leave_type: LeaveType, working_days: int) -> bool:
    return bool(leave_type.requires_document) and working_days > (leave_type.document_threshold_days or 0)


# --- policy loading --------------------------------------------------------------

@dataclass
class Policy:
    holidays: frozenset[date]
    weekend_days: tuple[int, ...]
    rules: list[ApprovalRuleSpec]
    max_backdate_days: int = 7
    max_advance_days: int = 365
    sla_hours: int = 48


def get_setting(session: Session, key: str) -> str:
    row = session.get(SystemSetting, key)
    return row.value if row else DEFAULT_SETTINGS[key][0]


def load_policy(session: Session) -> Policy:
    holidays = frozenset(session.scalars(select(Holiday.holiday_date).where(Holiday.is_active.is_(True))))
    rules = [ApprovalRuleSpec(r.min_days, parse_stages(r.stages)) for r in session.scalars(select(ApprovalRule))]
    return Policy(
        holidays=holidays,
        weekend_days=parse_weekend_days(get_setting(session, "WEEKEND_DAYS")),
        rules=rules,
        max_backdate_days=int(get_setting(session, "MAX_BACKDATE_DAYS")),
        max_advance_days=int(get_setting(session, "MAX_ADVANCE_DAYS")),
        sla_hours=int(get_setting(session, "SLA_HOURS_PER_STAGE")),
    )


# --- main validation -------------------------------------------------------------

@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    working_days: int = 0
    calendar_days: int = 0
    excluded_weekend_days: int = 0
    excluded_holidays: int = 0
    stages: tuple[Stage, ...] = ()
    needs_document: bool = False
    available_balance: Decimal | None = None
    requires_approval: bool = True

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_leave_request(session: Session, employee: Employee, leave_type: LeaveType,
                           start: date | None, end: date | None, has_document: bool,
                           today: date | None = None, policy: Policy | None = None,
                           exclude_request_id: int | None = None, lock_balance: bool = False) -> ValidationResult:
    """Run every business-rule check and return all findings (not only the first)."""
    result = ValidationResult(requires_approval=leave_type.requires_approval)
    today = today or today_local()
    policy = policy or load_policy(session)

    if not leave_type.is_active:
        result.errors.append("This leave type is not currently available.")
    if start is None or end is None:
        result.errors.append("Please select a start and end date.")
        return result
    if end < start:
        result.errors.append("The end date cannot be before the start date.")
        return result
    if start.year != end.year:
        result.errors.append("A request cannot span two calendar years. Please submit separate requests.")
        return result
    if start < today - timedelta(days=policy.max_backdate_days):
        result.errors.append(f"Leave cannot start more than {policy.max_backdate_days} days in the past.")
    if start > today + timedelta(days=policy.max_advance_days):
        result.errors.append(f"Leave cannot be requested more than {policy.max_advance_days} days in advance.")

    # Working days (weekends + company holidays excluded)
    result.calendar_days = (end - start).days + 1
    result.working_days = count_working_days(start, end, policy.holidays, policy.weekend_days)
    holiday_hits = {d for d in policy.holidays if start <= d <= end and d.weekday() not in policy.weekend_days}
    result.excluded_holidays = len(holiday_hits)
    result.excluded_weekend_days = sum(
        1 for i in range(result.calendar_days) if (start + timedelta(days=i)).weekday() in policy.weekend_days)
    if result.working_days == 0:
        result.errors.append("The selected dates contain no working days (weekends and holidays are excluded).")
        return result

    if leave_type.max_consecutive_days and result.working_days > leave_type.max_consecutive_days:
        result.errors.append(
            f"{leave_type.name} is limited to {leave_type.max_consecutive_days} working day(s) per request.")

    # Overlap with the employee's existing pending/approved requests
    stmt = select(LeaveRequest.start_date, LeaveRequest.end_date, LeaveRequest.status).where(
        LeaveRequest.employee_id == employee.id,
        LeaveRequest.status.in_([s.value for s in ACTIVE_STATUSES]),
        LeaveRequest.start_date <= end, LeaveRequest.end_date >= start)
    if exclude_request_id:
        stmt = stmt.where(LeaveRequest.id != exclude_request_id)
    clash = find_overlap(start, end, [tuple(r) for r in session.execute(stmt)])
    if clash:
        result.errors.append("An overlapping leave request already exists.")

    # Balance
    if leave_type.tracks_balance:
        balance = balance_service.get_or_create_balance(session, employee.id, leave_type, start.year, lock=lock_balance)
        result.available_balance = balance.available
        if not has_sufficient_balance(result.working_days, balance.available):
            result.errors.append("Insufficient leave balance.")

    # Documentation
    result.needs_document = document_required(leave_type, result.working_days)
    if result.needs_document and not has_document:
        result.errors.append(f"{leave_type.document_description} is required for this request.")

    # Approval chain
    if leave_type.requires_approval:
        result.stages = select_stages(result.working_days, policy.rules)
    if result.excluded_weekend_days or result.excluded_holidays:
        result.warnings.append(
            f"{result.excluded_weekend_days} weekend day(s) and {result.excluded_holidays} holiday(s) "
            f"were excluded from the duration.")
    return result
