"""Validation engine: balance, overlap, holidays, documents, date validity."""
from datetime import date
from decimal import Decimal

import pytest

from services import leave_service, rules_service
from services.rules_service import find_overlap, has_sufficient_balance
from tests.conftest import MONDAY, NOW
from utils.errors import BusinessRuleError

TODAY = date(2026, 3, 2)


def validate(w, lt, start, end, doc=False, emp=None, **kw):
    return rules_service.validate_leave_request(w.s, emp or w.ananya, lt, start, end, doc, today=TODAY, **kw)


def submit(w, lt, start, end, emp=None, **kw):
    return leave_service.submit_leave_request(w.s, w.actor(emp or w.ananya), lt.id, start, end, now=NOW, **kw)


class TestBalance:
    def test_pure_balance_check(self):
        assert has_sufficient_balance(3, Decimal("3.0"))
        assert not has_sufficient_balance(4, Decimal("3.0"))

    def test_insufficient_balance_rejected(self, world):
        world.balance(world.ananya, world.annual).allocated = Decimal("2")
        r = validate(world, world.annual, MONDAY, date(2026, 3, 11))             # 3 working days
        assert "Insufficient leave balance." in r.errors
        assert r.available_balance == Decimal("2")

    def test_exact_balance_is_allowed(self, world):
        world.balance(world.ananya, world.annual).allocated = Decimal("3")
        assert validate(world, world.annual, MONDAY, date(2026, 3, 11)).valid

    def test_pending_requests_reduce_available_balance(self, world):
        world.balance(world.ananya, world.annual).allocated = Decimal("5")
        submit(world, world.annual, MONDAY, date(2026, 3, 11))                   # reserves 3
        r = validate(world, world.annual, date(2026, 3, 16), date(2026, 3, 18))  # needs 3, only 2 left
        assert "Insufficient leave balance." in r.errors

    def test_untracked_leave_type_ignores_balance(self, world):
        r = validate(world, world.unpaid, MONDAY, date(2026, 3, 27))
        assert r.valid and r.available_balance is None


class TestOverlap:
    def test_pure_overlap_detection(self):
        existing = [(date(2026, 3, 10), date(2026, 3, 12), "APPROVED")]
        assert find_overlap(date(2026, 3, 12), date(2026, 3, 13), existing)
        assert find_overlap(date(2026, 3, 11), date(2026, 3, 11), existing)
        assert not find_overlap(date(2026, 3, 13), date(2026, 3, 14), existing)

    def test_pending_request_blocks_overlap(self, world):
        submit(world, world.casual, MONDAY, date(2026, 3, 10))
        r = validate(world, world.casual, date(2026, 3, 10), date(2026, 3, 11))
        assert "An overlapping leave request already exists." in r.errors

    def test_approved_request_blocks_overlap(self, world):
        req = submit(world, world.casual, MONDAY, date(2026, 3, 10))
        leave_service.approve_request(world.s, world.actor(world.karthik), req.id, now=NOW)
        assert not validate(world, world.casual, MONDAY, MONDAY).valid

    def test_rejected_and_cancelled_do_not_block(self, world):
        a = submit(world, world.casual, MONDAY, MONDAY)
        leave_service.reject_request(world.s, world.actor(world.karthik), a.id, "No cover", now=NOW)
        b = submit(world, world.casual, MONDAY, MONDAY)
        leave_service.cancel_request(world.s, world.actor(world.ananya), b.id, now=NOW)
        assert validate(world, world.casual, MONDAY, MONDAY).valid

    def test_adjacent_ranges_and_other_employees_are_fine(self, world):
        submit(world, world.casual, MONDAY, date(2026, 3, 10))
        assert validate(world, world.casual, date(2026, 3, 11), date(2026, 3, 11)).valid
        assert validate(world, world.casual, MONDAY, date(2026, 3, 10), emp=world.ravi).valid


class TestWorkingDaysAndHolidays:
    def test_weekends_and_holidays_excluded_from_duration(self, world):
        # Mon 2 Mar – Sun 8 Mar contains the Wed 4 Mar holiday and the weekend (5,6 Mar are Fri/Sat? no: 7,8)
        r = validate(world, world.annual, date(2026, 3, 2), date(2026, 3, 8))
        assert r.working_days == 4 and r.excluded_holidays == 1 and r.excluded_weekend_days == 2

    def test_request_on_holiday_only_has_no_working_days(self, world):
        r = validate(world, world.casual, date(2026, 3, 4), date(2026, 3, 4))
        assert not r.valid and "no working days" in r.errors[0]

    def test_inactive_holiday_counts_as_working_day(self, world):
        from database.models import Holiday
        h = world.s.query(Holiday).one(); h.is_active = False; world.s.flush()
        assert validate(world, world.annual, date(2026, 3, 2), date(2026, 3, 6)).working_days == 5

    def test_stored_working_days_exclude_weekend(self, world):
        req = submit(world, world.annual, date(2026, 3, 6), date(2026, 3, 10))   # Fri..Tue
        assert req.working_days == 3


class TestDocuments:
    def test_sick_leave_over_threshold_needs_document(self, world):
        r = validate(world, world.sick, MONDAY, date(2026, 3, 11))                # 3 days > 2
        assert "Medical documentation is required for this request." in r.errors and r.needs_document

    def test_sick_leave_at_threshold_needs_no_document(self, world):
        assert validate(world, world.sick, MONDAY, date(2026, 3, 10)).valid

    def test_document_satisfies_requirement(self, world):
        assert validate(world, world.sick, MONDAY, date(2026, 3, 11), doc=True).valid

    def test_submit_stores_document(self, world):
        req = submit(world, world.sick, MONDAY, date(2026, 3, 11), document=("cert.pdf", b"data"))
        assert req.document_name == "cert.pdf" and req.document_content == b"data"


class TestDateValidity:
    def test_end_before_start(self, world):
        assert not validate(world, world.casual, date(2026, 3, 10), date(2026, 3, 9)).valid

    def test_too_far_in_past(self, world):
        r = validate(world, world.casual, date(2026, 2, 16), date(2026, 2, 16))
        assert any("in the past" in e for e in r.errors)

    def test_cannot_span_calendar_years(self, world):
        r = validate(world, world.casual, date(2026, 12, 30), date(2027, 1, 2))
        assert any("two calendar years" in e for e in r.errors)

    def test_max_consecutive_days(self, world):
        r = validate(world, world.casual, MONDAY, date(2026, 3, 16))             # 6 working days > 5
        assert any("limited to 5" in e for e in r.errors)

    def test_missing_dates(self, world):
        assert not validate(world, world.casual, None, None).valid

    def test_all_errors_are_reported_together(self, world):
        world.balance(world.ananya, world.sick).allocated = Decimal("1")
        r = validate(world, world.sick, MONDAY, date(2026, 3, 11))
        assert len(r.errors) == 2

    def test_submit_raises_user_friendly_error(self, world):
        with pytest.raises(BusinessRuleError, match="Medical documentation is required"):
            submit(world, world.sick, MONDAY, date(2026, 3, 11))
