import contextlib
import io
import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from redmine_hours_helper.cli import main
from redmine_hours_helper.redmine import RedmineError, WriteUncertainError


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = Path(self.folder.name) / "config.local.json"
        self.config.write_text(
            json.dumps(
                {"redmine_url": "https://redmine.example.com", "issue_id": 123, "activity_id": 9}
            )
        )
        self.client = Mock()
        self.client.current_user_id.return_value = 42
        self.client.hours_for_day.return_value = Decimal("6")
        self.client.create_entry.return_value = 88

    def run_cli(self, *extra):
        stream = io.StringIO()
        with (
            patch.dict(os.environ, {"REDMINE_API_KEY": "example-key"}),
            patch("redmine_hours_helper.cli.RedmineClient") as client_type,
            patch("sys.stdin.isatty", return_value=False),
            contextlib.redirect_stdout(stream),
            contextlib.redirect_stderr(stream),
        ):
            client_type.return_value.__enter__.return_value = self.client
            result = main(["--config", str(self.config), "--year", "2020", "--month", "2", *extra])
        return result, stream.getvalue()

    def test_default_is_read_only(self):
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Planned: 40.00 h", output)
        self.client.create_entry.assert_not_called()

    def test_noninteractive_apply_requires_yes(self):
        code, _ = self.run_cli("--apply")
        self.assertEqual(code, 1)
        self.client.create_entry.assert_not_called()

    def test_explicit_apply_counts_confirmed_hours(self):
        code, output = self.run_cli("--apply", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.client.create_entry.call_count, 20)
        self.assertIn("Successfully added: 40.00 h", output)

    def test_failed_preview_never_applies(self):
        self.client.hours_for_day.side_effect = RedmineError("Unavailable")
        code, _ = self.run_cli("--apply", "--yes")
        self.assertEqual(code, 1)
        self.client.create_entry.assert_not_called()

    def test_uncertain_apply_stops_and_returns_failure(self):
        self.client.create_entry.side_effect = WriteUncertainError("Unknown")
        code, output = self.run_cli("--apply", "--yes")
        self.assertEqual(code, 1)
        self.assertEqual(self.client.create_entry.call_count, 1)
        self.assertIn("Successfully added: 0.00 h", output)

    def test_no_credentials_fail_before_connecting(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.stdin.isatty", return_value=False),
            patch("redmine_hours_helper.cli.RedmineClient") as client_type,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(["--config", str(self.config)]), 1)
            client_type.assert_not_called()

    def test_conflicting_flags_fail_before_connecting(self):
        for flags in (("--dry-run", "--apply"), ("--yes",), ("--demo",)):
            with (
                self.subTest(flags=flags),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as caught,
            ):
                main(list(flags))
            self.assertEqual(caught.exception.code, 2)
