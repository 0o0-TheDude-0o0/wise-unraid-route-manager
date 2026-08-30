from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from threading import Lock
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecretsStore:
    """Authenticated encrypted storage with an independently permissioned key."""
    def __init__(self, config_dir: Path, key_path: Path | None = None):
        self.key_path = key_path or config_dir / "master.key"
        self.data_path = config_dir / "integrations.enc"
        self._lock = Lock()
        self.key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key() + b"\n")
            self.key_path.chmod(0o600)
        if self.key_path.stat().st_mode & 0o077:
            raise RuntimeError("master key permissions must be 0600")
        self._fernet = Fernet(self.key_path.read_bytes().strip())

    def _load(self) -> list[dict[str, Any]]:
        if not self.data_path.exists(): return []
        try: plain = self._fernet.decrypt(self.data_path.read_bytes())
        except InvalidToken as exc: raise RuntimeError("encrypted integration store could not be authenticated") from exc
        value = json.loads(plain)
        if not isinstance(value, list): raise RuntimeError("encrypted integration store is invalid")
        return value

    def _save(self, values: list[dict[str, Any]]) -> None:
        encrypted = self._fernet.encrypt(json.dumps(values, sort_keys=True, separators=(",", ":")).encode())
        fd, temporary = tempfile.mkstemp(prefix=".integrations.", dir=self.data_path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encrypted); handle.flush(); os.fsync(handle.fileno())
            os.chmod(temporary, 0o600); os.replace(temporary, self.data_path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    @staticmethod
    def public(value: dict[str, Any]) -> dict[str, Any]:
        return {key: item for key, item in value.items() if key not in {"credential"}}

    def list_public(self) -> list[dict[str, Any]]:
        with self._lock: return [self.public(v) for v in self._load()]

    def put(self, value: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            values = [v for v in self._load() if v.get("id") != value.get("id")]
            values.append(value); self._save(values)
        return self.public(value)

    def get(self, integration_id: str) -> dict[str, Any] | None:
        with self._lock: return next((v for v in self._load() if v.get("id") == integration_id), None)

    def delete(self, integration_id: str) -> bool:
        with self._lock:
            values = self._load(); remaining = [v for v in values if v.get("id") != integration_id]
            if len(remaining) == len(values): return False
            self._save(remaining); return True
