"""Authentication, lockout and administration safeguards."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

import config
from auth.security import hash_password, validate_password_strength, verify_password
from auth.service import authenticate
from database import models as m
from services import admin_service as admin
from tests.conftest import NOW
from utils.errors import AuthenticationError, BusinessRuleError


class TestPasswords:
    def test_hash_is_not_plaintext_and_verifies(self):
        h = hash_password("Secret123")
        assert "Secret123" not in h and h.startswith("$2") and verify_password("Secret123", h)
        assert not verify_password("secret123", h) and not verify_password("x", "not-a-hash")

    def test_same_password_gets_different_salts(self):
        assert hash_password("Secret123") != hash_password("Secret123")

    @pytest.mark.parametrize("bad", ["short1", "alllettersonly", "12345678"])
    def test_weak_passwords_rejected(self, bad):
        with pytest.raises(BusinessRuleError):
            validate_password_strength(bad)


class TestLogin:
    def test_successful_login_audited_and_role_loaded(self, world):
        user = authenticate(world.s, " Ananya ", "Passw0rd!", now=NOW)         # username is trimmed / case-insensitive
        assert user.role.name == config.ROLE_EMPLOYEE and user.last_login_at == NOW
        assert world.s.scalars(select(m.AuditLog).where(m.AuditLog.action == "LOGIN")).first().user_id == user.id

    def test_wrong_password_and_unknown_user_share_one_message(self, world):
        with pytest.raises(AuthenticationError) as a:
            authenticate(world.s, "ananya", "wrong", now=NOW)
        with pytest.raises(AuthenticationError) as b:
            authenticate(world.s, "nobody", "wrong", now=NOW)
        assert str(a.value) == str(b.value) == "Invalid username or password."

    def test_account_locks_after_repeated_failures_even_for_correct_password(self, world):
        for _ in range(config.MAX_LOGIN_ATTEMPTS):
            with pytest.raises(AuthenticationError):
                authenticate(world.s, "ananya", "wrong", now=NOW)
        with pytest.raises(AuthenticationError, match="temporarily locked"):
            authenticate(world.s, "ananya", "Passw0rd!", now=NOW)
        assert authenticate(world.s, "ananya", "Passw0rd!", now=NOW + timedelta(minutes=config.LOCKOUT_MINUTES + 1))

    def test_deactivated_user_cannot_login(self, world):
        world.ananya.user.is_active = False
        world.s.flush()
        with pytest.raises(AuthenticationError):
            authenticate(world.s, "ananya", "Passw0rd!", now=NOW)


class TestAdminSafeguards:
    def hr(self, w):
        return w.actor(w.arjun)

    def new_employee(self, w, **over):
        data = dict(first_name="New", last_name="Hire", email="new.hire@t.example", department_id=w.dept.id,
                    manager_id=w.karthik.id, hire_date=date(2026, 1, 5), job_title="Engineer")
        data.update(over)
        return admin.create_employee(w.s, self.hr(w), data, "new.hire", "Welcome123", config.ROLE_EMPLOYEE)

    def test_create_employee_creates_user_balances_and_audit(self, world):
        emp = self.new_employee(world)
        assert emp.user.username == "new.hire" and emp.user.password_hash != "Welcome123"
        assert emp.employee_code.startswith("EMP")
        assert world.s.scalars(select(m.AuditLog).where(m.AuditLog.action == "EMPLOYEE_CREATED")).first()
        assert world.s.scalars(select(m.LeaveBalance).where(m.LeaveBalance.employee_id == emp.id)).all()

    def test_duplicate_email_gives_friendly_error(self, world):
        self.new_employee(world)
        with pytest.raises(BusinessRuleError, match="already exists"):
            admin.create_employee(world.s, self.hr(world), dict(
                first_name="X", last_name="Y", email="new.hire@t.example", department_id=world.dept.id,
                hire_date=date(2026, 1, 5)), "other.user", "Welcome123", config.ROLE_EMPLOYEE)

    def test_manager_must_have_manager_or_hr_role(self, world):
        with pytest.raises(BusinessRuleError, match="Manager or HR"):
            self.new_employee(world, manager_id=world.ravi.id)

    def test_circular_reporting_line_rejected(self, world):
        with pytest.raises(BusinessRuleError, match="circular"):
            admin.update_employee(world.s, self.hr(world), world.vikram.id, {"manager_id": world.karthik.id})

    def test_cannot_demote_a_manager_with_reports(self, world):
        with pytest.raises(BusinessRuleError, match="reassign"):
            admin.update_employee(world.s, self.hr(world), world.karthik.id, {}, role=config.ROLE_EMPLOYEE)

    def test_cannot_deactivate_self_or_approver_with_pending_work(self, world):
        with pytest.raises(BusinessRuleError, match="own account"):
            admin.update_employee(world.s, self.hr(world), world.arjun.id, {"is_active": False})
        with pytest.raises(BusinessRuleError):
            admin.update_employee(world.s, self.hr(world), world.karthik.id, {"is_active": False})

    def test_duplicate_holiday_gives_friendly_error_without_db_details(self, world):
        with pytest.raises(BusinessRuleError) as exc:
            admin.save_holiday(world.s, self.hr(world), date(2026, 3, 4), "Duplicate")
        assert str(exc.value) == "A holiday already exists on this date."
        assert "psycopg2" not in str(exc.value) and "duplicate key" not in str(exc.value)

    def test_approval_policy_is_editable_and_drives_validation(self, world):
        admin.save_approval_rule(world.s, self.hr(world), 1, ["HR", "MANAGER"])
        from services.rules_service import load_policy
        from workflows.states import Stage, select_stages
        assert select_stages(2, load_policy(world.s).rules) == (Stage.MANAGER, Stage.HR)
        with pytest.raises(BusinessRuleError, match="base rule"):
            admin.delete_approval_rule(world.s, self.hr(world), world.s.scalars(
                select(m.ApprovalRule).where(m.ApprovalRule.min_days == 0)).first().id)

    def test_settings_validation(self, world):
        admin.save_setting(world.s, self.hr(world), "WEEKEND_DAYS", "4, 5")
        assert world.s.get(m.SystemSetting, "WEEKEND_DAYS").value == "4,5"
        for key, bad in [("WEEKEND_DAYS", "9"), ("SLA_HOURS_PER_STAGE", "0"), ("MAX_BACKDATE_DAYS", "abc")]:
            with pytest.raises(BusinessRuleError):
                admin.save_setting(world.s, self.hr(world), key, bad)
