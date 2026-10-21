"""Balance updates, notifications and audit trail produced by the workflow."""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from database import models as m
from services import admin_service, audit_service, balance_service, leave_service as ls, notification_service as ns
from tests.conftest import MONDAY, NOW
from workflows.states import RequestStatus as S


def submit(w, lt, start, end, emp=None):
    return ls.submit_leave_request(w.s, w.actor(emp or w.ananya), lt.id, start, end, now=NOW)


def bal(w, lt=None, emp=None):
    w.s.expire_all()
    return w.balance(emp or w.ananya, lt or w.annual)


class TestBalanceUpdates:
    def test_submit_reserves_days(self, world):
        submit(world, world.annual, MONDAY, date(2026, 3, 11))
        b = bal(world)
        assert (b.pending, b.used, b.available) == (3, 0, 15)

    def test_final_approval_moves_pending_to_used(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        assert (bal(world).pending, bal(world).used) == (3, 0)                    # not final yet
        ls.approve_request(world.s, world.actor(world.arjun), req.id, now=NOW)
        b = bal(world)
        assert (b.pending, b.used, b.available) == (0, 3, 15)

    def test_rejection_releases_days(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        ls.reject_request(world.s, world.actor(world.karthik), req.id, "No", now=NOW)
        b = bal(world)
        assert (b.pending, b.used, b.available) == (0, 0, 18)

    def test_cancellation_releases_days(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        ls.cancel_request(world.s, world.actor(world.ananya), req.id, now=NOW)
        assert bal(world).available == 18

    def test_override_cancel_of_approved_request_restores_used_days(self, world):
        req = submit(world, world.casual, MONDAY, date(2026, 3, 10))
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        assert bal(world, world.casual).used == 2
        ls.override_request(world.s, world.actor(world.arjun), req.id, S.CANCELLED, "Project change", now=NOW)
        b = bal(world, world.casual)
        assert (b.used, b.available) == (0, 8)

    def test_override_approve_commits_days(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        ls.override_request(world.s, world.actor(world.arjun), req.id, S.APPROVED, "Urgent", now=NOW)
        b = bal(world)
        assert (b.pending, b.used) == (0, 3)

    def test_untracked_types_never_touch_balances(self, world):
        submit(world, world.wfh, MONDAY, MONDAY)
        req = submit(world, world.unpaid, date(2026, 3, 16), date(2026, 3, 17))
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        assert world.s.scalars(select(m.LeaveBalance).where(m.LeaveBalance.employee_id == world.ananya.id)).all() == []

    def test_carry_forward_respects_leave_type_limit(self, world):
        prev = world.balance(world.ananya, world.annual, 2025)
        prev.used = Decimal("5")                                                  # 13 left, limit is 5
        world.balance(world.ananya, world.casual, 2025).used = Decimal("1")       # casual does not carry
        balance_service.allocate_year(world.s, 2026)
        assert world.balance(world.ananya, world.annual, 2026).carried_forward == 5
        assert world.balance(world.ananya, world.casual, 2026).carried_forward == 0
        assert world.balance(world.ananya, world.annual, 2026).total == 23

    def test_admin_balance_cannot_drop_below_committed_days(self, world):
        submit(world, world.annual, MONDAY, date(2026, 3, 11))                    # 3 pending
        import pytest
        from utils.errors import BusinessRuleError
        with pytest.raises(BusinessRuleError):
            admin_service.update_balance(world.s, world.actor(world.arjun), world.ananya.id, world.annual.id, 2026,
                                         Decimal("2"), Decimal("0"))


class TestNotifications:
    def test_submission_notifies_employee_and_manager(self, world):
        submit(world, world.casual, MONDAY, MONDAY)
        mine = ns.list_for_user(world.s, world.ananya.user.id)
        assert any("submitted to your manager" in n.message for n in mine)
        mgr = ns.list_for_user(world.s, world.karthik.user.id)
        assert [n.category for n in mgr] == [ns.APPROVAL_REQUIRED] and not mgr[0].is_read
        assert ns.unread_count(world.s, world.karthik.user.id) == 1

    def test_hr_is_notified_when_their_stage_activates(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        assert ns.list_for_user(world.s, world.arjun.user.id) == []
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        for hr in (world.arjun, world.priya):
            assert ns.list_for_user(world.s, hr.user.id)[0].title == "HR approval required"

    def test_final_approval_notifies_employee_with_balance_update(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        cats = [n.category for n in ns.list_for_user(world.s, world.ananya.user.id)]
        assert ns.APPROVED in cats and ns.BALANCE_UPDATED in cats

    def test_rejection_notification_contains_reason(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.reject_request(world.s, world.actor(world.karthik), req.id, "Release freeze", now=NOW)
        n = ns.list_for_user(world.s, world.ananya.user.id)[0]
        assert n.category == ns.REJECTED and "Release freeze" in n.message

    def test_cancellation_notifies_pending_approver(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.cancel_request(world.s, world.actor(world.ananya), req.id, now=NOW)
        assert ns.CANCELLED in [n.category for n in ns.list_for_user(world.s, world.karthik.user.id)]

    def test_mark_read_is_scoped_to_owner(self, world):
        submit(world, world.casual, MONDAY, MONDAY)
        n = ns.list_for_user(world.s, world.karthik.user.id)[0]
        ns.mark_read(world.s, world.ananya.user.id, n.id)                         # wrong user: no effect
        assert ns.unread_count(world.s, world.karthik.user.id) == 1
        ns.mark_all_read(world.s, world.karthik.user.id)
        assert ns.unread_count(world.s, world.karthik.user.id) == 0


class TestAuditTrail:
    def actions(self, w):
        return [a.action for a in audit_service.recent(w.s)]

    def test_submission_and_decisions_are_audited_with_old_and_new_values(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.reject_request(world.s, world.actor(world.karthik), req.id, "Busy", now=NOW)
        rec = next(a for a in audit_service.recent(world.s) if a.action == "REQUEST_REJECTED")
        assert rec.user_id == world.karthik.user.id and rec.entity_type == "LeaveRequest"
        assert rec.entity_id == str(req.id)
        assert rec.old_value["status"] == "MANAGER_PENDING" and rec.new_value["status"] == "REJECTED"
        assert "LEAVE_SUBMITTED" in self.actions(world)

    def test_override_cancel_and_balance_updates_are_audited(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        ls.override_request(world.s, world.actor(world.arjun), req.id, S.CANCELLED, "Reorg", now=NOW)
        acts = self.actions(world)
        assert {"REQUEST_APPROVED", "ADMIN_OVERRIDE", "BALANCE_UPDATED"} <= set(acts)

    def test_master_data_changes_are_audited(self, world):
        actor = world.actor(world.arjun)
        h = admin_service.save_holiday(world.s, actor, date(2026, 4, 1), "Founders Day")
        admin_service.save_holiday(world.s, actor, date(2026, 4, 2), "Founders Day", holiday_id=h.id)
        admin_service.save_leave_type(world.s, actor, {"annual_allowance": 12}, world.casual.id)
        entries = {a.action: a for a in audit_service.recent(world.s)}
        assert entries["HOLIDAY_UPDATED"].old_value["holiday_date"] == "2026-04-01"
        assert float(entries["LEAVE_TYPE_UPDATED"].new_value["annual_allowance"]) == 12
        assert float(entries["LEAVE_TYPE_UPDATED"].old_value["annual_allowance"]) == 8
