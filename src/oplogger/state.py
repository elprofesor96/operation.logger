"""Session state file."""

from __future__ import annotations

import json
import os
from pathlib import Path


class State:
    def __init__(self, path: Path) -> None:
        self._path = path

    @classmethod
    def default(cls) -> State:
        base = Path(os.environ.get("OPLOGGER_DIR", Path.home() / ".oplogger"))
        return cls(base / "session.json")

    @property
    def active(self) -> bool:
        return self._path.is_file()

    def save(self, data: dict) -> None:  # type: ignore[type-arg]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2) + "\n")

    def load(self) -> dict | None:  # type: ignore[type-arg]
        if not self._path.is_file():
            return None
        try:
            return json.loads(self._path.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return None

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
