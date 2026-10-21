"""HR/Admin master-data operations. Every mutation is validated and audited."""
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
from auth.security import hash_password, validate_password_strength
from database.models import (
    ApprovalRule, ApprovalStep, Department, Employee, Holiday, LeaveBalance, LeaveType, Role, SystemSetting, User,
)
from services import audit_service as audit, balance_service, notification_service as ns, rules_service
from utils.dates import today_local
from utils.errors import BusinessRuleError
from workflows.engine import Actor
from workflows.states import StepStatus, parse_stages

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMP_FIELDS = ["employee_code", "first_name", "last_name", "email", "job_title", "department_id",
              "manager_id", "hire_date", "is_active"]
LT_FIELDS = ["code", "name", "description", "annual_allowance", "tracks_balance", "requires_approval",
             "requires_document", "document_threshold_days", "document_description", "can_carry_forward",
             "carry_forward_limit", "max_consecutive_days", "is_active"]


def _flush_unique(session: Session, message: str) -> None:
    """Flush and translate uniqueness violations into a user-safe message.

    The raised error propagates to session_scope(), which rolls the whole transaction back.
    """
    try:
        session.flush()
    except IntegrityError as exc:                  # never leak raw DB errors to the UI
        raise BusinessRuleError(message) from exc


def _role(session: Session, name: str) -> Role:
    role = session.scalars(select(Role).where(Role.name == name)).first()
    if role is None:
        raise BusinessRuleError("Unknown role.")
    return role


def _require_approver_capable(session: Session, employee_id: int | None, what: str) -> None:
    if employee_id is None:
        return
    emp = session.get(Employee, employee_id)
    if emp is None or not emp.is_active:
        raise BusinessRuleError(f"The selected {what} is not an active employee.")
    if emp.user is None or emp.user.role.name not in (config.ROLE_MANAGER, config.ROLE_HR):
        raise BusinessRuleError(f"{emp.full_name} needs the Manager or HR/Admin role to be assigned as {what}.")


def _check_no_cycle(session: Session, employee_id: int | None, manager_id: int | None) -> None:
    seen, current = set(), manager_id
    while current is not None:
        if current == employee_id or current in seen:
            raise BusinessRuleError("This reporting line would create a circular management chain.")
        seen.add(current)
        current = session.scalar(select(Employee.manager_id).where(Employee.id == current))


# --- employees ---------------------------------------------------------------------------------

def next_employee_code(session: Session) -> str:
    codes = session.scalars(select(Employee.employee_code).where(Employee.employee_code.like("EMP%"))).all()
    nums = [int(c[3:]) for c in codes if c[3:].isdigit()]
    return f"EMP{(max(nums) + 1) if nums else 1:03d}"


def create_employee(session: Session, actor: Actor, data: dict, username: str, password: str, role: str) -> Employee:
    for key in ("first_name", "last_name", "email", "department_id", "hire_date"):
        if not data.get(key):
            raise BusinessRuleError("Please complete all required fields.")
    if not EMAIL_RE.match(data["email"]):
        raise BusinessRuleError("Please enter a valid email address.")
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        raise BusinessRuleError("Username must be 3–40 characters (letters, digits, dot, dash, underscore).")
    validate_password_strength(password)
    _require_approver_capable(session, data.get("manager_id"), "manager")
    emp = Employee(**{k: data.get(k) for k in EMP_FIELDS if k != "is_active"}, is_active=True)
    emp.employee_code = emp.employee_code or next_employee_code(session)
    session.add(emp)
    _flush_unique(session, "An employee with this code or email already exists.")
    user = User(username=username, password_hash=hash_password(password), role_id=_role(session, role).id,
                employee_id=emp.id)
    session.add(user)
    _flush_unique(session, "This username is already taken.")
    audit.log(session, actor.user_id, "EMPLOYEE_CREATED", "Employee", emp.id,
              new={**audit.snapshot(emp, EMP_FIELDS), "username": username, "role": role})
    balance_service.list_for_employee(session, emp.id, today_local().year)
    return emp


def update_employee(session: Session, actor: Actor, employee_id: int, data: dict, role: str | None = None) -> Employee:
    emp = session.get(Employee, employee_id)
    if emp is None:
        raise BusinessRuleError("Employee not found.")
    old = {**audit.snapshot(emp, EMP_FIELDS), "role": emp.user.role.name if emp.user else None}
    if "email" in data and not EMAIL_RE.match(data["email"]):
        raise BusinessRuleError("Please enter a valid email address.")
    if "manager_id" in data:
        if data["manager_id"] == emp.id:
            raise BusinessRuleError("An employee cannot be their own manager.")
        _require_approver_capable(session, data["manager_id"], "manager")
        _check_no_cycle(session, emp.id, data["manager_id"])
    if data.get("is_active") is False and emp.is_active:
        if employee_id == actor.employee_id:
            raise BusinessRuleError("You cannot deactivate your own account.")
        _assert_can_deactivate(session, emp)
    for key, value in data.items():
        if key in EMP_FIELDS:
            setattr(emp, key, value)
    if role and emp.user and role != emp.user.role.name:
        if role == config.ROLE_EMPLOYEE:
            _assert_no_approver_duties(session, emp)
        if employee_id == actor.employee_id:
            raise BusinessRuleError("You cannot change your own role.")
        emp.user.role_id = _role(session, role).id
    if emp.user and "is_active" in data:
        emp.user.is_active = data["is_active"]
    _flush_unique(session, "An employee with this code or email already exists.")
    audit.log(session, actor.user_id, "EMPLOYEE_UPDATED", "Employee", emp.id, old=old,
              new={**audit.snapshot(emp, EMP_FIELDS), "role": emp.user.role.name if emp.user else None})
    return emp


def _assert_no_approver_duties(session: Session, emp: Employee) -> None:
    has_reports = session.scalar(select(func.count(Employee.id)).where(
        Employee.manager_id == emp.id, Employee.is_active.is_(True))) or 0
    heads = session.scalar(select(func.count(Department.id)).where(Department.head_employee_id == emp.id)) or 0
    if has_reports or heads:
        raise BusinessRuleError(f"{emp.full_name} manages people or a department – reassign them first.")


def _assert_can_deactivate(session: Session, emp: Employee) -> None:
    _assert_no_approver_duties(session, emp)
    pending = session.scalar(select(func.count(ApprovalStep.id)).where(
        ApprovalStep.approver_employee_id == emp.id, ApprovalStep.status == StepStatus.PENDING.value)) or 0
    if pending:
        raise BusinessRuleError(f"{emp.full_name} has {pending} pending approval(s) – resolve them first.")


# --- departments --------------------------------------------------------------------------------

def save_department(session: Session, actor: Actor, name: str, head_employee_id: int | None,
                    department_id: int | None = None) -> Department:
    name = (name or "").strip()
    if not name:
        raise BusinessRuleError("Department name is required.")
    _require_approver_capable(session, head_employee_id, "department head")
    dept = session.get(Department, department_id) if department_id else None
    old = None
    if dept is None:
        dept = Department(name=name, head_employee_id=head_employee_id)
        session.add(dept)
    else:
        old = {"name": dept.name, "head_employee_id": dept.head_employee_id}
        dept.name, dept.head_employee_id = name, head_employee_id
    _flush_unique(session, "A department with this name already exists.")
    audit.log(session, actor.user_id, "DEPARTMENT_UPDATED" if old else "DEPARTMENT_CREATED", "Department", dept.id,
              old=old, new={"name": name, "head_employee_id": head_employee_id})
    return dept


# --- leave types ----------------------------------------------------------------------------------

def save_leave_type(session: Session, actor: Actor, data: dict, leave_type_id: int | None = None) -> LeaveType:
    lt = session.get(LeaveType, leave_type_id) if leave_type_id else None
    old = audit.snapshot(lt, LT_FIELDS) if lt else None
    data = {**(old or {}), **data}                       # partial updates keep existing values
    data["code"], data["name"] = (data.get("code") or "").strip().upper(), (data.get("name") or "").strip()
    if not data["code"] or not data["name"]:
        raise BusinessRuleError("Leave type code and name are required.")
    if Decimal(str(data.get("annual_allowance") or 0)) < 0:
        raise BusinessRuleError("Annual allowance cannot be negative.")
    if lt is None:
        lt = LeaveType()
        session.add(lt)
    for key in LT_FIELDS:
        if key in data:
            setattr(lt, key, data[key])
    _flush_unique(session, "A leave type with this code or name already exists.")
    audit.log(session, actor.user_id, "LEAVE_TYPE_UPDATED" if old else "LEAVE_TYPE_CREATED", "LeaveType", lt.id,
              old=old, new=audit.snapshot(lt, LT_FIELDS))
    return lt


# --- holidays ---------------------------------------------------------------------------------------

def save_holiday(session: Session, actor: Actor, holiday_date: date, name: str, is_active: bool = True,
                 holiday_id: int | None = None) -> Holiday:
    if not (name or "").strip():
        raise BusinessRuleError("Holiday name is required.")
    h = session.get(Holiday, holiday_id) if holiday_id else None
    old = {"holiday_date": h.holiday_date, "name": h.name, "is_active": h.is_active} if h else None
    if h is None:
        h = Holiday()
        session.add(h)
    h.holiday_date, h.name, h.is_active = holiday_date, name.strip(), is_active
    _flush_unique(session, "A holiday already exists on this date.")
    audit.log(session, actor.user_id, "HOLIDAY_UPDATED" if old else "HOLIDAY_CREATED", "Holiday", h.id, old=old,
              new={"holiday_date": holiday_date, "name": name.strip(), "is_active": is_active})
    return h


def delete_holiday(session: Session, actor: Actor, holiday_id: int) -> None:
    h = session.get(Holiday, holiday_id)
    if h is None:
        raise BusinessRuleError("Holiday not found.")
    audit.log(session, actor.user_id, "HOLIDAY_DELETED", "Holiday", h.id,
              old={"holiday_date": h.holiday_date, "name": h.name})
    session.delete(h)


# --- balances ----------------------------------------------------------------------------------------

def update_balance(session: Session, actor: Actor, employee_id: int, leave_type_id: int, year: int,
                   allocated: Decimal, carried_forward: Decimal) -> LeaveBalance:
    lt = session.get(LeaveType, leave_type_id)
    bal = balance_service.get_or_create_balance(session, employee_id, lt, year, lock=True)
    allocated, carried_forward = Decimal(str(allocated)), Decimal(str(carried_forward))
    if allocated < 0 or carried_forward < 0:
        raise BusinessRuleError("Balances cannot be negative.")
    if allocated + carried_forward < (bal.used or 0) + (bal.pending or 0):
        raise BusinessRuleError("The new total cannot be lower than days already used or pending.")
    old = {"allocated": bal.allocated, "carried_forward": bal.carried_forward}
    bal.allocated, bal.carried_forward = allocated, carried_forward
    audit.log(session, actor.user_id, "BALANCE_UPDATED", "LeaveBalance", bal.id, old=old,
              new={"allocated": allocated, "carried_forward": carried_forward, "employee_id": employee_id,
                   "leave_type": lt.name, "year": year})
    emp = session.get(Employee, employee_id)
    if emp.user:
        ns.notify(session, emp.user.id, "Leave balance updated",
                  f"HR updated your {lt.name} balance for {year}: {bal.available} day(s) available.",
                  ns.BALANCE_UPDATED)
    return bal


def allocate_year(session: Session, actor: Actor, year: int) -> int:
    created = balance_service.allocate_year(session, year)
    audit.log(session, actor.user_id, "BALANCES_ALLOCATED", "LeaveBalance", None, new={"year": year, "created": created})
    return created


# --- approval policy & settings ----------------------------------------------------------------------

def save_approval_rule(session: Session, actor: Actor, min_days: int, stages: list[str],
                       rule_id: int | None = None, description: str | None = None) -> ApprovalRule:
    if not stages:
        raise BusinessRuleError("Select at least one approval stage.")
    stage_str = ",".join(s.value for s in parse_stages(",".join(stages)))
    rule = session.get(ApprovalRule, rule_id) if rule_id else None
    old = {"min_days": rule.min_days, "stages": rule.stages} if rule else None
    if rule is None:
        rule = ApprovalRule()
        session.add(rule)
    rule.min_days, rule.stages, rule.description = int(min_days), stage_str, description
    _flush_unique(session, "An approval rule for this duration threshold already exists.")
    audit.log(session, actor.user_id, "APPROVAL_RULE_UPDATED" if old else "APPROVAL_RULE_CREATED", "ApprovalRule",
              rule.id, old=old, new={"min_days": rule.min_days, "stages": stage_str})
    return rule


def delete_approval_rule(session: Session, actor: Actor, rule_id: int) -> None:
    rule = session.get(ApprovalRule, rule_id)
    if rule is None:
        raise BusinessRuleError("Rule not found.")
    if rule.min_days == 0:
        raise BusinessRuleError("The base rule (threshold 0) cannot be deleted – edit it instead.")
    audit.log(session, actor.user_id, "APPROVAL_RULE_DELETED", "ApprovalRule", rule.id,
              old={"min_days": rule.min_days, "stages": rule.stages})
    session.delete(rule)


def save_setting(session: Session, actor: Actor, key: str, value: str) -> None:
    if key not in rules_service.DEFAULT_SETTINGS:
        raise BusinessRuleError("Unknown setting.")
    value = str(value).strip()
    if key == "WEEKEND_DAYS":
        try:
            days = sorted({int(x) for x in value.split(",") if x.strip()})
        except ValueError:
            days = [-1]
        if not all(0 <= d <= 6 for d in days) or len(days) > 6:
            raise BusinessRuleError("Weekend days must be numbers 0 (Monday) to 6 (Sunday), at most six of them.")
        value = ",".join(map(str, days))
    else:
        minimum = 1 if key == "SLA_HOURS_PER_STAGE" else 0
        if not value.isdigit() or int(value) < minimum:
            raise BusinessRuleError("This setting must be a whole number" + (" greater than zero." if minimum else "."))
    row = session.get(SystemSetting, key)
    old = row.value if row else rules_service.DEFAULT_SETTINGS[key][0]
    if row is None:
        row = SystemSetting(key=key, description=rules_service.DEFAULT_SETTINGS[key][1], value=value)
        session.add(row)
    row.value = value
    audit.log(session, actor.user_id, "SETTING_UPDATED", "SystemSetting", key, old={"value": old}, new={"value": value})
