"""Preview and execution, independent of Tkinter and command-line presentation."""

import datetime as dt
import logging
from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from threading import Event
from typing import Callable

from .calendar import WorkCalendar, month_days
from .config import Settings
from .redmine import RedmineError, WriteUncertainError

logger = logging.getLogger(__name__)
ZERO = Decimal("0")


class Status(str, Enum):
    READY = "ready"
    COVERED = "covered"
    SKIPPED = "skipped"
    ERROR = "error"
    ADDED = "added"
    UNCERTAIN = "uncertain"
    CHANGED = "changed"
    NOT_RUN = "not_run"


STATUS_LABELS = {
    Status.READY: "待補填 / Ready",
    Status.COVERED: "已足額 / Covered",
    Status.SKIPPED: "略過 / Skipped",
    Status.ERROR: "失敗 / Failed",
    Status.ADDED: "已新增 / Added",
    Status.UNCERTAIN: "待核對 / Check Redmine",
    Status.CHANGED: "需重新預覽 / Preview again",
    Status.NOT_RUN: "未執行 / Not run",
}


@dataclass(frozen=True)
class DayResult:
    day: dt.date
    logged: Decimal | None = None
    planned: Decimal = ZERO
    added: Decimal = ZERO
    status: Status = Status.SKIPPED
    message: str = ""
    entry_id: int | None = None


@dataclass(frozen=True)
class MonthPlan:
    settings: Settings
    user_id: int
    year: int
    month: int
    rows: tuple[DayResult, ...]
    include_future: bool = False
    complete: bool = True

    @property
    def planned_hours(self) -> Decimal:
        return sum((row.planned for row in self.rows), ZERO)

    @property
    def can_apply(self) -> bool:
        return (
            self.complete
            and any(row.status == Status.READY for row in self.rows)
            and not any(row.status in (Status.ERROR, Status.UNCERTAIN) for row in self.rows)
        )


def gap(target: Decimal, logged: Decimal) -> Decimal:
    return max(ZERO, target - logged).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


Progress = Callable[[int, int, DayResult], None]


class HoursService:
    def __init__(
        self, client, settings: Settings, calendar: WorkCalendar, today: dt.date | None = None
    ):
        self.client = client
        self.settings = settings
        self.calendar = calendar
        self.today = today or dt.date.today()

    def preview(
        self,
        year: int,
        month: int,
        *,
        include_future: bool = False,
        progress: Progress | None = None,
        cancel: Event | None = None,
    ) -> MonthPlan:
        days = month_days(year, month)
        user_id = self.client.current_user_id()
        rows = []
        complete = True
        for index, day in enumerate(days, 1):
            if cancel and cancel.is_set():
                complete = False
                break
            if day > self.today and not include_future:
                row = DayResult(day, message="未來日期 / Future date")
            elif not self.calendar.is_workday(day):
                row = DayResult(day, message="休假日 / Non-working day")
            else:
                try:
                    logged = self.client.hours_for_day(day)
                    remaining = gap(self.settings.daily_hours, logged)
                    row = DayResult(
                        day,
                        logged,
                        remaining,
                        status=Status.READY if remaining > 0 else Status.COVERED,
                    )
                except RedmineError as exc:
                    row = DayResult(day, status=Status.ERROR, message=str(exc))
            rows.append(row)
            if progress:
                progress(index, len(days), row)
        return MonthPlan(self.settings, user_id, year, month, tuple(rows), include_future, complete)

    def apply(
        self, plan: MonthPlan, *, progress: Progress | None = None, cancel: Event | None = None
    ) -> tuple[DayResult, ...]:
        if plan.settings != self.settings or not plan.can_apply:
            raise RedmineError(
                "請先取得完整且無錯誤的預覽 / A complete, error-free preview is required."
            )
        if self.client.current_user_id() != plan.user_id:
            raise RedmineError("API 使用者已改變，請重新預覽 / API user changed; preview again.")
        rows = []
        stopped = False
        for index, original in enumerate(plan.rows, 1):
            row = original
            if original.status == Status.READY:
                if stopped or (cancel and cancel.is_set()):
                    row = replace(original, status=Status.NOT_RUN, message="已停止 / Stopped")
                elif (
                    original.day > self.today
                    and not plan.include_future
                    or not self.calendar.is_workday(original.day)
                ):
                    row = replace(
                        original,
                        status=Status.CHANGED,
                        message="日期規則已變動 / Date rules changed",
                    )
                    stopped = True
                else:
                    try:
                        logged = self.client.hours_for_day(original.day)
                        remaining = gap(self.settings.daily_hours, logged)
                        if remaining > original.planned:
                            row = replace(
                                original,
                                logged=logged,
                                status=Status.CHANGED,
                                message="待補時數增加，請重新預覽 / Gap increased; preview again",
                            )
                            stopped = True
                        elif remaining == 0:
                            row = replace(
                                original,
                                logged=logged,
                                status=Status.COVERED,
                                message="已由其他紀錄補足 / Already covered",
                            )
                        elif cancel and cancel.is_set():
                            row = replace(
                                original,
                                logged=logged,
                                status=Status.NOT_RUN,
                                message="已停止 / Stopped",
                            )
                        else:
                            entry_id = self.client.create_entry(original.day, remaining)
                            row = replace(
                                original,
                                logged=logged,
                                added=remaining,
                                status=Status.ADDED,
                                entry_id=entry_id,
                                message=f"Entry #{entry_id}",
                            )
                    except WriteUncertainError as exc:
                        row = replace(original, status=Status.UNCERTAIN, message=str(exc))
                        stopped = True
                    except RedmineError as exc:
                        row = replace(original, status=Status.ERROR, message=str(exc))
                        stopped = True
                logger.info("date=%s status=%s added=%s", row.day, row.status.value, row.added)
            rows.append(row)
            if progress:
                progress(index, len(plan.rows), row)
        return tuple(rows)
