"""Keep bilingual output readable in terminals, redirected files and Windows CI."""

import sys


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                # Embedded callers may supply closed or non-reconfigurable streams.
                pass
