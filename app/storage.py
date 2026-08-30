from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import Lock
from typing import Any


class JsonStore:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.routes_path = config_dir / "routes.json"
        self.audit_path = config_dir / "audit.jsonl"
        self.backups_dir = config_dir / "backups"
        self._lock = Lock()
        config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backups_dir.mkdir(exist_ok=True, mode=0o700)

    @staticmethod
    def _atomic_json(path: Path, value: Any) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load_routes(self) -> list[dict[str, Any]]:
        if not self.routes_path.exists():
            return []
        try:
            with self.routes_path.open(encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, list): raise ValueError("routes root is not an array")
            return value
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            recovered = self._recover_routes()
            if recovered is None:
                raise RuntimeError("routes.json is corrupt and no valid backup is available") from None
            return recovered

    def _recover_routes(self) -> list[dict[str, Any]] | None:
        for backup in sorted(self.backups_dir.glob("routes-*.json"), reverse=True):
            try:
                value = json.loads(backup.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(value, list): continue
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            quarantine = self.config_dir / f"routes.corrupt-{stamp}.json"
            os.replace(self.routes_path, quarantine)
            quarantine.chmod(0o600)
            self._atomic_json(self.routes_path, value)
            self.audit({"event":"routes.recovered","backup":backup.name,"quarantine":quarantine.name})
            return value
        return None

    def save_routes(self, routes: list[dict[str, Any]]) -> None:
        with self._lock:
            if self.routes_path.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                backup = self.backups_dir / f"routes-{stamp}.json"
                backup.write_bytes(self.routes_path.read_bytes())
                backup.chmod(0o600)
            self._atomic_json(self.routes_path, routes)

    def audit(self, event: dict[str, Any]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        with self._lock:
            fd = os.open(self.audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
