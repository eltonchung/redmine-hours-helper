"""Explicit, year-specific holidays and working-day overrides."""

import calendar
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError


@dataclass(frozen=True)
class WorkCalendar:
    holidays: frozenset[dt.date] = frozenset()
    workdays: frozenset[dt.date] = frozenset()

    def is_workday(self, day: dt.date) -> bool:
        return day in self.workdays or (day.weekday() < 5 and day not in self.holidays)

    @classmethod
    def load(cls, path: Path | None) -> "WorkCalendar":
        if path is None:
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) - {"holidays", "workdays"}:
                raise ValueError
            sets = []
            for key in ("holidays", "workdays"):
                items = data.get(key, [])
                if not isinstance(items, list):
                    raise ValueError
                dates = set()
                for value in items:
                    day = dt.date.fromisoformat(value)
                    if day.isoformat() != value:
                        raise ValueError
                    dates.add(day)
                sets.append(frozenset(dates))
            if sets[0] & sets[1]:
                raise ValueError
            return cls(*sets)
        except (OSError, ValueError, TypeError):
            raise ConfigError(
                "行事曆格式錯誤：請使用 YYYY-MM-DD，休假與補班不可重複 / Invalid calendar: use YYYY-MM-DD and disjoint holidays/workdays."
            ) from None


def month_days(year: int, month: int) -> tuple[dt.date, ...]:
    try:
        return tuple(
            dt.date(year, month, n) for n in range(1, calendar.monthrange(year, month)[1] + 1)
        )
    except (ValueError, TypeError):
        raise ConfigError("年份或月份無效 / Invalid year or month.") from None
