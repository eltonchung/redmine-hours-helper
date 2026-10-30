"""A small, consistent ttk palette without extra UI dependencies."""

from tkinter import font, ttk

BG = "#f3f6f8"
PAPER = "#ffffff"
INK = "#203442"
MUTED = "#687b89"
TEAL = "#087e83"


def apply_theme(root) -> None:
    root.configure(background=BG)
    default = font.nametofont("TkDefaultFont")
    default.configure(size=11)
    family = default.actual("family")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(family, 11), foreground=INK, background=BG)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PAPER)
    style.configure("TLabel", background=BG)
    style.configure("Card.TLabel", background=PAPER)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Hint.TLabel", background=PAPER, foreground=MUTED, font=(family, 10))
    style.configure("Title.TLabel", font=(family, 25, "bold"))
    style.configure("Section.TLabel", background=PAPER, font=(family, 13, "bold"))
    style.configure("Metric.TLabel", background=PAPER, foreground=TEAL, font=(family, 27, "bold"))
    style.configure("TEntry", padding=7, fieldbackground=PAPER, bordercolor="#d9e2e8")
    style.configure("TCombobox", padding=6, fieldbackground=PAPER, arrowsize=13)
    style.map("TCombobox", fieldbackground=[("readonly", PAPER)], foreground=[("readonly", INK)])
    style.configure("TButton", padding=(12, 9), background="#e7eef2", borderwidth=0)
    style.map("TButton", background=[("active", "#d9e6eb")], foreground=[("disabled", "#9aa8b1")])
    style.configure("Primary.TButton", background=TEAL, foreground="white")
    style.map(
        "Primary.TButton",
        background=[("disabled", "#cedce0"), ("active", "#06676b")],
        foreground=[("disabled", "#6f858d"), ("!disabled", "white")],
    )
    style.configure("TCheckbutton", background=BG, padding=3)
    style.configure("Card.TCheckbutton", background=PAPER)
    style.configure(
        "Treeview",
        rowheight=34,
        background=PAPER,
        fieldbackground=PAPER,
        borderwidth=0,
        font=(family, 11),
    )
    style.configure(
        "Treeview.Heading",
        background="#eaf0f4",
        foreground=MUTED,
        font=(family, 10, "bold"),
        padding=(8, 10),
        relief="flat",
    )
    style.map("Treeview", background=[("selected", "#d9eeee")], foreground=[("selected", INK)])
    style.configure(
        "Horizontal.TProgressbar", background=TEAL, troughcolor="#e3ebef", borderwidth=0
    )
