"""Demo data. Master data is inserted directly; leave history is generated through the real services
(with an injected clock) so balances, approval steps, notifications and audit logs are consistent.

    python -m seed.seed_data            # seed an empty database
    python -m seed.seed_data --reset    # drop + recreate + seed
"""
import argparse
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import config
from auth.security import hash_password
from database import models as m
from database.connection import session_scope
from services import audit_service, balance_service, leave_service, rules_service
from utils.dates import now_utc, today_local, tz
from utils.errors import BusinessRuleError
from workflows import engine
from workflows.engine import Actor
from workflows.states import PENDING_STATUSES, RequestStatus

DEMO_PASSWORDS = {"employee": "Employee@123", "manager": "Manager@123", "hr": "HrAdmin@123"}
DEFAULT_PASSWORD = "Welcome@123"

LEAVE_TYPES = [
    dict(code="CASUAL", name="Casual Leave", description="Short personal time off for planned or unplanned needs.",
         annual_allowance=8, max_consecutive_days=3),
    dict(code="SICK", name="Sick Leave", description="Absence due to illness or medical appointments.",
         annual_allowance=10, requires_document=True, document_threshold_days=2,
         document_description="Medical documentation", max_consecutive_days=10),
    dict(code="ANNUAL", name="Annual / Earned Leave", description="Planned vacation and earned time off.",
         annual_allowance=18, can_carry_forward=True, carry_forward_limit=10, max_consecutive_days=15),
    dict(code="UNPAID", name="Unpaid Leave", description="Leave without pay; not deducted from any balance.",
         annual_allowance=0, tracks_balance=False, max_consecutive_days=30),
    dict(code="WFH", name="Work From Home", description="Remote working day(s); confirmed automatically.",
         annual_allowance=0, tracks_balance=False, requires_approval=False, max_consecutive_days=5),
]

# (code, first, last, title, department, manager code, role, username override)
E, M, H = config.ROLE_EMPLOYEE, config.ROLE_MANAGER, config.ROLE_HR
PEOPLE = [
    ("EMP001", "Priya", "Sharma", "Head of HR", "Human Resources", None, H, "hr"),
    ("EMP002", "Arjun", "Mehta", "HR Business Partner", "Human Resources", "EMP001", H, None),
    ("EMP003", "Neha", "Kapoor", "HR Executive", "Human Resources", "EMP001", E, None),
    ("EMP004", "Sanjay", "Pillai", "HR Executive", "Human Resources", "EMP001", E, None),
    ("EMP005", "Vikram", "Nair", "Head of Engineering", "Engineering", None, M, None),
    ("EMP006", "Karthik", "Rao", "Engineering Team Lead", "Engineering", "EMP005", M, "manager"),
    ("EMP007", "Meera", "Joshi", "Engineering Team Lead", "Engineering", "EMP005", M, None),
    ("EMP008", "Ananya", "Iyer", "Software Engineer", "Engineering", "EMP006", E, "employee"),
    ("EMP009", "Rohan", "Das", "Software Engineer", "Engineering", "EMP006", E, None),
    ("EMP010", "Divya", "Menon", "QA Engineer", "Engineering", "EMP006", E, None),
    ("EMP011", "Aditya", "Singh", "DevOps Engineer", "Engineering", "EMP006", E, None),
    ("EMP012", "Pooja", "Reddy", "Software Engineer", "Engineering", "EMP007", E, None),
    ("EMP013", "Siddharth", "Jain", "Data Engineer", "Engineering", "EMP007", E, None),
    ("EMP014", "Lakshmi", "Narayan", "Software Engineer", "Engineering", "EMP007", E, None),
    ("EMP015", "Rajesh", "Gupta", "Finance Controller", "Finance", None, M, None),
    ("EMP016", "Sunita", "Bose", "Senior Accountant", "Finance", "EMP015", E, None),
    ("EMP017", "Manish", "Agarwal", "Financial Analyst", "Finance", "EMP015", E, None),
    ("EMP018", "Kavya", "Shetty", "Accounts Executive", "Finance", "EMP015", E, None),
    ("EMP019", "Imran", "Qureshi", "Payroll Specialist", "Finance", "EMP015", E, None),
    ("EMP020", "Deepak", "Malhotra", "Sales Director", "Sales", None, M, None),
    ("EMP021", "Anjali", "Desai", "Account Executive", "Sales", "EMP020", E, None),
    ("EMP022", "Farhan", "Sheikh", "Account Executive", "Sales", "EMP020", E, None),
    ("EMP023", "Tanvi", "Kulkarni", "Sales Analyst", "Sales", "EMP020", E, None),
    ("EMP024", "Rahul", "Chopra", "Business Development Rep", "Sales", "EMP020", E, None),
    ("EMP025", "Isha", "Bhatt", "Account Executive", "Sales", "EMP020", E, None),
    ("EMP026", "Suresh", "Patil", "Operations Head", "Operations", None, M, None),
    ("EMP027", "Nandini", "Rao", "Logistics Coordinator", "Operations", "EMP026", E, None),
    ("EMP028", "Vivek", "Kumar", "Process Analyst", "Operations", "EMP026", E, None),
    ("EMP029", "Shreya", "Ghosh", "Supply Planner", "Operations", "EMP026", E, None),
    ("EMP030", "Harish", "Naidu", "Facilities Coordinator", "Operations", "EMP026", E, None),
    ("EMP031", "Pallavi", "Mishra", "Customer Support Head", "Customer Support", None, M, None),
    ("EMP032", "Arun", "Prakash", "Support Specialist", "Customer Support", "EMP031", E, None),
    ("EMP033", "Swati", "Menon", "Support Specialist", "Customer Support", "EMP031", E, None),
    ("EMP034", "Kiran", "Hegde", "Support Specialist", "Customer Support", "EMP031", E, None),
    ("EMP035", "Zoya", "Khan", "Support Specialist", "Customer Support", "EMP031", E, None),
]
DEPT_HEADS = {"Human Resources": "EMP001", "Engineering": "EMP005", "Finance": "EMP015",
              "Sales": "EMP020", "Operations": "EMP026", "Customer Support": "EMP031"}

HOLIDAYS = [(1, 1, "New Year's Day"), (1, 26, "Republic Day"), (5, 1, "Labour Day"), (7, 1, "Company Foundation Day"),
            (8, 15, "Independence Day"), (10, 2, "Gandhi Jayanti"), (12, 24, "Year-End Shutdown"),
            (12, 25, "Christmas Day")]

REJECTION_REASONS = [
    "Critical project deadline during this period. Please reschedule.",
    "Too many team members are already away on these dates.",
    "Month-end closing – leave cannot be accommodated.",
    "Please provide a handover plan and resubmit.",
]
DURATIONS = {"CASUAL": [1, 1, 2, 2, 3], "SICK": [1, 1, 2, 3, 4], "ANNUAL": [2, 3, 4, 5, 8, 10],
             "UNPAID": [1, 2, 5], "WFH": [1, 1, 2, 3]}
TYPE_WEIGHTS = {"CASUAL": 30, "SICK": 22, "ANNUAL": 26, "UNPAID": 4, "WFH": 18}
FAKE_DOC = ("medical_certificate.pdf", b"%PDF-1.4\n% LeaveFlow demo document\n")


def _local_dt(d: date, hour: float) -> datetime:
    return datetime.combine(d, time(int(hour), int((hour % 1) * 60)), tzinfo=tz()).astimezone(timezone.utc)


def _end_for(start: date, n: int, policy) -> tuple[date, date]:
    d = start
    while d.weekday() in policy.weekend_days or d in policy.holidays:
        d += timedelta(days=1)
    start, count = d, 0
    while True:
        if d.weekday() not in policy.weekend_days and d not in policy.holidays:
            count += 1
        if count == n:
            return start, d
        d += timedelta(days=1)


def seed_master_data(session: Session) -> dict:
    today = today_local()
    roles = {n: m.Role(name=n, description=d) for n, d in [
        (E, "Standard employee"), (M, "Team manager / approver"), (H, "HR and system administrator")]}
    session.add_all(roles.values())
    session.add_all([m.LeaveType(**lt) for lt in LEAVE_TYPES])
    session.add_all([
        m.ApprovalRule(min_days=0, stages="MANAGER", description="Up to 2 working days: manager approval"),
        m.ApprovalRule(min_days=2, stages="MANAGER,HR", description="More than 2 working days: manager + HR"),
        m.ApprovalRule(min_days=7, stages="MANAGER,HR,DEPARTMENT_HEAD",
                       description="More than 7 working days: manager + HR + department head"),
    ])
    session.add_all([m.SystemSetting(key=k, value=v, description=d) for k, (v, d) in rules_service.DEFAULT_SETTINGS.items()])
    for year in (today.year - 1, today.year, today.year + 1):
        for mo, day, name in HOLIDAYS:
            session.add(m.Holiday(holiday_date=date(year, mo, day), name=name))
    depts = {n: m.Department(name=n) for n in DEPT_HEADS}
    session.add_all(depts.values())
    session.flush()

    rng = random.Random(7)
    pw_hashes = {k: hash_password(v) for k, v in DEMO_PASSWORDS.items()}
    default_hash = hash_password(DEFAULT_PASSWORD)
    emps: dict[str, m.Employee] = {}
    for code, first, last, title, dept, _, role, uname in PEOPLE:
        emp = m.Employee(employee_code=code, first_name=first, last_name=last, job_title=title,
                         email=f"{first}.{last}@leaveflow.example".lower(), department_id=depts[dept].id,
                         hire_date=date(rng.randint(2017, 2025), rng.randint(1, 12), rng.randint(1, 28)))
        emps[code] = emp
        session.add(emp)
    session.flush()
    for code, *_rest in PEOPLE:
        mgr_code = _rest[4]
        emps[code].manager_id = emps[mgr_code].id if mgr_code else None
    for dept, code in DEPT_HEADS.items():
        depts[dept].head_employee_id = emps[code].id
    session.flush()
    for code, first, last, _t, _d, _m, role, uname in PEOPLE:
        username = uname or f"{first}.{last}".lower()
        session.add(m.User(username=username, role_id=roles[role].id, employee_id=emps[code].id,
                           password_hash=pw_hashes.get(uname, default_hash)))
    session.flush()
    return emps


def _approver_actor(session: Session, step: m.ApprovalStep, request: m.LeaveRequest) -> Actor:
    if step.approver_employee_id:
        u = session.scalars(select(m.User).where(m.User.employee_id == step.approver_employee_id)).first()
        return Actor(u.id, u.employee_id, u.role.name)
    hr = session.scalars(select(m.User).join(m.Role).where(
        m.Role.name == H, m.User.employee_id != request.employee_id)).first()
    return Actor(hr.id, hr.employee_id, hr.role.name)


def _delay_hours(rng: random.Random, stage: str, fast: bool) -> float:
    if fast:
        return rng.uniform(1, 20)
    r = rng.random()
    if stage == "HR":
        return rng.uniform(4, 36) if r < 0.65 else rng.uniform(36, 120)
    if stage == "DEPARTMENT_HEAD":
        return rng.uniform(6, 40) if r < 0.7 else rng.uniform(40, 96)
    return rng.uniform(1, 24) if r < 0.65 else (rng.uniform(24, 48) if r < 0.88 else rng.uniform(48, 96))


def _process(session, rng, request, submitted_at, real_now, outcome="auto", max_decisions=None, fast=False):
    """Walk the approval chain forward in simulated time, stopping when `real_now` is reached."""
    t, decisions = submitted_at, 0
    cancel_at = submitted_at + timedelta(hours=rng.uniform(1, 30)) if outcome == "cancel" else None
    reject_at = rng.randint(0, 2) if outcome == "reject" else None
    while RequestStatus(request.status) in PENDING_STATUSES:
        if max_decisions is not None and decisions >= max_decisions:
            return
        step = engine.pending_step(request)
        actor = _approver_actor(session, step, request)
        t_next = t + timedelta(hours=_delay_hours(rng, step.stage, fast))
        if cancel_at and cancel_at < t_next and cancel_at < real_now:
            leave_service.cancel_request(session, Actor(request.employee.user.id, request.employee_id,
                                                        request.employee.user.role.name), request.id, cancel_at)
            return
        t = t_next
        if t > real_now - timedelta(hours=1):
            return
        if reject_at is not None and decisions >= reject_at:
            leave_service.reject_request(session, actor, request.id, rng.choice(REJECTION_REASONS), t)
            return
        leave_service.approve_request(session, actor, request.id, None, t)
        decisions += 1


def _submit(session, rng, emp, lt_code, start, n, submit_at, real_now, **proc):
    lt = session.scalars(select(m.LeaveType).where(m.LeaveType.code == lt_code)).first()
    policy = rules_service.load_policy(session)
    start, end = _end_for(start, n, policy)
    actor = Actor(emp.user.id, emp.id, emp.user.role.name)
    doc = FAKE_DOC if lt_code == "SICK" and n > 2 else None
    try:
        with session.begin_nested():
            req = leave_service.submit_leave_request(
                session, actor, lt.id, start, end, rng.choice(
                    ["Family function", "Medical appointment", "Personal commitments", "Travel plans",
                     "Rest and recovery", "Home maintenance", None]), doc, submit_at)
            _process(session, rng, req, submit_at, real_now, **proc)
        return req
    except BusinessRuleError:
        return None


def seed_history(session: Session, emps: dict) -> dict:
    rng = random.Random(2026)
    today, real_now = today_local(), now_utc()
    year = today.year
    for emp in emps.values():                                  # balances + some carry-forward variety
        balance_service.list_for_employee(session, emp.id, year)
    annual = session.scalars(select(m.LeaveType).where(m.LeaveType.code == "ANNUAL")).first()
    for emp in emps.values():
        if rng.random() < 0.35:
            b = balance_service.get_or_create_balance(session, emp.id, annual, year)
            b.carried_forward = Decimal(rng.choice([2, 3, 5]))
    session.flush()
    for e in emps.values():
        session.refresh(e)

    by_user = {e.user.username: e for e in emps.values()}
    codes, weights = list(TYPE_WEIGHTS), list(TYPE_WEIGHTS.values())
    counts = {"history": 0, "upcoming": 0, "pending": 0}

    # 1) Demo scenarios first so the three demo accounts always have a rich, predictable story
    ananya, karthik, priya = by_user["employee"], by_user["manager"], by_user["hr"]
    demo = [
        (ananya, "ANNUAL", today - timedelta(days=50), 8, 62, dict()),          # 3-stage approval, completed
        (ananya, "SICK", today - timedelta(days=33), 3, -33, dict()),
        (ananya, "CASUAL", today - timedelta(days=20), 2, 24, dict(outcome="reject")),
        (ananya, "WFH", today - timedelta(days=9), 1, 10, dict()),
        (ananya, "ANNUAL", today + timedelta(days=21), 4, 10, dict(fast=True)),
        (ananya, "CASUAL", today + timedelta(days=9), 1, 2, dict(max_decisions=0)),
        (karthik, "ANNUAL", today - timedelta(days=40), 4, 55, dict()),
        (karthik, "CASUAL", today + timedelta(days=14), 2, 5, dict(fast=True)),
        (priya, "ANNUAL", today + timedelta(days=30), 5, 14, dict(fast=True)),
    ]
    team = [by_user[u] for u in ("rohan.das", "divya.menon", "aditya.singh")]
    demo += [
        (team[0], "ANNUAL", today + timedelta(days=12), 9, 3, dict(max_decisions=1)),   # 3-stage, at HR
        (team[1], "CASUAL", today + timedelta(days=6), 2, 1, dict(max_decisions=0)),
        (team[2], "SICK", today - timedelta(days=1), 1, -1, dict(max_decisions=0)),
        (by_user["pooja.reddy"], "ANNUAL", today + timedelta(days=25), 9, 4, dict(max_decisions=2, fast=True)),  # waiting at dept head
        (by_user["sunita.bose"], "ANNUAL", today + timedelta(days=18), 6, 5, dict(max_decisions=0)),   # breaching SLA
        (by_user["farhan.sheikh"], "CASUAL", today + timedelta(days=7), 3, 3, dict(max_decisions=0)),
        (by_user["vivek.kumar"], "ANNUAL", today + timedelta(days=40), 8, 3, dict(max_decisions=2)),
        (by_user["kavya.shetty"], "ANNUAL", today + timedelta(days=22), 4, 3, dict(max_decisions=1, fast=True)),
        (by_user["nandini.rao"], "ANNUAL", today + timedelta(days=10), 3, 3, dict(max_decisions=1, fast=True)),
        (by_user["isha.bhatt"], "ANNUAL", today + timedelta(days=27), 5, 4, dict(max_decisions=1, fast=True)),
        (by_user["swati.menon"], "UNPAID", today + timedelta(days=16), 4, 2, dict(max_decisions=0)),
    ]
    for emp, code, start, n, submit_back, proc in demo:
        submit_at = real_now - timedelta(days=submit_back) if submit_back > 0 else _local_dt(start - timedelta(days=submit_back), 9.5)
        if code == "SICK" and submit_back < 0:
            submit_at = _local_dt(min(start + timedelta(days=1), today), 9.5)
        if proc.get("max_decisions") is not None:                       # pending ones: submitted recently
            submit_at = real_now - timedelta(hours=abs(submit_back) * 18)
        r = _submit(session, rng, emp, code, start, n, submit_at, real_now, **proc)
        if r:
            counts["pending" if RequestStatus(r.status) in PENDING_STATUSES else "history"] += 1

    # 2) Randomised history for everybody (Jan 1 → a week ago)
    specs = []
    first_day = date(year, 1, 5)
    span = max(10, (today - timedelta(days=7) - first_day).days)
    for emp in emps.values():
        for _ in range(rng.randint(3, 8)):
            code = rng.choices(codes, weights)[0]
            start = first_day + timedelta(days=rng.randint(0, span))
            n = rng.choice(DURATIONS[code])
            lead = -rng.randint(0, 2) if code == "SICK" else rng.randint(1, 5) if code in ("CASUAL", "WFH") else rng.randint(4, 21)
            submit_day = min(start - timedelta(days=lead), today - timedelta(days=2))
            r = rng.random()
            outcome = "cancel" if r < 0.05 else "reject" if r < 0.20 else "auto"
            specs.append((_local_dt(submit_day, rng.uniform(9, 17.5)), emp, code, start, n, outcome))
    for submit_at, emp, code, start, n, outcome in sorted(specs, key=lambda s: s[0]):
        if _submit(session, rng, emp, code, start, n, submit_at, real_now, outcome=outcome):
            counts["history"] += 1

    # 3) A few more approved upcoming absences so calendars are busy
    for emp in rng.sample(list(emps.values()), 8):
        start = today + timedelta(days=rng.randint(3, 45))
        code = rng.choice(["ANNUAL", "CASUAL", "WFH"])
        if _submit(session, rng, emp, code, start, rng.choice(DURATIONS[code]),
                   real_now - timedelta(days=rng.randint(3, 9)), real_now, fast=True):
            counts["upcoming"] += 1
    return counts


def seed_database() -> None:
    with session_scope() as session:
        if session.scalar(select(func.count(m.Role.id))):
            print("Database already contains data – use --reset to rebuild it.")
            return
        emps = seed_master_data(session)
        hr = session.scalars(select(m.User).where(m.User.username == "hr")).first()
        audit_service.log(session, hr.id, "DATABASE_SEEDED", "System", None,
                          new={"employees": len(emps), "leave_types": len(LEAVE_TYPES)})
        for e in emps.values():
            session.refresh(e)
        counts = seed_history(session, emps)
        # Everything except the last ~36 hours of notifications is already "read"
        session.execute(m.Notification.__table__.update().where(
            m.Notification.created_at < now_utc() - timedelta(hours=36)).values(is_read=True))
        print("Seeded:", counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    from database.init_db import create_all, drop_all
    if args.reset:
        drop_all()
    create_all()
    seed_database()


if __name__ == "__main__":
    main()
