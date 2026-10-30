"""Compatibility launcher; the desktop app now lives in src/redmine_hours_helper/gui."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from redmine_hours_helper.gui import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
