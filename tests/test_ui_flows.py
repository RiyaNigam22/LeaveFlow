"""UI smoke/flow tests using Streamlit's AppTest against a freshly seeded isolated database."""
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select

import config
from database import connection, init_db, models as m
from utils.dates import today_local

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page(name: str) -> str:
    return os.path.join(ROOT, name)


@pytest.fixture(scope="module")
def seeded():
    eng = create_engine(config.TEST_DATABASE_URL)
    try:
        eng.connect().close()
    except Exception as exc:
        pytest.skip(f"PostgreSQL test database not reachable: {exc}")
    previous = connection._engine
    connection.set_engine(eng)
    init_db.drop_all(eng)
    init_db.create_all(eng)
    from seed.seed_data import seed_database
    seed_database()
    yield eng
    init_db.drop_all(eng)
    init_db.create_all(eng)          # leave an empty schema for other test modules
    if previous is not None:
        connection.set_engine(previous)


def login_state(username):
    with connection.session_scope() as s:
        u = s.scalars(select(m.User).where(m.User.username == username)).first()
        return {"user_id": u.id, "username": u.username, "role": u.role.name, "employee_id": u.employee_id,
                "full_name": u.employee.full_name, "department_id": u.employee.department_id,
                "last_seen": datetime.now(timezone.utc)}


def open_page(name, username):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(page(name), default_timeout=60)
    at.session_state["auth_user"] = login_state(username)
    return at.run()


ALL_PAGES = {
    "employee": ["employee_dashboard", "request_leave", "my_requests", "notifications"],
    "manager": ["manager_dashboard", "manager_approvals", "manager_history", "team_calendar"],
    "hr": ["hr_dashboard", "hr_analytics", "hr_requests", "hr_employees", "hr_policies", "hr_balances", "hr_audit",
           "manager_approvals", "team_calendar"],
}


@pytest.mark.parametrize("user,name", [(u, n) for u, pages in ALL_PAGES.items() for n in pages])
def test_every_page_renders_without_errors(seeded, user, name):
    at = open_page(f"pages/{name}.py", user)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]


@pytest.mark.parametrize("user,name", [("employee", "hr_audit"), ("employee", "manager_approvals"),
                                       ("employee", "manager_dashboard"), ("manager", "hr_employees"),
                                       ("manager", "hr_requests"), ("employee", "team_calendar")])
def test_role_guard_blocks_direct_access(seeded, user, name):
    at = open_page(f"pages/{name}.py", user)
    assert any("permission" in e.value for e in at.error)
    assert len(at.dataframe) == 0


def test_anonymous_user_is_refused(seeded):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(page("pages/hr_audit.py"), default_timeout=30).run()
    assert at.warning and len(at.dataframe) == 0


def test_login_screen_rejects_bad_password_then_accepts_good_one(seeded):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(page("app.py"), default_timeout=60).run()
    at.text_input[0].set_value("employee")
    at.text_input[1].set_value("wrong-password")
    at.button[0].click().run()
    assert [e.value for e in at.error] == ["Invalid username or password."]
    at.text_input[1].set_value("Employee@123")
    at.button[0].click().run()
    assert not at.exception and not at.error
    assert any("lf-kpi" in md.value for md in at.markdown)          # dashboard rendered after login


def test_submit_leave_request_through_the_form(seeded):
    at = open_page("pages/request_leave.py", "employee")
    names = {o: i for i, o in enumerate(at.selectbox[0].options)}
    at.selectbox[0].select_index(names["Casual Leave"])
    day = today_local() + timedelta(days=75)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    at.date_input[0].set_value(day).run()
    at.date_input[1].set_value(day).run()
    submit = next(b for b in at.button if b.label == "Submit request")
    assert not submit.disabled, [e.value for e in at.error]
    submit.click().run()
    assert not at.error, [e.value for e in at.error]
    at = open_page("pages/my_requests.py", "employee")        # survives reload; visible in history
    with connection.session_scope() as s:
        req = s.scalars(select(m.LeaveRequest).where(m.LeaveRequest.start_date == day).order_by(
            m.LeaveRequest.id.desc())).first()
        assert req is not None and req.status == "MANAGER_PENDING" and req.steps[0].approver.full_name == "Karthik Rao"


def test_form_blocks_invalid_request_with_clear_message(seeded):
    at = open_page("pages/request_leave.py", "employee")
    names = {o: i for i, o in enumerate(at.selectbox[0].options)}
    at.selectbox[0].select_index(names["Sick Leave"])
    day = today_local() + timedelta(days=100)
    while day.weekday() != 0:
        day += timedelta(days=1)
    at.date_input[0].set_value(day).run()
    at.date_input[1].set_value(day + timedelta(days=3)).run()             # 4 working days > threshold, no document
    assert "Medical documentation is required for this request." in [e.value for e in at.error]
    assert next(b for b in at.button if b.label == "Submit request").disabled


def test_manager_can_reject_only_with_reason_then_approve(seeded):
    at = open_page("pages/manager_approvals.py", "manager")
    before = len([b for b in at.button if b.label == "Approve"])
    assert before > 0
    next(b for b in at.button if b.label == "Reject").click().run()
    assert "A reason is required to reject a request." in [e.value for e in at.error]
    next(b for b in at.button if b.label == "Approve").click().run()
    assert len([b for b in at.button if b.label == "Approve"]) == before - 1


def test_unexpected_errors_are_never_shown_raw(seeded, monkeypatch):
    from services import leave_service
    monkeypatch.setattr(leave_service, "approve_request",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("psycopg2.OperationalError: secret detail")))
    at = open_page("pages/manager_approvals.py", "manager")
    next(b for b in at.button if b.label == "Approve").click().run()
    shown = " ".join(e.value for e in at.error)
    assert "secret detail" not in shown and "psycopg2" not in shown and "Something went wrong" in shown
