"""Desktop workflow with background I/O and a main-thread-only Tk event queue."""

import datetime as dt
import os
import queue
import threading
import tkinter as tk
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..calendar import WorkCalendar
from ..config import ConfigError, Settings, load_settings, save_settings, validate_api_key
from ..redmine import RedmineClient, RedmineError
from ..service import STATUS_LABELS, HoursService, Status
from .theme import TEAL, apply_theme


class DemoClient:
    """Synthetic offline data. This client deliberately cannot create entries."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def current_user_id(self):
        return 1

    def hours_for_day(self, day):
        return Decimal(("8", "5.5", "6", "8", "4.25", "7", "0")[day.day % 7])


class HoursApp:
    def __init__(self, root: tk.Tk, config_path: Path, *, demo: bool = False):
        self.root = root
        self.config_path = config_path.resolve()
        self.demo = demo
        self.plan = None
        self.busy = False
        self.close_when_idle = False
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.inputs = []
        self.row_data = {}
        self.loading = True
        root.title("Redmine Hours Helper · 工時補填助手" + (" · Demo" if demo else ""))
        root.geometry("1220x850")
        root.minsize(1080, 800)
        apply_theme(root)
        today = dt.date.today()
        self.fields = {
            name: tk.StringVar(value=value)
            for name, value in {
                "redmine_url": "https://redmine.example.com",
                "api_key": "" if demo else os.environ.get("REDMINE_API_KEY", ""),
                "issue_id": "",
                "activity_id": "",
                "daily_hours": "8",
                "comment": "",
                "holidays_file": "",
                "timeout_seconds": "20",
                "year": str(today.year),
                "month": str(today.month),
            }.items()
        }
        self.include_future = tk.BooleanVar(value=False)
        self.show_key = tk.BooleanVar(value=False)
        self.status = tk.StringVar(
            value="先設定連線，再預覽待補工時 / Configure your connection, then preview."
        )
        self.detail = tk.StringVar(value="選取日期以查看詳細資訊 / Select a date for details.")
        self.metrics = [
            tk.StringVar(value="0.00 h"),
            tk.StringVar(value="0.00 h"),
            tk.StringVar(value="0 / 0"),
        ]
        self._build()
        if demo:
            self.fields["issue_id"].set("123")
            self.fields["activity_id"].set("9")
            self.fields["comment"].set("Project coordination")
            self.status.set("離線示範：所有工時皆為虛構資料 / Offline demo with synthetic data.")
        elif self.config_path.exists():
            self._load(self.config_path)
        self.loading = False
        for value in [*self.fields.values(), self.include_future]:
            value.trace_add("write", self._invalidate)
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(80, self._poll)
        if demo:
            root.after(150, self.preview)

    def _input(self, widget, state="normal"):
        self.inputs.append((widget, state))
        return widget

    def _field(self, parent, key, label, row, *, column=0, colspan=1, show=None):
        ttk.Label(parent, text=label, style="Hint.TLabel").grid(
            row=row, column=column, columnspan=colspan, sticky="w", pady=(10, 4)
        )
        entry = self._input(ttk.Entry(parent, textvariable=self.fields[key], show=show or ""))
        entry.grid(
            row=row + 1,
            column=column,
            columnspan=colspan,
            sticky="ew",
            padx=(0, 8) if colspan == 1 and column == 0 else 0,
        )
        return entry

    def _build(self):
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 22))
        ttk.Label(
            header,
            text="RH",
            background=TEAL,
            foreground="white",
            font=("Helvetica", 20, "bold"),
            padding=(14, 13),
        ).pack(side="left", padx=(0, 16))
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text="Redmine Hours Helper", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            titles,
            text="工時補填助手   /   A clearer view of your working month",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(5, 0))
        ttk.Label(
            header,
            text="OFFLINE DEMO" if self.demo else "預覽優先 · PREVIEW FIRST",
            foreground=TEAL,
            padding=9,
        ).pack(side="right")

        body = ttk.Frame(outer)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(body, style="Card.TFrame", padding=20, width=310)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 20))
        sidebar.columnconfigure((0, 1), weight=1, minsize=135)
        ttk.Label(sidebar, text="01   連線與目標", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(sidebar, text="Connection & destination", style="Hint.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(3, 6)
        )
        self._field(sidebar, "redmine_url", "Redmine URL · HTTPS", 2, colspan=2)
        self.key_entry = self._field(
            sidebar, "api_key", "API Key · 僅本次使用 / Session only", 4, colspan=2, show="•"
        )
        self._input(
            ttk.Checkbutton(
                sidebar,
                text="顯示金鑰 / Show key",
                variable=self.show_key,
                style="Card.TCheckbutton",
                command=lambda: self.key_entry.configure(show="" if self.show_key.get() else "•"),
            )
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self._field(sidebar, "issue_id", "議題 / Issue ID", 7)
        self._field(sidebar, "activity_id", "活動 / Activity ID", 7, column=1)
        self._field(sidebar, "daily_hours", "每日目標 / Hours", 9)
        self._field(sidebar, "timeout_seconds", "逾時 / Timeout (s)", 9, column=1)
        self._field(sidebar, "comment", "備註 / Comment", 11, colspan=2)
        self._field(sidebar, "holidays_file", "行事曆 / Calendar JSON", 13, colspan=2)
        self._input(
            ttk.Button(sidebar, text="選擇行事曆 / Browse", command=self._browse_calendar)
        ).grid(row=15, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        ttk.Label(
            sidebar,
            text="未設定時僅排除週末。\nWithout a calendar, only weekends are skipped.",
            style="Hint.TLabel",
            wraplength=270,
        ).grid(row=16, column=0, columnspan=2, sticky="w", pady=(9, 16))
        settings_buttons = ttk.Frame(sidebar, style="Card.TFrame")
        settings_buttons.grid(row=17, column=0, columnspan=2, sticky="ew")
        settings_buttons.columnconfigure((0, 1), weight=1)
        self._input(
            ttk.Button(settings_buttons, text="載入 / Load", command=self._choose_config)
        ).grid(row=0, column=0, sticky="ew", padx=(0, 7))
        self._input(ttk.Button(settings_buttons, text="儲存 / Save", command=self._save)).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Label(
            sidebar, text="設定檔不含 API Key\nAPI keys are never saved", style="Hint.TLabel"
        ).grid(row=18, column=0, columnspan=2, sticky="w", pady=(12, 0))
        sidebar.rowconfigure(19, weight=1)

        main = ttk.Frame(body)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        controls = ttk.Frame(main, style="Card.TFrame", padding=18)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text="02   選擇月份 / Month", style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12)
        )
        for column, (key, values, width) in enumerate(
            (
                ("year", list(range(dt.date.today().year - 5, dt.date.today().year + 6)), 9),
                ("month", list(range(1, 13)), 5),
            )
        ):
            widget = self._input(
                ttk.Combobox(controls, textvariable=self.fields[key], values=values, width=width)
            )
            widget.grid(row=1, column=column, padx=(0, 10), sticky="w")
        self._input(
            ttk.Checkbutton(
                controls,
                text="包含未來日期 / Include future dates",
                variable=self.include_future,
                style="Card.TCheckbutton",
            )
        ).grid(row=1, column=2, columnspan=2, sticky="w")
        cards = ttk.Frame(main)
        cards.grid(row=1, column=0, sticky="ew", pady=16)
        for index, title in enumerate(
            ("預計補填 / Planned", "成功新增 / Added", "成功 / 未完成 · Entries")
        ):
            cards.columnconfigure(index, weight=1, uniform="metrics")
            card = ttk.Frame(cards, style="Card.TFrame", padding=(16, 14))
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10) if index < 2 else 0)
            ttk.Label(card, text=title, style="Hint.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=self.metrics[index], style="Metric.TLabel").pack(
                anchor="w", pady=(8, 0)
            )
        toolbar = ttk.Frame(main)
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(
            toolbar, text="03   每日明細 / Daily overview", font=("Helvetica", 13, "bold")
        ).pack(side="left")
        self.stop_button = ttk.Button(
            toolbar, text="停止 / Stop", command=self.cancel.set, state="disabled"
        )
        self.stop_button.pack(side="right")

        table_frame = ttk.Frame(main, style="Card.TFrame")
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(
            table_frame,
            columns=("date", "logged", "planned", "added", "status"),
            show="headings",
            selectmode="browse",
        )
        for key, title, width in (
            ("date", "日期 / Date", 118),
            ("logged", "已填 / Logged", 105),
            ("planned", "待補 / Planned", 115),
            ("added", "新增 / Added", 105),
            ("status", "狀態 / Status", 200),
        ):
            self.table.heading(key, text=title)
            self.table.column(
                key, width=width, minwidth=width, anchor="w" if key in ("date", "status") else "e"
            )
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        for tag, foreground, background in (
            ("skipped", "#8a99a4", "#f8fafb"),
            ("covered", "#587a72", "#f5faf8"),
            ("error", "#b42318", "#fff1ee"),
            ("uncertain", "#b45309", "#fff6e8"),
            ("added", "#087e83", "#e9f7f4"),
            ("changed", "#b45309", "#fff6e8"),
        ):
            self.table.tag_configure(tag, foreground=foreground, background=background)
        self.table.bind("<<TreeviewSelect>>", self._select_row)
        ttk.Label(main, textvariable=self.detail, style="Muted.TLabel", wraplength=680).grid(
            row=4, column=0, sticky="ew", pady=(9, 12)
        )
        actions = ttk.Frame(main)
        actions.grid(row=5, column=0, sticky="ew")
        self.preview_button = ttk.Button(actions, text="預覽補填 / Preview", command=self.preview)
        self.preview_button.pack(side="left")
        self.apply_button = ttk.Button(
            actions,
            text="執行補填 / Apply entries",
            style="Primary.TButton",
            command=self.apply,
            state="disabled",
        )
        self.apply_button.pack(side="right")
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.grid(row=2, column=0, sticky="ew", pady=(20, 8))
        ttk.Label(outer, textvariable=self.status, style="Muted.TLabel", wraplength=1120).grid(
            row=3, column=0, sticky="w"
        )

    def _invalidate(self, *args):
        if not self.loading and not self.busy:
            self.plan = None
            self.apply_button.configure(state="disabled")
            self.status.set("設定已變更，請重新預覽 / Settings changed; preview again.")

    def _settings(self):
        return Settings.from_dict(
            {
                key: value.get()
                for key, value in self.fields.items()
                if key not in ("api_key", "year", "month")
            }
        )

    def _load(self, path):
        try:
            settings = load_settings(path)
            self.config_path = path.resolve()
            for key, value in settings.to_dict().items():
                self.fields[key].set(str(value))
            self.status.set("已載入設定；請預覽 / Settings loaded; ready to preview.")
        except ConfigError as exc:
            messagebox.showerror("設定 / Configuration", str(exc), parent=self.root)

    def _choose_config(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="載入設定 / Load settings", filetypes=[("JSON", "*.json")]
        )
        if path:
            self._load(Path(path))

    def _save(self):
        try:
            settings = self._settings()
            chosen = filedialog.asksaveasfilename(
                parent=self.root,
                title="儲存設定（不含金鑰）/ Save settings (no key)",
                initialdir=self.config_path.parent,
                initialfile="config.local.json",
                defaultextension=".local.json",
            )
            if not chosen:
                return
            path = Path(chosen).resolve()
            if not path.name.endswith(".local.json"):
                raise ConfigError(
                    "請使用 *.local.json 檔名，以便 Git 排除 / Use a *.local.json filename so Git ignores it."
                )
            data = settings.to_dict()
            if settings.holidays_file:
                data["holidays_file"] = str(
                    (self.config_path.parent / settings.holidays_file).resolve()
                )
            save_settings(Settings.from_dict(data), path)
            self._load(path)
            self.status.set("已儲存設定，未儲存 API Key / Settings saved without the API key.")
        except (ConfigError, OSError) as exc:
            messagebox.showerror(
                "設定 / Configuration",
                str(exc)
                if isinstance(exc, ConfigError)
                else "無法儲存設定 / Could not save settings.",
                parent=self.root,
            )

    def _browse_calendar(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="選擇行事曆 / Select calendar", filetypes=[("JSON", "*.json")]
        )
        if path:
            self.fields["holidays_file"].set(path)

    def _set_busy(self, busy):
        self.busy = busy
        for widget, normal in self.inputs:
            widget.configure(state="disabled" if busy else normal)
        self.preview_button.configure(state="disabled" if busy else "normal")
        self.apply_button.configure(
            state="normal"
            if not busy and self.plan and self.plan.can_apply and not self.demo
            else "disabled"
        )
        self.stop_button.configure(state="normal" if busy else "disabled")

    def _snapshot(self):
        settings = self._settings()
        calendar_path = (
            self.config_path.parent / settings.holidays_file if settings.holidays_file else None
        )
        calendar = WorkCalendar.load(calendar_path)
        key = "offline-demo" if self.demo else validate_api_key(self.fields["api_key"].get())
        year, month = int(self.fields["year"].get()), int(self.fields["month"].get())
        return settings, calendar, key, year, month, self.include_future.get()

    def preview(self):
        if self.busy:
            return
        try:
            snapshot = self._snapshot()
        except (ConfigError, ValueError) as exc:
            messagebox.showerror(
                "請檢查設定 / Check settings",
                str(exc)
                if isinstance(exc, ConfigError)
                else "年份與月份必須是整數 / Year and month must be integers.",
                parent=self.root,
            )
            return
        self.plan = None
        self.table.delete(*self.table.get_children())
        self.row_data.clear()
        self.metrics[0].set("0.00 h")
        self.metrics[1].set("0.00 h")
        self.metrics[2].set("0 / 0")
        self.detail.set("查詢中，不會新增工時 / Reading entries; no writes during preview.")
        self._start("preview", snapshot)

    def apply(self):
        if self.busy or self.demo or not self.plan or not self.plan.can_apply:
            return
        try:
            snapshot = self._snapshot()
        except (ConfigError, ValueError) as exc:
            messagebox.showerror("設定 / Configuration", str(exc), parent=self.root)
            return
        count = sum(row.status == Status.READY for row in self.plan.rows)
        if not messagebox.askyesno(
            "確認補填 / Confirm entries",
            f"最多新增 {count} 筆、{self.plan.planned_hours:.2f} 小時。\nCreate up to {count} entries / {self.plan.planned_hours:.2f} hours.\n\n送出前會重新查詢差額。確定執行？\nHours are rechecked before each write. Continue?",
            parent=self.root,
        ):
            return
        plan = self.plan
        self.plan = None
        self._start("apply", snapshot, plan)

    def _start(self, kind, snapshot, plan=None):
        self.cancel = threading.Event()
        self.progress["value"] = 0
        self._set_busy(True)
        self.status.set(
            "正在預覽 / Previewing…" if kind == "preview" else "正在補填 / Applying entries…"
        )
        settings, calendar, key, year, month, future = snapshot

        def work():
            try:
                with DemoClient() if self.demo else RedmineClient(settings, key) as client:
                    service = HoursService(client, settings, calendar)

                    def callback(done, total, row):
                        self.events.put(("progress", (done, total, row)))

                    result = (
                        service.preview(
                            year,
                            month,
                            include_future=future,
                            progress=callback,
                            cancel=self.cancel,
                        )
                        if kind == "preview"
                        else service.apply(plan, progress=callback, cancel=self.cancel)
                    )
                self.events.put((kind, result))
            except (ConfigError, RedmineError) as exc:
                self.events.put(("error", str(exc)))
            except Exception:
                self.events.put(
                    (
                        "error",
                        "未預期錯誤；若已送出請先核對 Redmine / Unexpected error; check Redmine if writing had started.",
                    )
                )

        threading.Thread(target=work, name="redmine-worker", daemon=True).start()

    def _upsert(self, row):
        key = row.day.isoformat()
        self.row_data[key] = row
        values = (
            key,
            "—" if row.logged is None else f"{row.logged:.2f}",
            f"{row.planned:.2f}",
            f"{row.added:.2f}",
            STATUS_LABELS[row.status],
        )
        if self.table.exists(key):
            self.table.item(key, values=values, tags=(row.status.value,))
        else:
            self.table.insert("", "end", iid=key, values=values, tags=(row.status.value,))

    def _select_row(self, event=None):
        selection = self.table.selection()
        if selection:
            row = self.row_data[selection[0]]
            self.detail.set(f"{row.day}  ·  {STATUS_LABELS[row.status]}  ·  {row.message or '—'}")

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    done, total, row = value
                    self.progress["value"] = done / total * 100
                    self._upsert(row)
                    continue
                if kind == "preview":
                    self.plan = value
                    self.metrics[0].set(f"{value.planned_hours:.2f} h")
                    errors = sum(row.status == Status.ERROR for row in value.rows)
                    self.metrics[2].set(f"0 / {errors}")
                    self.status.set(
                        "預覽已停止，請重新預覽 / Preview stopped; run again."
                        if not value.complete
                        else "預覽含錯誤，請修正後重試 / Preview contains errors; fix them before applying."
                        if errors
                        else "離線示範完成，未連線至 Redmine / Offline demo ready; no network requests."
                        if self.demo
                        else "預覽完成，請檢查每日明細 / Preview ready; review daily entries before applying."
                    )
                    self.detail.set(
                        "預覽不會新增工時；執行時會重新查詢 / Preview creates no entries; apply rechecks each date."
                    )
                elif kind == "apply":
                    added = sum(row.added for row in value)
                    success = sum(row.status == Status.ADDED for row in value)
                    failures = sum(
                        row.status
                        in (Status.ERROR, Status.UNCERTAIN, Status.CHANGED, Status.NOT_RUN)
                        for row in value
                    )
                    self.metrics[1].set(f"{added:.2f} h")
                    self.metrics[2].set(f"{success} / {failures}")
                    self.status.set(
                        "補填已停止，請查看明細並核對 Redmine / Stopped; review details and check Redmine."
                        if failures
                        else "補填完成；再次操作前需重新預覽 / Complete; preview again before another run."
                    )
                    self.detail.set(
                        "總計只計入已確認的新增紀錄 / Totals include confirmed entries only."
                    )
                elif kind == "error":
                    self.plan = None
                    self.status.set(value)
                    if not self.close_when_idle:
                        messagebox.showerror("執行結果 / Result", value, parent=self.root)
                self._set_busy(False)
                if self.close_when_idle:
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _close(self):
        if self.busy:
            if messagebox.askyesno(
                "停止並關閉 / Stop and close",
                "會等待目前請求結束；已新增的紀錄不會撤銷。\nWait for the current operation to finish; created entries remain.\n\n停止並關閉？ / Stop and close?",
                parent=self.root,
            ):
                self.cancel.set()
                self.close_when_idle = True
                self.status.set(
                    "正在等待目前請求結束 / Waiting for the current operation to finish…"
                )
        else:
            self.root.destroy()
