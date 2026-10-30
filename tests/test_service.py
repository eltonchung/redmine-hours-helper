import datetime as dt
import unittest
from dataclasses import replace
from decimal import Decimal
from threading import Event
from unittest.mock import Mock

from redmine_hours_helper.calendar import WorkCalendar
from redmine_hours_helper.config import Settings
from redmine_hours_helper.redmine import RedmineError, WriteUncertainError
from redmine_hours_helper.service import HoursService, Status, gap


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings.from_dict(
            {"redmine_url": "https://redmine.example.com", "issue_id": 123, "activity_id": 9}
        )
        self.client = Mock()
        self.client.current_user_id.return_value = 42
        self.client.hours_for_day.return_value = Decimal("5.5")
        self.client.create_entry.return_value = 88
        self.service = HoursService(
            self.client, self.settings, WorkCalendar(), today=dt.date(2026, 10, 2)
        )

    def test_preview_excludes_weekends_and_future_without_writes(self):
        plan = self.service.preview(2026, 10)
        self.assertEqual(plan.planned_hours, 5)
        self.assertEqual(self.client.hours_for_day.call_count, 2)
        self.client.create_entry.assert_not_called()
        self.assertTrue(plan.can_apply)
        self.assertEqual(len(plan.rows), 31)

    def test_explicit_future_opt_in(self):
        plan = self.service.preview(2026, 10, include_future=True)
        self.assertEqual(sum(row.status == Status.READY for row in plan.rows), 22)

    def test_query_failure_blocks_all_writes(self):
        self.client.hours_for_day.side_effect = [RedmineError("Unavailable"), Decimal("0")]
        plan = self.service.preview(2026, 10)
        self.assertEqual(plan.rows[0].status, Status.ERROR)
        self.assertFalse(plan.can_apply)
        with self.assertRaises(RedmineError):
            self.service.apply(plan)
        self.client.create_entry.assert_not_called()

    def test_apply_rechecks_and_reduces_gap(self):
        plan = self.service.preview(2026, 10)
        self.client.hours_for_day.side_effect = [Decimal("7"), Decimal("8")]
        rows = self.service.apply(plan)
        self.assertEqual(sum(row.added for row in rows), 1)
        self.client.create_entry.assert_called_once_with(dt.date(2026, 10, 1), Decimal("1.00"))
        self.assertEqual(rows[1].status, Status.COVERED)

    def test_gap_increase_stops_before_unapproved_write(self):
        plan = self.service.preview(2026, 10)
        self.client.hours_for_day.return_value = Decimal("0")
        rows = self.service.apply(plan)
        self.assertEqual(rows[0].status, Status.CHANGED)
        self.assertEqual(rows[1].status, Status.NOT_RUN)
        self.client.create_entry.assert_not_called()

    def test_failed_or_uncertain_write_is_not_counted(self):
        for exception, status in (
            (RedmineError("Rejected"), Status.ERROR),
            (WriteUncertainError("Unknown"), Status.UNCERTAIN),
        ):
            with self.subTest(status=status):
                self.client.create_entry.reset_mock()
                self.client.create_entry.side_effect = [88, exception]
                plan = self.service.preview(2026, 10)
                rows = self.service.apply(plan)
                self.assertEqual(sum(row.added for row in rows), Decimal("2.5"))
                self.assertEqual(rows[1].status, status)

    def test_first_write_failure_stops_remaining_dates(self):
        plan = self.service.preview(2026, 10)
        self.client.create_entry.side_effect = WriteUncertainError("Unknown")
        rows = self.service.apply(plan)
        self.assertEqual(rows[1].status, Status.NOT_RUN)
        self.assertEqual(self.client.create_entry.call_count, 1)

    def test_recheck_failure_never_writes(self):
        plan = self.service.preview(2026, 10)
        self.client.hours_for_day.side_effect = RedmineError("Unavailable")
        rows = self.service.apply(plan)
        self.assertEqual(rows[0].status, Status.ERROR)
        self.client.create_entry.assert_not_called()

    def test_user_or_settings_change_requires_new_preview(self):
        plan = self.service.preview(2026, 10)
        self.client.current_user_id.return_value = 99
        with self.assertRaises(RedmineError):
            self.service.apply(plan)
        self.client.current_user_id.return_value = 42
        with self.assertRaises(RedmineError):
            self.service.apply(replace(plan, settings=replace(self.settings, issue_id=999)))

    def test_cancelled_preview_cannot_apply(self):
        cancel = Event()
        cancel.set()
        plan = self.service.preview(2026, 10, cancel=cancel)
        self.assertFalse(plan.complete)
        self.assertFalse(plan.can_apply)

    def test_cancel_apply_preserves_confirmed_results(self):
        plan = self.service.preview(2026, 10)
        cancel = Event()
        rows = self.service.apply(plan, progress=lambda *_: cancel.set(), cancel=cancel)
        self.assertEqual(rows[0].status, Status.ADDED)
        self.assertEqual(rows[1].status, Status.NOT_RUN)
        self.assertEqual(sum(row.added for row in rows), Decimal("2.5"))

    def test_fractional_gap_never_exceeds_target(self):
        self.assertEqual(gap(Decimal("8"), Decimal("7.995")), 0)
        self.assertEqual(gap(Decimal("8"), Decimal("6.333")), Decimal("1.66"))
        self.assertEqual(gap(Decimal("8"), Decimal("9")), 0)
