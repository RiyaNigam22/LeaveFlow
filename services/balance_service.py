"""Leave balance bookkeeping.

Lifecycle of a request's days:  submit -> pending += d ; approve -> pending -= d, used += d ;
reject / cancel -> pending -= d ; revoke approved -> used -= d.
available = allocated + carried_forward - used - pending
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Employee, LeaveBalance, LeaveRequest, LeaveType

ZERO = Decimal("0")


def get_or_create_balance(session: Session, employee_id: int, leave_type: LeaveType, year: int,
                          lock: bool = False) -> LeaveBalance:
    stmt = select(LeaveBalance).where(
        LeaveBalance.employee_id == employee_id, LeaveBalance.leave_type_id == leave_type.id,
        LeaveBalance.year == year)
    if lock:
        stmt = stmt.with_for_update()
    balance = session.scalars(stmt).first()
    if balance is None:
        balance = LeaveBalance(employee_id=employee_id, leave_type_id=leave_type.id, year=year,
                               allocated=leave_type.annual_allowance, carried_forward=ZERO, used=ZERO, pending=ZERO)
        session.add(balance)
        session.flush()
    return balance


def _balance_for(session: Session, request: LeaveRequest) -> LeaveBalance | None:
    if not request.leave_type.tracks_balance:
        return None
    return get_or_create_balance(session, request.employee_id, request.leave_type, request.start_date.year, lock=True)


def reserve(session: Session, request: LeaveRequest) -> None:
    b = _balance_for(session, request)
    if b:
        b.pending = (b.pending or ZERO) + Decimal(request.working_days)


def release(session: Session, request: LeaveRequest) -> None:
    """Return reserved (pending) days – used for rejection and cancellation of open requests."""
    b = _balance_for(session, request)
    if b:
        b.pending = max(ZERO, (b.pending or ZERO) - Decimal(request.working_days))


def commit_used(session: Session, request: LeaveRequest) -> None:
    """Final approval: convert reserved days into used days."""
    b = _balance_for(session, request)
    if b:
        d = Decimal(request.working_days)
        b.pending = max(ZERO, (b.pending or ZERO) - d)
        b.used = (b.used or ZERO) + d


def revoke_used(session: Session, request: LeaveRequest) -> None:
    """HR cancels an already-approved request: give the days back."""
    b = _balance_for(session, request)
    if b:
        b.used = max(ZERO, (b.used or ZERO) - Decimal(request.working_days))


def list_for_employee(session: Session, employee_id: int, year: int) -> list[LeaveBalance]:
    """Balances for all active, balance-tracked leave types (created lazily at the default allowance)."""
    types = session.scalars(select(LeaveType).where(
        LeaveType.is_active.is_(True), LeaveType.tracks_balance.is_(True)).order_by(LeaveType.name)).all()
    return [get_or_create_balance(session, employee_id, lt, year) for lt in types]


def allocate_year(session: Session, year: int) -> int:
    """Create balances for `year` for every active employee and tracked leave type that lacks one.

    Unused days are carried forward from `year - 1` for leave types that allow it (up to the
    configured limit). Returns the number of balance rows created.
    """
    types = session.scalars(select(LeaveType).where(
        LeaveType.is_active.is_(True), LeaveType.tracks_balance.is_(True))).all()
    employees = session.scalars(select(Employee).where(Employee.is_active.is_(True))).all()
    existing = {(b.employee_id, b.leave_type_id) for b in session.scalars(
        select(LeaveBalance).where(LeaveBalance.year == year))}
    previous = {(b.employee_id, b.leave_type_id): b for b in session.scalars(
        select(LeaveBalance).where(LeaveBalance.year == year - 1))}
    created = 0
    for emp in employees:
        for lt in types:
            if (emp.id, lt.id) in existing:
                continue
            carry = ZERO
            prev = previous.get((emp.id, lt.id))
            if lt.can_carry_forward and prev is not None:
                carry = min(max(prev.available, ZERO), lt.carry_forward_limit or ZERO)
            session.add(LeaveBalance(employee_id=emp.id, leave_type_id=lt.id, year=year,
                                     allocated=lt.annual_allowance, carried_forward=carry, used=ZERO, pending=ZERO))
            created += 1
    session.flush()
    return created
