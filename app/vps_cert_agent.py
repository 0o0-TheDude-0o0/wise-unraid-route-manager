from __future__ import annotations

import argparse
import base64
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import ssl
from threading import Lock
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from .certificate_sync import validate_bundle


MAX_REQUESTS_PER_MINUTE = 10


def _pem_certificate(raw: bytes) -> bytes:
    if b"-----BEGIN CERTIFICATE-----" in raw:
        return raw
    return x509.load_der_x509_certificate(raw).public_bytes(serialization.Encoding.PEM)


def _pem_key(raw: bytes) -> bytes:
    if b"-----BEGIN" in raw:
        return raw
    key=serialization.load_der_private_key(raw,password=None)
    return key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())


def _certificate_sets(value: Any):
    if isinstance(value,dict):
        certificates=value.get("Certificates")
        if isinstance(certificates,list):
            yield from (item for item in certificates if isinstance(item,dict))
        for child in value.values():
            yield from _certificate_sets(child)
    elif isinstance(value,list):
        for child in value: yield from _certificate_sets(child)


def extract_bundle(acme_path: Path, requested_name: str):
    try: value=json.loads(acme_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError,UnicodeDecodeError) as exc: raise RuntimeError("Traefik ACME storage could not be read") from exc
    for item in _certificate_sets(value):
        domain=item.get("domain") if isinstance(item.get("domain"),dict) else {}
        names=[str(domain.get("main","")).lower(),*[str(name).lower() for name in domain.get("sans",[]) if name]]
        if requested_name.lower() not in names: continue
        try:
            cert=_pem_certificate(base64.b64decode(str(item["certificate"]),validate=True))
            key=_pem_key(base64.b64decode(str(item["key"]),validate=True))
        except (KeyError,ValueError,TypeError) as exc: raise RuntimeError("matching Traefik certificate entry is invalid") from exc
        return validate_bundle(cert,key,requested_name)
    raise RuntimeError("requested certificate is not present in Traefik ACME storage")


class RateLimiter:
    def __init__(self,limit: int=MAX_REQUESTS_PER_MINUTE): self.limit=limit; self.events: dict[str,deque[float]]={}; self.lock=Lock()
    def allow(self,identity: str,now: float | None=None) -> bool:
        moment=time.monotonic() if now is None else now
        with self.lock:
            events=self.events.setdefault(identity,deque())
            while events and events[0]<=moment-60: events.popleft()
            if len(events)>=self.limit: return False
            events.append(moment); return True


class AgentApplication:
    def __init__(self,acme_path: Path,token_path: Path,allowed_names: set[str]):
        self.acme_path=acme_path; self.token_path=token_path; self.allowed_names={name.lower().rstrip(".") for name in allowed_names}; self.rate=RateLimiter()
        if not self.allowed_names: raise RuntimeError("at least one allowed certificate name is required")
        if token_path.stat().st_mode & 0o077: raise RuntimeError("certificate agent token permissions must be 0600")
        self.token=token_path.read_text(encoding="utf-8").strip()
        if len(self.token)<32: raise RuntimeError("certificate agent token must contain at least 32 characters")
    def handler(self):
        application=self
        class Handler(BaseHTTPRequestHandler):
            server_version="WiseCertificateAgent/0.1"
            def log_message(self,format: str,*args: Any) -> None: pass
            def reply(self,status: int,value: dict[str,Any]) -> None:
                payload=json.dumps(value,separators=(",",":")).encode(); self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Pragma","no-cache"); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Content-Length",str(len(payload))); self.end_headers(); self.wfile.write(payload)
            def do_GET(self) -> None:
                parsed=urlsplit(self.path)
                if parsed.path=="/healthz": self.reply(HTTPStatus.OK,{"status":"ok"}); return
                if parsed.path!="/v1/certificate": self.reply(HTTPStatus.NOT_FOUND,{"error":"not found"}); return
                if not application.rate.allow(self.client_address[0]): self.reply(HTTPStatus.TOO_MANY_REQUESTS,{"error":"rate limit exceeded"}); return
                supplied=self.headers.get("Authorization",""); supplied=supplied[7:] if supplied.startswith("Bearer ") else ""
                if not supplied or not secrets.compare_digest(supplied,application.token): self.reply(HTTPStatus.UNAUTHORIZED,{"error":"authentication required"}); return
                requested=str(parse_qs(parsed.query).get("name",[""])[0]).lower().rstrip(".")
                if requested not in application.allowed_names: self.reply(HTTPStatus.FORBIDDEN,{"error":"certificate name is not allowed"}); return
                try: bundle=extract_bundle(application.acme_path,requested)
                except RuntimeError as exc: self.reply(HTTPStatus.NOT_FOUND,{"error":str(exc)}); return
                print(json.dumps({"timestamp":datetime.now(timezone.utc).isoformat(),"event":"certificate.served","name":requested,"fingerprint_sha256":bundle.fingerprint},separators=(",",":")),flush=True)
                self.reply(HTTPStatus.OK,{"certificate_pem":bundle.certificate_pem.decode(),"private_key_pem":bundle.private_key_pem.decode()})
        return Handler


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--listen",default="0.0.0.0:9443"); parser.add_argument("--acme",type=Path,default=Path("/traefik/acme.json")); parser.add_argument("--token-file",type=Path,default=Path("/run/secrets/cert-agent-token")); parser.add_argument("--allowed-name",action="append",required=True); parser.add_argument("--tls-cert",type=Path,default=Path("/run/tls/tls.crt")); parser.add_argument("--tls-key",type=Path,default=Path("/run/tls/tls.key")); args=parser.parse_args()
    host,port=args.listen.rsplit(":",1); application=AgentApplication(args.acme,args.token_file,set(args.allowed_name)); server=ThreadingHTTPServer((host,int(port)),application.handler()); context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version=ssl.TLSVersion.TLSv1_3; context.load_cert_chain(args.tls_cert,args.tls_key); server.socket=context.wrap_socket(server.socket,server_side=True); print(f"Wise certificate agent listening on {args.listen}",flush=True); server.serve_forever()


if __name__=="__main__": main()
