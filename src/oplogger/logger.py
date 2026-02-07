"""Capture backends — pty fork for plain terminals, pipe-pane for tmux."""

from __future__ import annotations

import fcntl
import os
import re
import select
import signal
import subprocess
import sys
import termios
import textwrap
import tty
from datetime import datetime, timezone
from pathlib import Path

from oplogger import console as ui

# Bytes-level regex to strip ANSI/terminal escape sequences from log output.
# Covers CSI (colors, cursor, bracketed paste ?2004h/l, etc.),
# OSC (title set), and other common escape sequences.
_ANSI_BYTES = re.compile(
    rb"\x1b"
    rb"(?:"
    rb"\[[0-9;?]*[a-zA-Z]"      # CSI: \x1b[...letter  (includes ?2004h etc.)
    rb"|\[[0-9;?]*[ -/]*[a-zA-Z]"  # CSI with intermediate bytes
    rb"|\][^\x07]*\x07"           # OSC terminated by BEL
    rb"|\][^\x1b]*\x1b\\"        # OSC terminated by ST
    rb"|\([0-9A-Za-z]"           # charset selection
    rb"|[=>]"                     # DECKPAM / DECKPNM
    rb"|[78]"                     # save/restore cursor
    rb")"
)


def detect_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


class PlainLogger:
    """Spawn a shell inside a PTY. Tee all output to a log file.

    Uses pty.fork() for full control over terminal save/restore
    so the terminal is never left in a broken state.
    """

    def __init__(self, logs_dir: Path) -> None:
        self._logs_dir = logs_dir
        self.child_pid: int = 0

    def start(self) -> int:
        """Fork a PTY shell. Blocks until the shell exits. Returns exit code."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logfile = self._logs_dir / f"terminal_{ts}.log"

        _write_header(logfile, {
            "type": "plain",
            "started": datetime.now(timezone.utc).isoformat(),
            "cwd": str(Path.cwd()),
        })

        ui.info(f"Logging to [hl]{logfile}[/]")
        ui.info("Type [bold]exit[/] or run [bold]oplogger stop[/] to finish.\n")

        # Save original terminal state so we can always restore it.
        stdin_fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(stdin_fd)

        import pty

        child_pid, pty_fd = pty.fork()

        if child_pid == 0:
            # ---- child ---- exec the user's shell
            shell = os.environ.get("SHELL", "/bin/sh")
            os.execvp(shell, [shell, "-l"])
            # never reached

        # ---- parent ----
        self.child_pid = child_pid

        # Write PID file so `oplogger stop` can find us.
        pid_file = self._logs_dir / ".oplogger.pid"
        pid_file.write_text(str(child_pid))

        # Put stdin in raw mode so keystrokes pass through to the PTY.
        tty.setraw(stdin_fd)

        # Propagate terminal size to the child.
        _copy_winsize(stdin_fd, pty_fd)

        # Resize the child PTY when our terminal resizes.
        def _handle_winch(signum: int, frame: object) -> None:
            _copy_winsize(stdin_fd, pty_fd)

        signal.signal(signal.SIGWINCH, _handle_winch)

        exit_code = 0
        try:
            with open(logfile, "ab") as log:
                exit_code = self._io_loop(stdin_fd, pty_fd, log)
        finally:
            # Always restore the terminal, no matter what.
            termios.tcsetattr(stdin_fd, termios.TCSAFLUSH, old_attrs)
            pid_file.unlink(missing_ok=True)

        return exit_code

    @staticmethod
    def _io_loop(stdin_fd: int, pty_fd: int, log_fp: object) -> int:
        """Shuttle bytes between stdin↔pty and tee pty output to the log."""
        line_buf = _LineBuffer()

        while True:
            try:
                rfds, _, _ = select.select([stdin_fd, pty_fd], [], [], 0.25)
            except (OSError, ValueError):
                break

            if stdin_fd in rfds:
                try:
                    data = os.read(stdin_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                os.write(pty_fd, data)

            if pty_fd in rfds:
                try:
                    data = os.read(pty_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                # Write raw to real terminal (user sees colors etc.).
                os.write(sys.stdout.fileno(), data)
                # Feed through line buffer which strips escapes and
                # renders \r / \b like a real terminal would.
                for line in line_buf.feed(data):
                    log_fp.write(line)  # type: ignore[union-attr]
                log_fp.flush()  # type: ignore[union-attr]

        # Flush any remaining partial line.
        final = line_buf.flush()
        if final:
            log_fp.write(final)  # type: ignore[union-attr]
            log_fp.flush()  # type: ignore[union-attr]

        # Reap the child.
        try:
            _, status = os.waitpid(0, 0)
            return os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            return 0

    @staticmethod
    def read_pid(logs_dir: Path) -> int | None:
        """Read child PID from pid file."""
        pid_file = logs_dir / ".oplogger.pid"
        if pid_file.is_file():
            try:
                return int(pid_file.read_text().strip())
            except (ValueError, OSError):
                return None
        return None


class TmuxLogger:
    def __init__(self, logs_dir: Path) -> None:
        self._logs_dir = logs_dir
        self._session = self.current_session()

    def start(self) -> None:
        panes = self._list_panes()
        for p in panes:
            self._attach(p)

        self._install_hooks()

        ui.info(f"Logging [bold]{len(panes)}[/] pane(s) — new panes auto-logged")
        ui.info("Run [bold]oplogger stop[/] when done.")

    @staticmethod
    def current_session() -> str:
        try:
            return subprocess.check_output(
                ["tmux", "display-message", "-p", "#S"], text=True,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    @classmethod
    def stop_all(cls, session: str, logs_dir: Path | None = None) -> None:
        try:
            ids = subprocess.check_output(
                ["tmux", "list-panes", "-s", "-t", session, "-F", "#{pane_id}"],
                text=True,
            ).strip().splitlines()
        except subprocess.CalledProcessError:
            ids = []

        for pid in ids:
            _tmux("pipe-pane", "-t", pid)

        _tmux("set-hook", "-u", "-t", session, "after-split-window")
        _tmux("set-hook", "-u", "-t", session, "after-new-window")

        # Clean up the hook helper script.
        if logs_dir:
            hook = logs_dir / ".oplogger_hook.sh"
            hook.unlink(missing_ok=True)

    def _list_panes(self) -> list[dict[str, str]]:
        fmt = "#{pane_id}\t#{window_index}\t#{pane_index}\t#{pane_current_path}"
        try:
            raw = subprocess.check_output(
                ["tmux", "list-panes", "-s", "-t", self._session, "-F", fmt],
                text=True,
            )
        except subprocess.CalledProcessError:
            return []

        panes: list[dict[str, str]] = []
        for line in raw.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                panes.append({
                    "pane_id": parts[0],
                    "window": parts[1],
                    "pane": parts[2],
                    "cwd": parts[3],
                })
        return panes

    def _attach(self, pane: dict[str, str]) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logfile = self._logs_dir / f"pane_w{pane['window']}_p{pane['pane']}_{ts}.log"

        _write_header(logfile, {
            "type": "tmux",
            "pane_id": pane["pane_id"],
            "window": pane["window"],
            "pane": pane["pane"],
            "started": datetime.now(timezone.utc).isoformat(),
            "cwd": pane["cwd"],
        })

        _tmux("pipe-pane", "-t", pane["pane_id"], "-o", f"cat >> '{logfile}'")

    def _install_hooks(self) -> None:
        helper = self._logs_dir / ".oplogger_hook.sh"
        helper.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            DIR="{self._logs_dir}"
            WIN=$(tmux display-message -p '#{{window_index}}')
            PAN=$(tmux display-message -p '#{{pane_index}}')
            PID=$(tmux display-message -p '#{{pane_id}}')
            CWD=$(tmux display-message -p '#{{pane_current_path}}')
            TS=$(date +%Y%m%d_%H%M%S)
            LOG="$DIR/pane_w${{WIN}}_p${{PAN}}_${{TS}}.log"
            cat > "$LOG" <<HDR
            ===OPLOGGER_PANE_START===
            pane_id: $PID
            window: $WIN
            pane: $PAN
            started: $(date -Iseconds)
            cwd: $CWD
            ===OPLOGGER_PANE_HEADER_END===
            HDR
            tmux pipe-pane -o "cat >> '$LOG'"
        """))
        helper.chmod(0o755)

        for event in ("after-split-window", "after-new-window"):
            _tmux("set-hook", "-t", self._session, event, f"run-shell '{helper}'")


class _LineBuffer:
    """Accumulate PTY output, strip escapes, render \\r and \\b like a terminal.

    A real terminal treats \\r as "move cursor to column 0" (overwrite) and
    \\b as "move cursor back one column". Shells like zsh redraw the line
    after every keystroke using \\r + rewrite. If we just strip escapes and
    concatenate bytes we get duplicated characters. This class simulates the
    overwrite behavior so the log file matches what the user sees on screen.
    """

    def __init__(self) -> None:
        self._line: list[str] = []   # current line as list of chars
        self._col: int = 0           # cursor position in _line

    def feed(self, raw: bytes) -> list[bytes]:
        """Feed raw PTY bytes. Returns a list of complete rendered lines."""
        # Strip ANSI escape sequences first.
        cleaned = _ANSI_BYTES.sub(b"", raw)
        text = cleaned.decode("utf-8", errors="replace")

        finished: list[bytes] = []

        for ch in text:
            if ch == "\n":
                # Emit the rendered line.
                rendered = "".join(self._line).rstrip() + "\n"
                finished.append(rendered.encode("utf-8"))
                self._line.clear()
                self._col = 0
            elif ch == "\r":
                # Carriage return — cursor back to column 0 (don't clear).
                self._col = 0
            elif ch == "\b":
                # Backspace — move cursor left.
                if self._col > 0:
                    self._col -= 1
            elif ch in ("\x00", "\x07", "\x0e", "\x0f"):
                # Ignore control chars.
                pass
            else:
                # Normal character — write at cursor, advance.
                if self._col < len(self._line):
                    self._line[self._col] = ch
                else:
                    # Pad if cursor jumped ahead (shouldn't normally happen).
                    while len(self._line) < self._col:
                        self._line.append(" ")
                    self._line.append(ch)
                self._col += 1

        return finished

    def flush(self) -> bytes:
        """Flush any remaining partial line."""
        if self._line:
            rendered = "".join(self._line).rstrip()
            self._line.clear()
            self._col = 0
            if rendered:
                return (rendered + "\n").encode("utf-8")
        return b""


def _copy_winsize(src_fd: int, dst_fd: int) -> None:
    """Copy terminal dimensions from one fd to another."""
    try:
        buf = fcntl.ioctl(src_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(dst_fd, termios.TIOCSWINSZ, buf)
    except OSError:
        pass


def _write_header(path: Path, meta: dict[str, str]) -> None:
    lines = ["===OPLOGGER_PANE_START==="]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("===OPLOGGER_PANE_HEADER_END===")
    path.write_text("\n".join(lines) + "\n")


def _tmux(*args: str) -> None:
    try:
        subprocess.run(["tmux", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass
