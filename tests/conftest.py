"""Test fixtures. DB tests run against a real PostgreSQL database (TEST_DATABASE_URL) inside a
transaction that is rolled back after every test. They are skipped if PostgreSQL is unreachable."""
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import config
from auth.security import hash_password
from database import models as m
from utils.dates import tz
from workflows.engine import Actor

# Fixed "now": Monday 2 March 2026, 10:00 local time. 2026-03-04 (Wed) is a company holiday.
NOW = datetime.combine(date(2026, 3, 2), time(10, 0), tzinfo=tz()).astimezone(timezone.utc)
MONDAY = date(2026, 3, 9)
_PW_HASH = hash_password("Passw0rd!")   # hash once: bcrypt is deliberately slow


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(config.TEST_DATABASE_URL)
    try:
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL test database not reachable: {exc}")
    m.Base.metadata.drop_all(eng)
    m.Base.metadata.create_all(eng)
    yield eng
    m.Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield s
    s.close()
    trans.rollback()
    conn.close()


class World:
    """Small, explicit org: Ananya (employee) -> Karthik (lead) -> Vikram (dept head); HR: Priya, Arjun."""

    def __init__(self, s: Session):
        self.s = s
        roles = {n: m.Role(name=n) for n in config.ROLES}
        s.add_all(roles.values())
        self.casual = m.LeaveType(code="CASUAL", name="Casual Leave", annual_allowance=8, max_consecutive_days=5)
        self.sick = m.LeaveType(code="SICK", name="Sick Leave", annual_allowance=10, requires_document=True,
                                document_threshold_days=2, document_description="Medical documentation")
        self.annual = m.LeaveType(code="ANNUAL", name="Annual Leave", annual_allowance=18, can_carry_forward=True,
                                  carry_forward_limit=5)
        self.unpaid = m.LeaveType(code="UNPAID", name="Unpaid Leave", annual_allowance=0, tracks_balance=False)
        self.wfh = m.LeaveType(code="WFH", name="Work From Home", annual_allowance=0, tracks_balance=False,
                               requires_approval=False)
        s.add_all([self.casual, self.sick, self.annual, self.unpaid, self.wfh])
        s.add_all([m.ApprovalRule(min_days=0, stages="MANAGER"), m.ApprovalRule(min_days=2, stages="MANAGER,HR"),
                   m.ApprovalRule(min_days=7, stages="MANAGER,HR,DEPARTMENT_HEAD")])
        s.add(m.Holiday(holiday_date=date(2026, 3, 4), name="Test Holiday"))
        self.dept = m.Department(name="Engineering")
        self.hr_dept = m.Department(name="HR")
        s.add_all([self.dept, self.hr_dept])
        s.flush()
        self.vikram = self._person("Vikram", self.dept, None, roles[config.ROLE_MANAGER])
        self.karthik = self._person("Karthik", self.dept, self.vikram, roles[config.ROLE_MANAGER])
        self.ananya = self._person("Ananya", self.dept, self.karthik, roles[config.ROLE_EMPLOYEE])
        self.ravi = self._person("Ravi", self.dept, self.karthik, roles[config.ROLE_EMPLOYEE])
        self.priya = self._person("Priya", self.hr_dept, None, roles[config.ROLE_HR])
        self.arjun = self._person("Arjun", self.hr_dept, self.priya, roles[config.ROLE_HR])
        self.dept.head_employee_id = self.vikram.id
        s.flush()

    def _person(self, name, dept, manager, role):
        e = m.Employee(employee_code=f"T-{name}", first_name=name, last_name="Test", email=f"{name}@t.example",
                       department_id=dept.id, manager_id=manager.id if manager else None, hire_date=date(2020, 1, 1))
        self.s.add(e)
        self.s.flush()
        self.s.add(m.User(username=name.lower(), password_hash=_PW_HASH, role_id=role.id,
                          employee_id=e.id))
        self.s.flush()
        self.s.refresh(e)
        return e

    @staticmethod
    def actor(emp: m.Employee) -> Actor:
        return Actor(emp.user.id, emp.id, emp.user.role.name)

    def balance(self, emp, leave_type, year=2026):
        from services import balance_service
        return balance_service.get_or_create_balance(self.s, emp.id, leave_type, year)


@pytest.fixture
def world(session):
    return World(session)
