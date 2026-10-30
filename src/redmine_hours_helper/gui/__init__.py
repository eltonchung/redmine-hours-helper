"""GUI entry points, imported only when a desktop window is requested."""

import argparse
from pathlib import Path

from ..console import configure_console


def launch(config_path: Path, *, demo: bool = False) -> int:
    try:
        import tkinter as tk

        from .app import HoursApp
    except ImportError:
        print(
            "缺少 Tkinter，請安裝含 Tk 的 Python / Tkinter is missing; install Python with Tk support."
        )
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        print("無法開啟圖形環境；可改用 CLI / Cannot open a desktop display; use the CLI instead.")
        return 1
    HoursApp(root, config_path, demo=demo)
    root.mainloop()
    return 0


def main(argv=None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="Redmine Hours Helper GUI")
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    parser.add_argument("--demo", action="store_true", help="離線示範 / Offline demo")
    args = parser.parse_args(argv)
    return launch(args.config, demo=args.demo)
