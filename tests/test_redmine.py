import datetime as dt
import json
import unittest
from decimal import Decimal
from unittest.mock import Mock

import requests

from redmine_hours_helper.config import Settings
from redmine_hours_helper.redmine import RedmineClient, RedmineError, WriteUncertainError

DAY = dt.date(2026, 10, 1)


def response(body=None, status=200, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = (
        json.dumps(body).encode() if body is not None else b"<html>Unexpected login</html>"
    )
    result.headers.update(headers or {})
    return result


def entry(identifier=1, hours=2, **overrides):
    return {
        "id": identifier,
        "hours": hours,
        "spent_on": DAY.isoformat(),
        "user": {"id": 42},
        "issue": {"id": 123},
        "activity": {"id": 9},
        **overrides,
    }


class RedmineTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings.from_dict(
            {"redmine_url": "https://redmine.example.com/desk", "issue_id": 123, "activity_id": 9}
        )
        self.session = Mock()
        self.client = RedmineClient(self.settings, "test-api-key", self.session)

    def replies(self, *items):
        self.session.request.side_effect = [response({"user": {"id": 42}}), *items]

    def test_pagination_counts_every_entry_and_scopes_to_user(self):
        self.replies(
            response({"time_entries": [entry(1, 1.25)], "total_count": 2, "offset": 0}),
            response({"time_entries": [entry(2, 2.5)], "total_count": 2, "offset": 1}),
        )
        self.assertEqual(self.client.hours_for_day(DAY), Decimal("3.75"))
        calls = self.session.request.call_args_list
        self.assertEqual(
            calls[2].kwargs["params"],
            {"user_id": 42, "spent_on": "2026-10-01", "offset": 1, "limit": 100},
        )
        self.assertFalse(calls[1].kwargs["allow_redirects"])
        self.assertEqual(calls[1].kwargs["timeout"], (5, 20))

    def test_empty_day_is_zero(self):
        self.replies(response({"time_entries": [], "total_count": 0, "offset": 0}))
        self.assertEqual(self.client.hours_for_day(DAY), 0)

    def test_failure_is_never_zero(self):
        for result in (response(status=403), response(), requests.Timeout("secret-url")):
            with self.subTest(result=type(result).__name__):
                self.client._user_id = 42
                self.session.request.side_effect = [result]
                with self.assertRaises(RedmineError) as caught:
                    self.client.hours_for_day(DAY)
                self.assertNotIn("secret-url", str(caught.exception))

    def test_invalid_entries_and_metadata_fail_closed(self):
        for body in (
            {"time_entries": [entry(user={"id": 99})], "total_count": 1, "offset": 0},
            {"time_entries": [entry(spent_on="2026-10-02")], "total_count": 1, "offset": 0},
            {"time_entries": [entry(hours="NaN")], "total_count": 1, "offset": 0},
            {"time_entries": [entry(hours=-1)], "total_count": 1, "offset": 0},
            {"time_entries": [], "total_count": 1, "offset": 0},
            {"time_entries": [], "total_count": 0, "offset": 1},
            {"time_entries": [entry()]},
        ):
            with self.subTest(body=body):
                self.client._user_id = 42
                self.session.request.side_effect = [response(body)]
                with self.assertRaises(RedmineError):
                    self.client.hours_for_day(DAY)

    def test_repeated_pages_are_rejected(self):
        self.replies(
            response({"time_entries": [entry()], "total_count": 2, "offset": 0}),
            response({"time_entries": [entry()], "total_count": 2, "offset": 1}),
        )
        with self.assertRaises(RedmineError):
            self.client.hours_for_day(DAY)

    def test_count_changing_mid_read_is_rejected(self):
        self.replies(
            response({"time_entries": [entry()], "total_count": 2, "offset": 0}),
            response({"time_entries": [entry(2)], "total_count": 3, "offset": 1}),
        )
        with self.assertRaises(RedmineError):
            self.client.hours_for_day(DAY)

    def test_valid_same_origin_read_redirect_preserves_filter(self):
        self.replies(
            response(status=302, headers={"Location": "/new/time_entries.json"}),
            response({"time_entries": [], "total_count": 0, "offset": 0}),
        )
        self.assertEqual(self.client.hours_for_day(DAY), 0)
        self.assertEqual(
            self.session.request.call_args.args[1],
            "https://redmine.example.com/new/time_entries.json",
        )
        self.assertEqual(self.session.request.call_args.kwargs["params"]["spent_on"], "2026-10-01")

    def test_unsafe_read_redirect_does_not_forward_key(self):
        for location in (
            "https://other.example.com/time_entries.json",
            "http://redmine.example.com/time_entries.json",
            "https://redmine.example.com:444/time_entries.json",
            "/time_entries.json?user_id=99",
            "//user@redmine.example.com/x",
        ):
            with self.subTest(location=location):
                self.session.reset_mock()
                self.client._user_id = 42
                self.session.request.side_effect = [
                    response(status=302, headers={"Location": location})
                ]
                with self.assertRaises(RedmineError):
                    self.client.hours_for_day(DAY)
                self.assertEqual(self.session.request.call_count, 1)

    def test_verified_created_entry(self):
        for status in (200, 201):
            with self.subTest(status=status):
                self.client._user_id = 42
                self.session.request.side_effect = [
                    response({"time_entry": entry(88, 2.5)}, status=status)
                ]
                self.assertEqual(self.client.create_entry(DAY, Decimal("2.5")), 88)
                payload = self.session.request.call_args.kwargs["json"]["time_entry"]
                self.assertEqual(payload["issue_id"], 123)
                self.assertEqual(payload["hours"], 2.5)

    def test_ambiguous_write_never_retries(self):
        for result in (
            requests.Timeout("sensitive response"),
            response(status=500),
            response(status=408),
            response(status=302, headers={"Location": "/new/time_entries.json"}),
            response({"time_entries": []}),
            response({"time_entry": entry(hours=9)}),
            response(),
        ):
            with self.subTest(result=type(result).__name__):
                self.session.reset_mock()
                self.client._user_id = 42
                self.session.request.side_effect = [result]
                with self.assertRaises(WriteUncertainError) as caught:
                    self.client.create_entry(DAY, Decimal("2"))
                self.assertEqual(self.session.request.call_count, 1)
                self.assertNotIn("sensitive response", str(caught.exception))

    def test_explicit_rejection_is_failed_not_success(self):
        self.client._user_id = 42
        self.session.request.side_effect = [
            response({"errors": ["private project name"]}, status=422)
        ]
        with self.assertRaises(RedmineError) as caught:
            self.client.create_entry(DAY, Decimal("2"))
        self.assertNotIsInstance(caught.exception, WriteUncertainError)
        self.assertNotIn("private project name", str(caught.exception))
