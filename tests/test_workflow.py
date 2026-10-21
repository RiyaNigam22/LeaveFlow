"""Approval workflow: chain construction, transitions, permissions, cancellation and overrides."""
from datetime import date

import pytest

from database.models import ApprovalStep
from services import leave_service as ls
from tests.conftest import MONDAY, NOW
from utils.errors import BusinessRuleError, PermissionDenied, WorkflowError
from workflows import engine
from workflows.states import RequestStatus as S


def submit(w, lt, start, end, emp=None):
    return ls.submit_leave_request(w.s, w.actor(emp or w.ananya), lt.id, start, end, now=NOW)


def stages(req):
    return [(s.stage, s.status) for s in req.steps]


class TestChainConstruction:
    def test_short_leave_needs_manager_only(self, world):
        req = submit(world, world.casual, MONDAY, date(2026, 3, 10))              # 2 days
        assert req.status == S.MANAGER_PENDING and stages(req) == [("MANAGER", "PENDING")]
        assert req.steps[0].approver_employee_id == world.karthik.id

    def test_three_to_seven_days_need_manager_and_hr(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))              # 3 days
        assert stages(req) == [("MANAGER", "PENDING"), ("HR", "WAITING")]
        assert req.steps[1].approver_employee_id is None                          # any HR user

    def test_over_seven_days_adds_department_head(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 18))              # 8 days
        assert [s.stage for s in req.steps] == ["MANAGER", "HR", "DEPARTMENT_HEAD"]
        assert req.steps[2].approver_employee_id == world.vikram.id

    def test_department_head_step_skipped_when_same_as_manager(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 18), emp=world.karthik)   # manager == dept head
        assert req.steps[0].approver_employee_id == world.vikram.id
        assert req.steps[2].status == "SKIPPED"

    def test_manager_stage_falls_back_to_hr_when_no_manager(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY, emp=world.vikram)
        assert req.steps[0].approver_employee_id is None

    def test_no_approval_leave_type_is_auto_approved(self, world):
        req = submit(world, world.wfh, MONDAY, MONDAY)
        assert req.status == S.APPROVED and req.steps == []


class TestTransitions:
    def test_full_three_stage_approval(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 18))
        t = ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        assert (t.old_status, t.new_status) == (S.MANAGER_PENDING, S.HR_PENDING)
        t = ls.approve_request(world.s, world.actor(world.arjun), req.id, now=NOW)
        assert t.new_status == S.DEPARTMENT_HEAD_PENDING
        t = ls.approve_request(world.s, world.actor(world.vikram), req.id, "Enjoy", now=NOW)
        assert t.new_status == S.APPROVED and t.is_final
        assert req.decided_at is not None and all(s.status == "APPROVED" for s in req.steps)

    def test_step_timestamps_recorded(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        m, h = req.steps
        assert m.activated_at == NOW and m.decided_at == NOW and h.activated_at == NOW

    def test_rejection_cancels_remaining_steps(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        ls.reject_request(world.s, world.actor(world.karthik), req.id, "Deadline", now=NOW)
        assert req.status == S.REJECTED and req.decision_reason == "Deadline"
        assert stages(req) == [("MANAGER", "REJECTED"), ("HR", "CANCELLED")]

    @pytest.mark.parametrize("reason", ["", "   ", None])
    def test_rejection_requires_a_reason(self, world, reason):
        req = submit(world, world.casual, MONDAY, MONDAY)
        with pytest.raises(BusinessRuleError, match="reason is required"):
            ls.reject_request(world.s, world.actor(world.karthik), req.id, reason, now=NOW)
        assert req.status == S.MANAGER_PENDING

    def test_finalised_request_cannot_be_decided_again(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        with pytest.raises(PermissionDenied):
            ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)


class TestPermissions:
    def test_only_assigned_manager_can_approve(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        for outsider in (world.vikram, world.ravi, world.ananya):
            with pytest.raises(PermissionDenied):
                ls.approve_request(world.s, world.actor(outsider), req.id, now=NOW)

    def test_hr_cannot_skip_ahead_of_manager_stage(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        with pytest.raises(PermissionDenied):
            ls.approve_request(world.s, world.actor(world.arjun), req.id, now=NOW)

    def test_nobody_approves_their_own_request(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY, emp=world.arjun)       # HR user, HR fallback
        with pytest.raises(PermissionDenied):
            ls.approve_request(world.s, world.actor(world.arjun), req.id, now=NOW)
        ls.approve_request(world.s, world.actor(world.priya), req.id, now=NOW)   # another HR can

    def test_approval_queue_is_scoped_to_actor(self, world):
        submit(world, world.casual, MONDAY, MONDAY)
        submit(world, world.annual, date(2026, 3, 16), date(2026, 3, 20), emp=world.ravi)
        assert len(engine.queue_for_actor(world.s, world.actor(world.karthik))) == 2
        assert engine.queue_for_actor(world.s, world.actor(world.vikram)) == []
        assert engine.queue_for_actor(world.s, world.actor(world.arjun)) == []   # nothing at HR stage yet
        ls.approve_request(world.s, world.actor(world.karthik), world.s.query(ApprovalStep).first().request_id, now=NOW)

    def test_hr_queue_shows_hr_stage_only_after_manager_approval(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 11))
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        assert [s.request_id for s in engine.queue_for_actor(world.s, world.actor(world.arjun))] == [req.id]


class TestCancellationAndOverride:
    def test_employee_cancels_own_pending_request(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.cancel_request(world.s, world.actor(world.ananya), req.id, now=NOW)
        assert req.status == S.CANCELLED and req.steps[0].status == "CANCELLED"

    def test_cannot_cancel_someone_elses_request(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        with pytest.raises(PermissionDenied):
            ls.cancel_request(world.s, world.actor(world.ravi), req.id, now=NOW)

    def test_cannot_cancel_approved_request(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        with pytest.raises(BusinessRuleError, match="Only pending"):
            ls.cancel_request(world.s, world.actor(world.ananya), req.id, now=NOW)

    def test_hr_override_approves_pending_request(self, world):
        req = submit(world, world.annual, MONDAY, date(2026, 3, 18))
        ls.override_request(world.s, world.actor(world.arjun), req.id, S.APPROVED, "Business critical", now=NOW)
        assert req.status == S.APPROVED and all(s.status == "SKIPPED" for s in req.steps)

    def test_override_requires_hr_reason_and_not_self(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        with pytest.raises(PermissionDenied):
            ls.override_request(world.s, world.actor(world.karthik), req.id, S.APPROVED, "x", now=NOW)
        with pytest.raises(BusinessRuleError):
            ls.override_request(world.s, world.actor(world.arjun), req.id, S.APPROVED, " ", now=NOW)
        own = submit(world, world.casual, date(2026, 3, 16), date(2026, 3, 16), emp=world.arjun)
        with pytest.raises(PermissionDenied):
            ls.override_request(world.s, world.actor(world.arjun), own.id, S.APPROVED, "self", now=NOW)

    def test_rejected_request_cannot_be_overridden(self, world):
        req = submit(world, world.casual, MONDAY, MONDAY)
        ls.reject_request(world.s, world.actor(world.karthik), req.id, "No", now=NOW)
        with pytest.raises(WorkflowError):
            ls.override_request(world.s, world.actor(world.arjun), req.id, S.APPROVED, "Reverse", now=NOW)
