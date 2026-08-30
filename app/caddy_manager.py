from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Lock
from typing import Callable

Validator = Callable[[Path], None]
Reloader = Callable[[Path], None]

def command_validator(path: Path) -> None:
    subprocess.run(["caddy","validate","--config",str(path)],check=True,capture_output=True,text=True,timeout=15)

def command_reloader(path: Path) -> None:
    subprocess.run(["caddy","reload","--config",str(path),"--address","unix//run/wise-route-manager/caddy-admin.sock"],check=True,capture_output=True,text=True,timeout=15)

class CaddyConfigManager:
    def __init__(self,path:Path,validator:Validator=command_validator,reloader:Reloader=command_reloader): self.path=path; self.validator=validator; self.reloader=reloader; self._lock=Lock()
    def _atomic(self,payload:bytes) -> None:
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700); fd,temporary=tempfile.mkstemp(prefix=".caddy.",dir=self.path.parent)
        try:
            with os.fdopen(fd,"wb") as handle: handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.chmod(temporary,0o600); os.replace(temporary,self.path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    def apply(self,config:dict) -> dict[str,str|bool]:
        candidate=json.dumps(config,sort_keys=True,separators=(",",":")).encode()+b"\n"
        with self._lock:
            before=self.path.read_bytes() if self.path.exists() else None
            fd,temp=tempfile.mkstemp(prefix="caddy-candidate-",suffix=".json",dir=self.path.parent)
            try:
                with os.fdopen(fd,"wb") as handle: handle.write(candidate)
                candidate_path=Path(temp); self.validator(candidate_path); self._atomic(candidate); self.reloader(self.path)
            except Exception:
                if before is None:
                    try: self.path.unlink()
                    except FileNotFoundError: pass
                else: self._atomic(before)
                raise
            finally:
                try: os.unlink(temp)
                except FileNotFoundError: pass
        return {"existed":before is not None,"before":base64.b64encode(before or b"").decode()}
    def rollback(self,state:dict[str,str|bool]) -> None:
        with self._lock:
            if state.get("existed"): self._atomic(base64.b64decode(str(state["before"])))
            else:
                try: self.path.unlink()
                except FileNotFoundError: pass
            if self.path.exists(): self.validator(self.path); self.reloader(self.path)
