"""CLI entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from oplogger import __version__

app = typer.Typer(
    name="oplogger",
    help="Terminal session logger for pentesters & bug bounty hunters.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        from oplogger.console import console
        console.print(f"[bold]oplogger[/] {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-v", help="Show version.", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    pass


@app.command()
def start() -> None:
    """Start logging the current terminal or all tmux panes."""
    from oplogger.session import SessionManager
    raise typer.Exit(SessionManager().start())


@app.command()
def stop() -> None:
    """Stop logging and generate the Markdown report."""
    from oplogger.session import SessionManager
    raise typer.Exit(SessionManager().stop())


@app.command()
def status() -> None:
    """Show active session info."""
    from oplogger.session import SessionManager
    raise typer.Exit(SessionManager().status())


@app.command()
def parse(
    directory: Annotated[
        Optional[Path],
        typer.Argument(help="Path to oplogs/ directory. Defaults to ./oplogs"),
    ] = None,
) -> None:
    """Re-generate Markdown report from existing raw logs."""
    from oplogger.session import SessionManager
    raise typer.Exit(SessionManager().parse(directory))
