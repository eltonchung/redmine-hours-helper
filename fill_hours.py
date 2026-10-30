"""Compatibility CLI launcher. Preview is the default; --apply explicitly enables writes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from redmine_hours_helper.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
