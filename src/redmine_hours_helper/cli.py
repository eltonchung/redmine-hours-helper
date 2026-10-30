"""Command line: preview by default, explicitly opt in to writes."""

import argparse
import datetime as dt
import getpass
import os
import sys
from pathlib import Path

from . import __version__
from .calendar import WorkCalendar
from .config import ConfigError, load_settings, validate_api_key
from .logging_setup import configure_logging
from .redmine import RedmineClient, RedmineError
from .service import STATUS_LABELS, HoursService, Status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Redmine 工時補填 / Redmine Hours Helper (preview by default)"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--gui", action="store_true", help="開啟視窗 / Open the desktop GUI")
    parser.add_argument(
        "--demo", action="store_true", help="離線 GUI 示範 / Offline GUI demo (requires --gui)"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config.local.json"), help="設定檔 / Configuration file"
    )
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    parser.add_argument("--month", type=int, default=dt.date.today().month)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="僅預覽（預設）/ Preview only (default)"
    )
    mode.add_argument("--apply", action="store_true", help="預覽後送出 / Apply after preview")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="略過 CLI 確認，須搭配 --apply / Skip confirmation with --apply",
    )
    parser.add_argument(
        "--include-future", action="store_true", help="包含未來日期 / Include future dates"
    )
    parser.add_argument(
        "--log-file", type=Path, help="選填紀錄路徑，例如 logs/run.log / Optional log file"
    )
    return parser


def print_rows(rows) -> None:
    print("日期 / Date  | 已填 / Logged | 待補 / Planned | 成功 / Added | 狀態 / Status")
    for row in rows:
        logged = "—" if row.logged is None else f"{row.logged:.2f}"
        print(
            f"{row.day} | {logged:>13} | {row.planned:>14.2f} | {row.added:>12.2f} | {STATUS_LABELS[row.status]}"
        )
        if row.message and row.status not in (Status.SKIPPED, Status.ADDED):
            print(f"  {row.message}")


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.gui:
        if args.apply or args.yes or args.dry_run or args.include_future or args.log_file:
            parser.error(
                "GUI 請使用畫面上的操作 / Use the GUI controls instead of CLI execution flags."
            )
        from .gui import launch

        return launch(args.config, demo=args.demo)
    if args.demo or (args.yes and not args.apply):
        parser.error("--demo requires --gui; --yes requires --apply")
    try:
        settings = load_settings(args.config)
        calendar_path = (
            args.config.resolve().parent / settings.holidays_file
            if settings.holidays_file
            else None
        )
        calendar = WorkCalendar.load(calendar_path)
        key = os.environ.get("REDMINE_API_KEY", "")
        if not key and sys.stdin.isatty():
            key = getpass.getpass("Redmine API Key（不儲存 / not saved）: ")
        key = validate_api_key(key)
        configure_logging(args.log_file)
        with RedmineClient(settings, key) as client:
            service = HoursService(client, settings, calendar)
            plan = service.preview(args.year, args.month, include_future=args.include_future)
            print_rows(plan.rows)
            print(f"\n預計補填 / Planned: {plan.planned_hours:.2f} h")
            if not plan.complete or any(row.status == Status.ERROR for row in plan.rows):
                print(
                    "預覽含錯誤，禁止送出 / Preview contains errors; no writes allowed.",
                    file=sys.stderr,
                )
                return 1
            if not args.apply or not plan.can_apply:
                return 0
            if not args.yes:
                if not sys.stdin.isatty():
                    raise ConfigError(
                        "非互動執行須提供 --apply --yes / Non-interactive writes require --apply --yes."
                    )
                answer = input("確認新增以上工時？輸入 yes / Create these entries? Type yes: ")
                if answer.strip().lower() != "yes":
                    print("已取消，未送出 / Cancelled; nothing sent.")
                    return 0
            rows = service.apply(plan)
            print_rows(rows)
            actual = sum(row.added for row in rows)
            failed = sum(
                row.status in (Status.ERROR, Status.UNCERTAIN, Status.CHANGED, Status.NOT_RUN)
                for row in rows
            )
            print(f"\n成功補填 / Successfully added: {actual:.2f} h; 未完成 / Unfinished: {failed}")
            return 1 if failed else 0
    except (ConfigError, RedmineError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError:
        print(
            "本機檔案讀寫失敗，請檢查路徑與權限 / Local file operation failed; check paths and permissions.",
            file=sys.stderr,
        )
        return 1
    except (KeyboardInterrupt, EOFError):
        print(
            "\n已中止；若已開始送出，請核對 Redmine / Interrupted; verify Redmine if writing had started.",
            file=sys.stderr,
        )
        return 130
