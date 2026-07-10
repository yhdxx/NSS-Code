from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4


class JsonRunJournal:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = Lock()

    def save(self, record: dict[str, Any]) -> str:
        run_id = str(record.get("run_id") or uuid4().hex)
        payload = {**record, "run_id": run_id}
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / f"{run_id}.json"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            (self.root / "latest").write_text(run_id, encoding="utf-8")
        return run_id

    def latest(self) -> dict[str, Any] | None:
        marker = self.root / "latest"
        if not marker.exists():
            return None
        return self.get(marker.read_text(encoding="utf-8").strip())

    def get(self, run_id: str) -> dict[str, Any] | None:
        if not run_id or "/" in run_id or "\\" in run_id:
            return None
        target = self.root / f"{run_id}.json"
        if not target.exists():
            return None
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None
