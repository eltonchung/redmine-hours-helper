"""Opt-in desktop integration tests; every API operation is mocked."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("RUN_GUI_TESTS") == "1", "Requires RUN_GUI_TESTS=1 and a display"
)
class GuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        from redmine_hours_helper.gui.app import HoursApp

        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = HoursApp(self.root, Path(self.folder.name) / "missing.local.json", demo=True)

    def tearDown(self):
        # Cancel scheduled callbacks before destroying Tcl to avoid cross-test callbacks.
        for job in self.root.tk.call("after", "info"):
            self.root.after_cancel(job)
        self.root.destroy()
        self.folder.cleanup()

    def wait_ready(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if self.app.plan is not None and not self.app.busy:
                return
            time.sleep(0.01)
        self.fail("GUI preview did not complete")

    def test_demo_is_offline_and_cannot_write(self):
        with patch("redmine_hours_helper.gui.app.RedmineClient") as network:
            self.wait_ready()
            self.assertGreater(len(self.app.table.get_children()), 27)
            self.assertEqual(str(self.app.apply_button["state"]), "disabled")
            self.app.apply()
            network.assert_not_called()

    def test_settings_change_invalidates_preview(self):
        self.wait_ready()
        self.app.fields["daily_hours"].set("7")
        self.assertIsNone(self.app.plan)
        self.assertEqual(str(self.app.apply_button["state"]), "disabled")

    def test_invalid_settings_show_error_without_worker(self):
        self.wait_ready()
        self.app.fields["issue_id"].set("bad-id")
        with patch("redmine_hours_helper.gui.app.messagebox.showerror") as dialog:
            self.app.preview()
            dialog.assert_called_once()
        self.assertFalse(self.app.busy)

    def test_save_never_includes_key(self):
        self.wait_ready()
        destination = Path(self.folder.name) / "config.local.json"
        self.app.fields["api_key"].set("session-only-test-key")
        with patch(
            "redmine_hours_helper.gui.app.filedialog.asksaveasfilename",
            return_value=str(destination),
        ):
            self.app._save()
        self.assertNotIn("session-only-test-key", destination.read_text())
        self.assertNotIn("api_key", destination.read_text())

    def test_layout_stays_within_window(self):
        self.wait_ready()
        self.assertLessEqual(
            self.app.apply_button.winfo_rooty() + self.app.apply_button.winfo_height(),
            self.root.winfo_rooty() + self.root.winfo_height(),
        )
        self.assertGreater(self.app.table.winfo_height(), 120)
