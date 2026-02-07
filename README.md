# oplogger

Terminal session logger for pentesters, red teamers, and bug bounty hunters.

Records every command and its output across all your tmux panes and generates a Markdown report.

## Install

```bash
pip install oplogger
# or
pipx install oplogger
# or
uv tool install oplogger
```

Requires Python 3.10+ and optionally tmux.

## Usage

```bash
cd ~/targets/acme-corp
tmux new -s acme

oplogger start        # creates ./oplogs/, starts logging all panes
# ... work normally, split panes, run tools ...
oplogger stop         # stops logging, generates markdown report
```

That's it. Everything goes into `./oplogs/`:

```
oplogs/
├── pane_w0_p0_20250206_100000.log    # raw captures
├── pane_w0_p1_20250206_100000.log
├── pane_w1_p0_20250206_100530.log
├── session_log.md                     # full report
└── commands_only.md                   # just the commands
```

### Commands

```
oplogger start          Start logging (auto-detects tmux vs plain terminal)
oplogger stop           Stop logging, generate report
oplogger status         Show active session info
oplogger parse [dir]    Re-generate report from existing logs
```

### Without tmux

Works in a plain terminal too — spawns a PTY to capture the session. You just won't get multi-pane logging.

## Configuration

On first run, oplogger creates `~/.oplogger/oplogger.conf` with the default list of highlighted security tools. Edit this file to add or remove tools:

```
# ~/.oplogger/oplogger.conf
nmap
ffuf
sqlmap
my-custom-tool
```

## How it works

In tmux, `oplogger` attaches `pipe-pane` to every existing pane and sets hooks (`after-split-window`, `after-new-window`) so new panes are auto-logged. On `oplogger stop`, raw captures are parsed: ANSI codes stripped, shell prompts detected to split into command→output blocks, security tools highlighted, and the result rendered to Markdown.

## Report format

- Security tool commands (nmap, ffuf, sqlmap, etc.) marked with 🔴
- Regular commands marked with ▸
- Command output in collapsible `<details>` blocks
- Long outputs truncated (first 100 + last 50 lines)
- Summary table with tool invocations count
- Separate `commands_only.md` for copy-pasting into reports

## Development

```bash
git clone https://github.com/yourusername/oplogger.git
cd oplogger
pip install -e ".[dev]"
pytest
```

## License

MIT
