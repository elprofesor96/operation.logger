"""Tests for oplogger."""

from __future__ import annotations

import textwrap
from pathlib import Path

from oplogger.config import load_tools
from oplogger.parser import (
    LogParser,
    _cmd_base,
    _extract_cmd,
    _is_prompt,
    _render_line,
)


# ---- line rendering ---- #


class TestRenderLine:
    def test_ansi(self) -> None:
        assert _render_line("\x1b[31mhello\x1b[0m") == "hello"

    def test_control(self) -> None:
        assert _render_line("abc\x07def") == "abcdef"

    def test_passthrough(self) -> None:
        assert _render_line("normal text") == "normal text"

    def test_carriage_return_overwrite(self) -> None:
        # zsh line editor: prompt + partial, \r, prompt + more
        assert _render_line("$ e\r$ oplogger stop") == "$ oplogger stop"

    def test_backspace(self) -> None:
        assert _render_line("helloo\b \bp") == "hellop"

    def test_bracketed_paste(self) -> None:
        assert _render_line("\x1b[?2004hwhoami\x1b[?2004l") == "whoami"


class TestPrompts:
    def test_user_at_host(self) -> None:
        assert _is_prompt("user@host:~/dir$ nmap 10.0.0.1")

    def test_root(self) -> None:
        assert _is_prompt("root@box:/tmp# id")

    def test_bare_dollar(self) -> None:
        assert _is_prompt("$ whoami")

    def test_not_prompt(self) -> None:
        assert not _is_prompt("Starting Nmap 7.94")
        assert not _is_prompt("")


class TestExtraction:
    def test_standard(self) -> None:
        assert _extract_cmd("user@host:~$ nmap -sV 10.0.0.1") == "nmap -sV 10.0.0.1"

    def test_base_sudo(self) -> None:
        assert _cmd_base("sudo nmap -sS 10.0.0.1") == "nmap"

    def test_base_path(self) -> None:
        assert _cmd_base("/usr/bin/nmap -sV 10.0.0.1") == "nmap"


class TestTools:
    def test_known(self) -> None:
        tools = load_tools()
        for t in ("nmap", "ffuf", "sqlmap", "nuclei"):
            assert t in tools

    def test_not_tools(self) -> None:
        tools = load_tools()
        for t in ("ls", "cd", "cat"):
            assert t not in tools


class TestRoundtrip:
    def test_parse_and_render(self, tmp_path: Path) -> None:
        logs = tmp_path / "oplogs"
        logs.mkdir()

        (logs / "pane_w0_p0_test.log").write_text(textwrap.dedent("""\
            ===OPLOGGER_PANE_START===
            window: 0
            pane: 0
            started: 2025-02-06T10:00:00+00:00
            cwd: /home/user/targets
            ===OPLOGGER_PANE_HEADER_END===
            user@kali:~/targets$ nmap -sC -sV 10.10.10.1
            Starting Nmap 7.94
            22/tcp open ssh
            user@kali:~/targets$ ls
            notes
        """))

        LogParser(logs).run()

        report = logs / "session_log.md"
        assert report.exists()
        content = report.read_text()
        assert "🔴" in content
        assert "▸" in content

    def test_empty(self, tmp_path: Path) -> None:
        logs = tmp_path / "oplogs"
        logs.mkdir()
        LogParser(logs).run()
        assert not (logs / "session_log.md").exists()
