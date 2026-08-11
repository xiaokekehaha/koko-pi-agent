from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class UIStateStore:
    """Best-effort persistence for project-level CLI presentation state."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path)
            if path is not None
            else Path.cwd() / ".mewcode" / "ui_state.json"
        )

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def mascot_open(self) -> bool:
        mascot = self._read().get("mascot")
        return mascot.get("open") is True if isinstance(mascot, dict) else False

    def set_mascot_open(self, is_open: bool) -> bool:
        """Persist the last explicit open/closed state without breaking the UI on I/O errors."""
        data = self._read()
        mascot = data.get("mascot")
        if not isinstance(mascot, dict):
            mascot = {}
            data["mascot"] = mascot
        mascot["open"] = bool(is_open)

        temp_path = self.path.with_name(f".{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        except OSError:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True
