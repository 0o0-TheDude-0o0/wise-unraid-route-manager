from __future__ import annotations

import base64
import ipaddress
import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .models import ValidationError

PROVIDERS = {
    "technitium": {"name": "Technitium DNS", "credential_label": "Restricted API token", "automatic_token": True},
    "pihole": {"name": "Pi-hole v6", "credential_label": "Application password", "automatic_token": False},
    "adguard": {"name": "AdGuard Home", "credential_label": "Dedicated password", "automatic_token": False},
}

def validate_local_url(value: str, *, allow_http: bool = True) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ({"http", "https"} if allow_http else {"https"}) or not parsed.hostname:
        raise ValidationError("provider URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError("provider URL must not contain credentials, a query, or a fragment")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname not in {"localhost"} and not parsed.hostname.endswith((".local", ".lan", ".internal")):
            raise ValidationError("use a private IP or local DNS name for the DNS provider") from None
    else:
        if not (address.is_private or address.is_loopback or address.is_link_local):
            raise ValidationError("DNS provider must use a private or local address")
    return value.strip().rstrip("/")

class IntegrationError(RuntimeError): pass

class IntegrationTester:
    def __init__(self, timeout: float = 5, verify_tls: bool = True):
        self.timeout = timeout
        self.context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()

    def _json(self, request: Request) -> tuple[int, dict[str, Any]]:
        try:
            with urlopen(request, timeout=self.timeout, context=self.context) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            raise IntegrationError(f"authentication failed (HTTP {exc.code})") from exc
        except (URLError, TimeoutError) as exc:
            raise IntegrationError("provider could not be reached") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise IntegrationError("provider returned invalid JSON") from exc

    def test(self, provider: str, base_url: str, credential: str, username: str = "") -> dict[str, Any]:
        if provider not in PROVIDERS: raise ValidationError("unsupported DNS provider")
        base_url = validate_local_url(base_url)
        if not credential: raise ValidationError("credential is required")
        if provider == "technitium":
            _, value = self._json(Request(base_url + "/api/user/session/get", headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"}))
            if value.get("status") != "ok": raise IntegrationError("Technitium rejected the API token")
            return {"provider": provider, "status": "connected", "identity": value.get("username") or value.get("response", {}).get("username")}
        if provider == "pihole":
            request = Request(base_url + "/api/auth", data=json.dumps({"password": credential}).encode(), method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
            _, value = self._json(request); session = value.get("session") or {}
            if not session.get("valid") or not session.get("sid"): raise IntegrationError("Pi-hole rejected the application password")
            # Do not retain a verification-only session.
            try: urlopen(Request(base_url + "/api/auth", method="DELETE", headers={"X-FTL-SID": str(session["sid"])}), timeout=self.timeout, context=self.context).close()
            except Exception: pass
            return {"provider": provider, "status": "connected", "session_validity": session.get("validity")}
        if not username: raise ValidationError("username is required for AdGuard Home")
        encoded = base64.b64encode(f"{username}:{credential}".encode()).decode()
        _, value = self._json(Request(base_url + "/control/status", headers={"Authorization": f"Basic {encoded}", "Accept": "application/json"}))
        return {"provider": provider, "status": "connected", "identity": username, "dns_port": value.get("dns_port")}
