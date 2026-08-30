from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import tempfile
from threading import Lock
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization

from .models import ValidationError


MAX_CERT_RESPONSE = 256 * 1024


def _covers(pattern: str, expected: str) -> bool:
    pattern=pattern.lower().rstrip("."); expected=expected.lower().rstrip(".")
    if expected.startswith("*."):
        return pattern == expected
    if pattern == expected:
        return True
    return pattern.startswith("*.") and expected.endswith(pattern[1:]) and expected.count(".") == pattern.count(".")


@dataclass(frozen=True)
class CertificateBundle:
    certificate_pem: bytes
    private_key_pem: bytes
    common_name: str
    names: tuple[str, ...]
    not_before: str
    not_after: str
    fingerprint: str

    def public(self) -> dict[str, Any]:
        return {"common_name":self.common_name,"names":list(self.names),"not_before":self.not_before,"not_after":self.not_after,"fingerprint_sha256":self.fingerprint}


def validate_bundle(certificate_pem: bytes, private_key_pem: bytes, expected_name: str, *, now: datetime | None = None) -> CertificateBundle:
    try:
        cert=x509.load_pem_x509_certificate(certificate_pem)
        key=serialization.load_pem_private_key(private_key_pem,password=None)
    except (ValueError,TypeError) as exc: raise ValidationError("certificate endpoint returned invalid PEM material") from exc
    cert_public=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    key_public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    if not secrets.compare_digest(cert_public,key_public): raise ValidationError("certificate and private key do not match")
    current=now or datetime.now(timezone.utc); before=cert.not_valid_before_utc; after=cert.not_valid_after_utc
    if before > current: raise ValidationError("certificate is not valid yet")
    if after <= current+timedelta(days=7): raise ValidationError("certificate expires in seven days or less")
    try: names=tuple(str(name).lower() for name in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName))
    except x509.ExtensionNotFound: names=()
    common=cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    common_name=str(common[0].value).lower() if common else ""
    candidates=names or ((common_name,) if common_name else ())
    if not any(_covers(name,expected_name) for name in candidates): raise ValidationError(f"certificate does not cover {expected_name}")
    fingerprint=cert.fingerprint(hashes.SHA256()).hex()
    return CertificateBundle(certificate_pem,private_key_pem,common_name,names,before.isoformat(),after.isoformat(),fingerprint)


class CertificateSyncClient:
    def __init__(self,endpoint: str,token: str,*,timeout: float=10): self.endpoint=endpoint; self.token=token; self.timeout=timeout
    def fetch(self,expected_name: str) -> CertificateBundle:
        url=self.endpoint+("&" if "?" in self.endpoint else "?")+urlencode({"name":expected_name})
        request=Request(url,headers={"Authorization":f"Bearer {self.token}","Accept":"application/json","User-Agent":"WiseRouteManager/0.1"})
        try:
            with urlopen(request,timeout=self.timeout,context=ssl.create_default_context()) as response:
                length=int(response.headers.get("Content-Length","0") or 0)
                if length>MAX_CERT_RESPONSE: raise ValidationError("certificate response is too large")
                payload=response.read(MAX_CERT_RESPONSE+1)
                if len(payload)>MAX_CERT_RESPONSE: raise ValidationError("certificate response is too large")
                value=json.loads(payload)
        except HTTPError as exc:
            try: exc.close()
            finally: raise RuntimeError(f"certificate endpoint rejected the request (HTTP {exc.code})") from exc
        except (URLError,TimeoutError) as exc: raise RuntimeError("certificate endpoint could not be reached through Newt") from exc
        except (json.JSONDecodeError,UnicodeDecodeError) as exc: raise RuntimeError("certificate endpoint returned invalid JSON") from exc
        if not isinstance(value,dict): raise RuntimeError("certificate endpoint response must be an object")
        return validate_bundle(str(value.get("certificate_pem","")).encode(),str(value.get("private_key_pem","")).encode(),expected_name)


Validator=Callable[[Path],None]
Reloader=Callable[[Path],None]
def _validate_caddy(config: Path) -> None: subprocess.run(["caddy","validate","--config",str(config)],check=True,capture_output=True,text=True,timeout=15)
def _reload_caddy(config: Path) -> None: subprocess.run(["caddy","reload","--config",str(config),"--address","unix//run/wise-route-manager/caddy-admin.sock"],check=True,capture_output=True,text=True,timeout=15)


class CertificateInstaller:
    def __init__(self,tls_dir: Path,caddy_config: Path,*,validator: Validator=_validate_caddy,reloader: Reloader=_reload_caddy): self.tls_dir=tls_dir; self.caddy_config=caddy_config; self.validator=validator; self.reloader=reloader; self._lock=Lock()
    @staticmethod
    def _atomic(path: Path,payload: bytes) -> None:
        fd,temp=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
        try:
            with os.fdopen(fd,"wb") as handle: handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.chmod(temp,0o600); os.replace(temp,path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    def install(self,bundle: CertificateBundle) -> dict[str, Any]:
        self.tls_dir.mkdir(parents=True,exist_ok=True,mode=0o700); cert_path=self.tls_dir/"tls.crt"; key_path=self.tls_dir/"tls.key"
        with self._lock:
            old_cert=cert_path.read_bytes() if cert_path.exists() else None; old_key=key_path.read_bytes() if key_path.exists() else None
            try:
                self._atomic(cert_path,bundle.certificate_pem); self._atomic(key_path,bundle.private_key_pem)
                self.validator(self.caddy_config); self.reloader(self.caddy_config)
            except Exception:
                if old_cert is None: cert_path.unlink(missing_ok=True)
                else: self._atomic(cert_path,old_cert)
                if old_key is None: key_path.unlink(missing_ok=True)
                else: self._atomic(key_path,old_key)
                if old_cert is not None and old_key is not None:
                    try: self.validator(self.caddy_config); self.reloader(self.caddy_config)
                    except Exception: pass
                raise
        return {"status":"installed","fingerprint_sha256":bundle.fingerprint,"not_after":bundle.not_after}


@dataclass(frozen=True)
class CertificatePlan:
    plan_id: str
    confirmation_token: str
    expires_at: datetime
    bundle: CertificateBundle


class CertificatePlanStore:
    def __init__(self): self._plans: dict[str,CertificatePlan]={}; self._lock=Lock()
    def create(self,bundle: CertificateBundle) -> CertificatePlan:
        plan=CertificatePlan(secrets.token_urlsafe(18),secrets.token_urlsafe(32),datetime.now(timezone.utc)+timedelta(minutes=10),bundle)
        with self._lock: self._plans[plan.plan_id]=plan
        return plan
    def consume(self,plan_id: str,token: str) -> CertificateBundle:
        with self._lock: plan=self._plans.pop(plan_id,None)
        if plan is None or not secrets.compare_digest(plan.confirmation_token,token): raise ValidationError("certificate approval is invalid or already used")
        if plan.expires_at<datetime.now(timezone.utc): raise ValidationError("certificate approval has expired")
        return plan.bundle


def installed_certificate(path: Path) -> dict[str, Any] | None:
    if not path.exists(): return None
    try: cert=x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError,ValueError): return {"status":"invalid"}
    try: names=[str(name).lower() for name in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)]
    except x509.ExtensionNotFound: names=[]
    return {"status":"installed","names":names,"not_after":cert.not_valid_after_utc.isoformat(),"fingerprint_sha256":cert.fingerprint(hashes.SHA256()).hex()}


def renewal_comparison(installed: dict[str, Any] | None, candidate: CertificateBundle) -> dict[str, Any]:
    available=installed is None or installed.get("status")!="installed" or (installed.get("fingerprint_sha256")!=candidate.fingerprint and datetime.fromisoformat(str(installed["not_after"]))<datetime.fromisoformat(candidate.not_after))
    return {"status":"update_available" if available else "current","installed":installed,"candidate":candidate.public(),"update_available":available}
