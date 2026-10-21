"""Pure unit tests – no database needed."""
from datetime import date

import pytest

from utils.dates import count_working_days, ranges_overlap
from utils.errors import WorkflowError
from workflows.states import (
    ApprovalRuleSpec, RequestStatus as S, Stage, assert_transition, can_transition,
    is_cancellable_by_employee, parse_stages, select_stages,
)

RULES = [ApprovalRuleSpec(0, (Stage.MANAGER,)), ApprovalRuleSpec(2, (Stage.MANAGER, Stage.HR)),
         ApprovalRuleSpec(7, (Stage.MANAGER, Stage.HR, Stage.DEPARTMENT_HEAD))]


class TestWorkingDays:
    def test_full_week_excludes_weekend(self):
        assert count_working_days(date(2026, 3, 2), date(2026, 3, 8)) == 5      # Mon..Sun

    def test_range_spanning_two_weekends(self):
        assert count_working_days(date(2026, 3, 6), date(2026, 3, 16)) == 7     # Fri..Mon+1w

    def test_weekend_only_range_is_zero(self):
        assert count_working_days(date(2026, 3, 7), date(2026, 3, 8)) == 0

    def test_holiday_is_excluded(self):
        assert count_working_days(date(2026, 3, 2), date(2026, 3, 6), holidays={date(2026, 3, 4)}) == 4

    def test_holiday_on_weekend_not_double_counted(self):
        assert count_working_days(date(2026, 3, 2), date(2026, 3, 8), holidays={date(2026, 3, 7)}) == 5

    def test_custom_weekend_configuration(self):
        assert count_working_days(date(2026, 3, 2), date(2026, 3, 8), weekend_days=(4, 5)) == 5   # Fri/Sat off

    def test_single_working_day_and_inverted_range(self):
        assert count_working_days(date(2026, 3, 3), date(2026, 3, 3)) == 1
        assert count_working_days(date(2026, 3, 5), date(2026, 3, 3)) == 0

    def test_overlap_boundaries(self):
        assert ranges_overlap(date(2026, 3, 2), date(2026, 3, 4), date(2026, 3, 4), date(2026, 3, 6))
        assert not ranges_overlap(date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 6))


class TestApprovalRuleSelection:
    @pytest.mark.parametrize("days,expected", [
        (1, (Stage.MANAGER,)), (2, (Stage.MANAGER,)),
        (3, (Stage.MANAGER, Stage.HR)), (7, (Stage.MANAGER, Stage.HR)),
        (8, (Stage.MANAGER, Stage.HR, Stage.DEPARTMENT_HEAD)), (30, (Stage.MANAGER, Stage.HR, Stage.DEPARTMENT_HEAD)),
    ])
    def test_thresholds(self, days, expected):
        assert select_stages(days, RULES) == expected

    def test_thresholds_are_data_driven(self):
        custom = [ApprovalRuleSpec(0, (Stage.MANAGER,)), ApprovalRuleSpec(1, (Stage.MANAGER, Stage.HR))]
        assert select_stages(2, custom) == (Stage.MANAGER, Stage.HR)

    def test_stages_always_in_canonical_order(self):
        assert parse_stages("HR,MANAGER") == (Stage.MANAGER, Stage.HR)

    def test_no_rules_is_an_error(self):
        with pytest.raises(WorkflowError):
            select_stages(3, [])


class TestTransitions:
    def test_happy_path(self):
        for a, b in [(S.DRAFT, S.SUBMITTED), (S.SUBMITTED, S.MANAGER_PENDING), (S.MANAGER_PENDING, S.HR_PENDING),
                     (S.HR_PENDING, S.DEPARTMENT_HEAD_PENDING), (S.DEPARTMENT_HEAD_PENDING, S.APPROVED)]:
            assert can_transition(a, b)

    @pytest.mark.parametrize("final", [S.REJECTED, S.CANCELLED])
    def test_terminal_states_are_terminal(self, final):
        for target in S:
            assert not can_transition(final, target)

    def test_cannot_skip_backwards_or_reapprove(self):
        assert not can_transition(S.HR_PENDING, S.MANAGER_PENDING)
        assert not can_transition(S.APPROVED, S.REJECTED)
        with pytest.raises(WorkflowError):
            assert_transition(S.APPROVED, S.MANAGER_PENDING)

    def test_employee_can_only_cancel_open_requests(self):
        assert is_cancellable_by_employee(S.MANAGER_PENDING)
        assert not is_cancellable_by_employee(S.APPROVED)
        assert not is_cancellable_by_employee(S.REJECTED)
