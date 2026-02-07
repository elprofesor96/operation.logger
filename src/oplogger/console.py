"""Rich console and output helpers."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.theme import Theme

from oplogger import __version__

_theme = Theme({
    "info": "green",
    "warn": "yellow",
    "error": "bold red",
    "debug": "blue",
    "hl": "bold cyan",
})

console = Console(theme=_theme, stderr=True)


def banner() -> None:
    console.print(f"\n [bold cyan]oplogger[/] [dim]v{__version__}[/]\n")


def info(msg: str) -> None:
    console.print(f" [info]✓[/] {msg}")


def warn(msg: str) -> None:
    console.print(f" [warn]![/] {msg}")


def error(msg: str) -> None:
    console.print(f" [error]✗[/] {msg}")


def debug(msg: str) -> None:
    console.print(f" [debug]•[/] {msg}")


def status_table(rows: list[tuple[str, str]]) -> None:
    t = Table(show_header=False, border_style="dim", padding=(0, 1))
    t.add_column(style="bold")
    t.add_column()
    for k, v in rows:
        t.add_row(k, v)
    console.print(t)
