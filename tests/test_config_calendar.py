import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from redmine_hours_helper.calendar import WorkCalendar, month_days
from redmine_hours_helper.config import (
    ConfigError,
    Settings,
    load_settings,
    save_settings,
    validate_api_key,
)


class ConfigurationTests(unittest.TestCase):
    def settings(self, **kwargs):
        return Settings.from_dict(
            {
                "redmine_url": "https://redmine.example.com/desk/",
                "issue_id": 123,
                "activity_id": 9,
                **kwargs,
            }
        )

    def test_normalizes_url_and_roundtrips_without_key(self):
        settings = self.settings()
        self.assertEqual(settings.redmine_url, "https://redmine.example.com/desk")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.local.json"
            save_settings(settings, path)
            self.assertEqual(load_settings(path), settings)
            self.assertNotIn("api_key", path.read_text())

    def test_unsafe_urls_are_rejected(self):
        for url in (
            "http://example.com",
            "https://user:pass@example.com",
            "https://example.com?key=x",
            "https://example.com/#token",
            "https://example.com:bad",
            "https://example.com:0",
            "https://exa mple.com",
            "https://example.com\\@evil.example",
        ):
            with self.subTest(url=url), self.assertRaises(ConfigError):
                self.settings(redmine_url=url)

    def test_invalid_configuration(self):
        for values in (
            {"issue_id": 0},
            {"activity_id": True},
            {"daily_hours": "NaN"},
            {"daily_hours": 25},
            {"daily_hours": 0},
            {"daily_hours": "1.001"},
            {"timeout_seconds": float("inf")},
            {"timeout_seconds": True},
            {"comment": "x" * 256},
            {"api_key": "do-not-save-this"},
        ):
            with self.subTest(values=values), self.assertRaises(ConfigError):
                self.settings(**values)

    def test_key_validation(self):
        self.assertEqual(validate_api_key(" example-key "), "example-key")
        for key in ("", "a\nb", "a b", "密碼"):
            with self.subTest(key=key), self.assertRaises(ConfigError):
                validate_api_key(key)

    def test_missing_config_has_actionable_error(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            self.assertRaisesRegex(ConfigError, "config.example.json"),
        ):
            load_settings(Path(folder) / "missing.json")


class CalendarTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "calendar.json"
            path.write_text(json.dumps(data))
            return WorkCalendar.load(path)

    def test_year_specific_holiday_and_weekend_override(self):
        calendar = self.load({"holidays": ["2026-10-30"], "workdays": ["2026-10-31"]})
        self.assertFalse(calendar.is_workday(dt.date(2026, 10, 30)))
        self.assertTrue(calendar.is_workday(dt.date(2026, 10, 31)))
        self.assertTrue(calendar.is_workday(dt.date(2028, 10, 30)))

    def test_default_has_no_public_holidays(self):
        calendar = WorkCalendar.load(None)
        self.assertTrue(calendar.is_workday(dt.date(2026, 1, 1)))
        self.assertFalse(calendar.is_workday(dt.date(2026, 1, 3)))

    def test_malformed_calendar_fails_closed(self):
        for data in (
            {"holidays": ["10-30"]},
            {"holidays": ["2026-02-30"]},
            {"holidays": ["20261030"]},
            {"holidays": ["2026-10-30"], "workdays": ["2026-10-30"]},
            {"holidays": "2026-10-30"},
            {"unknown": []},
            [],
        ):
            with self.subTest(data=data), self.assertRaises(ConfigError):
                self.load(data)

    def test_month_boundaries(self):
        self.assertEqual(len(month_days(2024, 2)), 29)
        self.assertEqual(len(month_days(2025, 2)), 28)
        self.assertEqual(month_days(9999, 12)[-1], dt.date(9999, 12, 31))
        with self.assertRaises(ConfigError):
            month_days(2026, 13)
