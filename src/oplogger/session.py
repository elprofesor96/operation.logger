"""Session lifecycle."""

from __future__ import annotations

import os
import signal
from datetime import datetime, timezone
from pathlib import Path

from oplogger import console as ui
from oplogger.logger import PlainLogger, TmuxLogger, detect_tmux
from oplogger.parser import LogParser
from oplogger.state import State

LOGS_DIR = "oplogs"


class SessionManager:
    def __init__(self) -> None:
        self._state = State.default()

    def start(self) -> int:
        if self._state.active:
            data = self._state.load() or {}
            ui.error(f"Already logging in [bold]{data.get('dir', '?')}[/]")
            ui.error("Run [bold]oplogger stop[/] first.")
            return 1

        ui.banner()

        logs_dir = Path.cwd() / LOGS_DIR
        logs_dir.mkdir(exist_ok=True)

        in_tmux = detect_tmux()

        if in_tmux:
            ui.debug("tmux detected — logging all panes")
            logger = TmuxLogger(logs_dir)
            logger.start()

            self._state.save({
                "dir": str(logs_dir),
                "type": "tmux",
                "started": datetime.now(timezone.utc).isoformat(),
                "tmux_session": TmuxLogger.current_session(),
            })

        else:
            ui.debug("Plain terminal — logging this shell")

            self._state.save({
                "dir": str(logs_dir),
                "type": "plain",
                "started": datetime.now(timezone.utc).isoformat(),
            })

            # Blocks until user exits shell or oplogger stop kills the child.
            logger = PlainLogger(logs_dir)
            logger.start()

            # Shell exited — finalize.
            if self._state.active:
                self._finalize(logs_dir)
                self._state.clear()

        return 0

    def stop(self) -> int:
        data = self._state.load()
        if data is None:
            ui.error("No active session.")
            return 1

        logs_dir = Path(data["dir"])

        if data["type"] == "tmux":
            sess = data.get("tmux_session")
            if sess:
                TmuxLogger.stop_all(sess, logs_dir)
            ui.info(f"Stopped tmux session [hl]{sess}[/]")
            self._finalize(logs_dir)
            self._state.clear()

        elif data["type"] == "plain":
            pid = PlainLogger.read_pid(logs_dir)
            if pid:
                try:
                    os.kill(pid, signal.SIGHUP)
                    ui.info("Stopping — report will be generated automatically.")
                except ProcessLookupError:
                    ui.info("Session already ended.")
                    self._finalize(logs_dir)
                    self._state.clear()
            else:
                ui.warn("No PID found — generating report from existing logs.")
                self._finalize(logs_dir)
                self._state.clear()

        return 0

    def status(self) -> int:
        data = self._state.load()
        if data is None:
            ui.info("No active session.")
            return 0

        logs_dir = Path(data["dir"])
        logs = list(logs_dir.glob("*.log"))
        total = sum(f.stat().st_size for f in logs)

        rows = [
            ("Directory", str(logs_dir)),
            ("Type", data["type"]),
            ("Started", data["started"]),
        ]
        if data.get("tmux_session"):
            rows.append(("tmux session", data["tmux_session"]))
        pid = PlainLogger.read_pid(logs_dir)
        if pid:
            rows.append(("Shell PID", str(pid)))
        rows.append(("Log files", f"{len(logs)}  ({_human(total)})"))

        ui.status_table(rows)
        return 0

    def parse(self, directory: Path | None = None) -> int:
        logs_dir = directory or Path.cwd() / LOGS_DIR

        if not logs_dir.is_dir():
            ui.error(f"Not found: [bold]{logs_dir}[/]")
            return 1

        self._finalize(logs_dir)
        return 0

    @staticmethod
    def _finalize(logs_dir: Path) -> None:
        LogParser(logs_dir).run()


def _human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"
