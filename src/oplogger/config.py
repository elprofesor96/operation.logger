"""Configuration — tools list from ~/.oplogger/oplogger.conf"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_TOOLS: list[str] = [
    # recon & scanning
    "nmap",
    "masscan",
    "rustscan",
    "nikto",
    "gobuster",
    "dirb",
    "dirsearch",
    "ffuf",
    "wfuzz",
    "feroxbuster",
    # web
    "sqlmap",
    "nuclei",
    "httpx",
    "whatweb",
    "wafw00f",
    # osint & subdomains
    "subfinder",
    "amass",
    "assetfinder",
    "waybackurls",
    "gau",
    # networking
    "curl",
    "wget",
    "ssh",
    "netcat",
    "nc",
    "ncat",
    "socat",
    # exploitation
    "msfconsole",
    "msfvenom",
    # cracking
    "hashcat",
    "john",
    "hydra",
    "medusa",
    "crackmapexec",
    "netexec",
    # AD / post-exploitation
    "bloodhound",
    "sharphound",
    "mimikatz",
    "rubeus",
    "certipy",
    # scripting
    "python",
    "python3",
    "ruby",
    "perl",
    "php",
    # dns
    "searchsploit",
    "dig",
    "host",
    "nslookup",
    "whois",
    "dnsrecon",
    # smb / ldap / enum
    "enum4linux",
    "smbclient",
    "rpcclient",
    "ldapsearch",
    # traffic
    "tcpdump",
    "tshark",
    "responder",
    # tunneling
    "chisel",
    "ligolo",
    "proxychains",
    # impacket
    "impacket-smbexec",
    "impacket-wmiexec",
    "impacket-psexec",
    "impacket-secretsdump",
    "impacket-getTGT",
    "impacket-GetNPUsers",
    # file transfer
    "scp",
    "rsync",
    "openssl",
    "testssl.sh",
    "certutil",
    # remote access
    "powershell",
    "evil-winrm",
    "xfreerdp",
    "rdesktop",
    "cme",
    # misc
    "kerbrute",
    "gopherus",
    "arjun",
    "paramspider",
]


def _conf_path() -> Path:
    base = Path(os.environ.get("OPLOGGER_DIR", Path.home() / ".oplogger"))
    return base / "oplogger.conf"


def load_tools() -> frozenset[str]:
    """Load tools from config file. Creates default config on first run."""
    conf = _conf_path()

    if not conf.is_file():
        _write_default(conf)

    tools: list[str] = []
    for raw in conf.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            tools.append(line)

    return frozenset(tools) if tools else frozenset(_DEFAULT_TOOLS)


def _write_default(conf: Path) -> None:
    """Write the default config file."""
    conf.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# oplogger — highlighted security tools",
        "# One tool name per line. Lines starting with # are ignored.",
        "# Add your own tools below or remove ones you don't use.",
        "",
    ]
    lines.extend(_DEFAULT_TOOLS)
    lines.append("")

    conf.write_text("\n".join(lines))
