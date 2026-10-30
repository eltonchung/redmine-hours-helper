"""Optional bounded logs containing only date/status/hour metadata."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(path: Path | None) -> None:
    logger = logging.getLogger("redmine_hours_helper")
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    if path is None:
        logger.addHandler(logging.NullHandler())
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
