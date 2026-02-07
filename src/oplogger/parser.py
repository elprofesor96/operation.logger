"""Parse raw logs and emit Markdown reports."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from oplogger import console as ui
from oplogger.config import load_tools

# ---------------------------------------------------------------------------
#  Patterns
# ---------------------------------------------------------------------------

_ANSI = re.compile(
    r"\x1b(?:"
    r"\[[0-9;?]*[a-zA-Z]"          # CSI sequences (colors, cursor, ?2004h, etc.)
    r"|\[[0-9;?]*[ -/]*[a-zA-Z]"   # CSI with intermediate bytes
    r"|\][^\x07]*\x07"              # OSC terminated by BEL
    r"|\][^\x1b]*\x1b\\"           # OSC terminated by ST
    r"|\([0-9A-Za-z]"              # charset selection
    r"|[=>78]"                      # DECKPAM, DECKPNM, save/restore cursor
    r")"
)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_PROMPTS: list[re.Pattern[str]] = [
    re.compile(r"^[\w.-]+@[\w.-]+:[^\$#]*[\$#]\s"),
    re.compile(r"^\[[\w.-]+@[\w.-]+\s[^\]]*\][\$#]\s"),
    re.compile(r"^[\$#]\s"),
    re.compile(r"^\([\w.-]+\)\s*[\w.-]+@[\w.-]+:[^\$#]*[\$#]\s"),
    re.compile(r"^.*[\$#]\s(?=\S)"),
    re.compile(r"^└─[\$#]\s"),
    re.compile(r"^❯\s"),
    re.compile(r"^➜\s+\S"),
    re.compile(r"^>>>\s"),
]

# Loaded once per parse run from ~/.oplogger/oplogger.conf
TOOLS: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _render_line(raw: str) -> str:
    """Strip ANSI escapes and simulate \\r / \\b like a real terminal.

    tmux pipe-pane captures raw bytes including shell line-editor redraws.
    Just stripping escapes causes duplicated characters (e.g. 'ooplogger').
    This renders carriage returns and backspaces properly.
    """
    stripped = _ANSI.sub("", raw)
    buf: list[str] = []
    col = 0

    for ch in stripped:
        if ch == "\r":
            col = 0
        elif ch == "\b":
            if col > 0:
                col -= 1
        elif _CTRL.match(ch):
            pass
        else:
            if col < len(buf):
                buf[col] = ch
            else:
                while len(buf) < col:
                    buf.append(" ")
                buf.append(ch)
            col += 1

    return "".join(buf).rstrip()


def _is_prompt(line: str) -> bool:
    return any(p.search(line) for p in _PROMPTS)


def _extract_cmd(line: str) -> str:
    for p in _PROMPTS:
        m = p.search(line)
        if m:
            return line[m.end():].strip()
    return line.strip()


def _cmd_base(cmd: str) -> str:
    parts = cmd.split()
    if not parts:
        return ""
    tok = parts[0]
    if tok == "sudo" and len(parts) > 1:
        tok = parts[1]
    return os.path.basename(tok)


def _lang_hint(cmd: str, output: str) -> str:
    s = output.strip()
    if s.startswith("{") or s.startswith("["):
        return "json"
    if s.startswith("<?xml") or s.startswith("<"):
        return "xml"
    return {"curl": "http", "python": "python", "python3": "python", "jq": "json"}.get(cmd, "")


# ---------------------------------------------------------------------------
#  Data
# ---------------------------------------------------------------------------


class Block:
    __slots__ = ("command", "output", "is_tool")

    def __init__(self, command: str | None, output: str, is_tool: bool) -> None:
        self.command = command
        self.output = output
        self.is_tool = is_tool


class PaneLog:
    __slots__ = ("path", "meta", "blocks")

    def __init__(self, path: Path, meta: dict[str, str], blocks: list[Block]) -> None:
        self.path = path
        self.meta = meta
        self.blocks = blocks

    @property
    def label(self) -> str:
        w, p = self.meta.get("window"), self.meta.get("pane")
        if w is not None and p is not None:
            return f"Window {w} — Pane {p}"
        stem = self.path.stem.replace("_", " ").title()
        return "Terminal Session" if stem.startswith("Terminal") else stem


# ---------------------------------------------------------------------------
#  Parsing
# ---------------------------------------------------------------------------


def _parse_header(lines: list[str]) -> tuple[dict[str, str], int]:
    meta: dict[str, str] = {}
    inside = False
    end = 0
    for i, raw in enumerate(lines):
        if "===OPLOGGER_PANE_START===" in raw:
            inside = True
            continue
        if "===OPLOGGER_PANE_HEADER_END===" in raw:
            end = i + 1
            break
        if inside and ":" in raw:
            k, _, v = raw.partition(":")
            meta[k.strip()] = v.strip()
    return meta, end


def _parse_file(path: Path, tools: frozenset[str]) -> PaneLog:
    raw = path.read_text(errors="replace").splitlines()
    meta, offset = _parse_header(raw)
    lines = [_render_line(l) for l in raw[offset:]]

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    blocks: list[Block] = []
    cur_cmd: str | None = None
    cur_out: list[str] = []

    def flush() -> None:
        nonlocal cur_cmd, cur_out
        if cur_cmd is not None:
            blocks.append(Block(cur_cmd, "\n".join(cur_out).rstrip(), _cmd_base(cur_cmd) in tools))
        elif cur_out:
            blocks.append(Block(None, "\n".join(cur_out).rstrip(), False))
        cur_cmd = None
        cur_out = []

    for line in lines:
        if _is_prompt(line):
            flush()
            cur_cmd = _extract_cmd(line)
            cur_out = []
        else:
            cur_out.append(line)

    flush()
    return PaneLog(path, meta, blocks)


# ---------------------------------------------------------------------------
#  Markdown
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", text.lower()))


def _render_full(logs: list[PaneLog]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    o: list[str] = []
    w = o.append

    w(f"# Session Log\n")
    w(f"> Generated by **oplogger** on {now}\n")

    # TOC
    w("## Table of Contents\n")
    for p in logs:
        n = sum(1 for b in p.blocks if b.command)
        w(f"- [{p.label}](#{_slug(p.label)}) — {n} commands")
    w("")

    # Summary
    total = sum(sum(1 for b in p.blocks if b.command) for p in logs)
    tools = sum(sum(1 for b in p.blocks if b.is_tool) for p in logs)
    unique = sorted({_cmd_base(b.command) for p in logs for b in p.blocks if b.is_tool and b.command})

    w("## Summary\n")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Panes / Sessions | {len(logs)} |")
    w(f"| Total Commands | {total} |")
    w(f"| Tool Invocations | {tools} |")
    if unique:
        w(f"| Tools | {' · '.join(f'`{t}`' for t in unique)} |")
    w("")
    w("---\n")

    # Per pane
    for p in logs:
        w(f"## {p.label}\n")
        if p.meta.get("started"):
            w(f"> **Started:** {p.meta['started']}  ")
        if p.meta.get("cwd"):
            w(f"> **CWD:** `{p.meta['cwd']}`  ")
        w("")

        if not p.blocks:
            w("_No commands recorded._\n")
            continue

        for b in p.blocks:
            if b.command is None:
                if b.output.strip():
                    w(f"```\n{b.output}\n```\n")
                continue

            trunc = b.command if len(b.command) <= 120 else b.command[:117] + "..."
            marker = "🔴" if b.is_tool else "▸"
            w(f"### {marker} `{trunc}`\n")

            if len(b.command) > 120:
                w(f"```bash\n{b.command}\n```\n")

            if b.output.strip():
                out_lines = b.output.split("\n")
                n = len(out_lines)
                body = b.output
                if n > 200:
                    head = "\n".join(out_lines[:100])
                    tail = "\n".join(out_lines[-50:])
                    body = f"{head}\n\n... [{n - 150} lines omitted] ...\n\n{tail}"

                hint = _lang_hint(_cmd_base(b.command), b.output)
                w("<details>")
                w(f"<summary>Output ({n} lines)</summary>\n")
                w(f"```{hint}\n{body}\n```\n")
                w("</details>\n")
            else:
                w("_No output._\n")

        w("---\n")

    return "\n".join(o)


def _render_commands(logs: list[PaneLog]) -> str:
    o: list[str] = ["# Commands\n"]
    for p in logs:
        o.append(f"## {p.label}\n")
        for b in p.blocks:
            if b.command:
                m = "🔴" if b.is_tool else "-"
                o.append(f"{m} `{b.command}`")
        o.append("")
    return "\n".join(o)


# ---------------------------------------------------------------------------
#  Public
# ---------------------------------------------------------------------------


class LogParser:
    def __init__(self, logs_dir: Path) -> None:
        self._dir = logs_dir

    def run(self, *, output_path: Path | None = None) -> None:
        files = sorted(self._dir.glob("*.log"))
        if not files:
            ui.warn("No log files found.")
            return

        tools = load_tools()
        parsed: list[PaneLog] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=ui.console,
        ) as progress:
            task = progress.add_task("Parsing", total=len(files))
            for f in files:
                progress.update(task, description=f"[bold]{f.name}[/]")
                try:
                    parsed.append(_parse_file(f, tools))
                except Exception as exc:
                    ui.warn(f"{f.name}: {exc}")
                progress.advance(task)

        if not parsed:
            ui.error("No logs could be parsed.")
            return

        md = output_path or self._dir / "session_log.md"
        md.write_text(_render_full(parsed))
        ui.info(f"Report   → [bold]{md}[/]")

        cmd = self._dir / "commands_only.md"
        cmd.write_text(_render_commands(parsed))
        ui.info(f"Commands → [bold]{cmd}[/]")
