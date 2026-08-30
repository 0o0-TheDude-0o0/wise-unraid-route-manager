from __future__ import annotations

import base64
import json
import ssl
from contextlib import contextmanager
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .http import ProviderError


Open = Callable[..., Any]


class _UrlClient:
    def __init__(self, base_url: str, *, verify_tls: bool = True, timeout: float = 8, opener: Open = urlopen):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = opener
        self.context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()

    def request(self, method: str, path: str, *, headers: dict[str, str], body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base_url + path, data=data, method=method, headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "WiseRouteManager/0.1",
            **headers,
        })
        try:
            with self.opener(request, timeout=self.timeout, context=self.context) as response:
                payload = response.read()
        except HTTPError as exc:
            raise ProviderError(f"DNS provider returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise ProviderError("DNS provider connection failed") from exc
        if not payload:
            return None
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError("DNS provider returned invalid JSON") from exc


class AdGuardAddressRecords:
    provider = "adguard"

    def __init__(self, base_url: str, username: str, password: str, **kwargs: Any):
        self.http = _UrlClient(base_url, **kwargs)
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {encoded}"}

    def _records(self) -> list[dict[str, Any]]:
        value = self.http.request("GET", "/control/rewrite/list", headers=self.headers)
        if not isinstance(value, list):
            raise ProviderError("AdGuard did not return a rewrite list")
        return [item for item in value if isinstance(item, dict)]

    def addresses(self, hostname: str) -> list[str]:
        wanted = hostname.rstrip(".").lower()
        return [
            str(item["answer"])
            for item in self._records()
            if str(item.get("domain", "")).rstrip(".").lower() == wanted
            and item.get("enabled", True)
            and item.get("answer")
        ]

    def add(self, hostname: str, address: str) -> None:
        self.http.request("POST", "/control/rewrite/add", headers=self.headers, body={"domain": hostname, "answer": address})

    def delete(self, hostname: str, address: str) -> None:
        self.http.request("POST", "/control/rewrite/delete", headers=self.headers, body={"domain": hostname, "answer": address})


class PiHoleAddressRecords:
    provider = "pihole"

    def __init__(self, base_url: str, application_password: str, **kwargs: Any):
        self.http = _UrlClient(base_url, **kwargs)
        self.password = application_password

    @contextmanager
    def _session(self) -> Iterator[dict[str, str]]:
        value = self.http.request("POST", "/api/auth", headers={}, body={"password": self.password})
        session = value.get("session", {}) if isinstance(value, dict) else {}
        sid = session.get("sid") if session.get("valid") else None
        if not sid:
            raise ProviderError("Pi-hole rejected the application password")
        headers = {"X-FTL-SID": str(sid)}
        try:
            yield headers
        finally:
            try:
                self.http.request("DELETE", "/api/auth", headers=headers)
            except ProviderError:
                pass

    def _hosts(self) -> list[str]:
        with self._session() as headers:
            value = self.http.request("GET", "/api/config/dns/hosts", headers=headers)
        raw = value.get("config", {}).get("dns", {}).get("hosts", []) if isinstance(value, dict) else []
        if not isinstance(raw, list):
            raise ProviderError("Pi-hole did not return a hosts list")
        return [str(item) for item in raw]

    def addresses(self, hostname: str) -> list[str]:
        wanted = hostname.rstrip(".").lower()
        result: list[str] = []
        for item in self._hosts():
            parts = item.split()
            if len(parts) >= 2 and any(name.rstrip(".").lower() == wanted for name in parts[1:]):
                result.append(parts[0])
        return result

    @staticmethod
    def _path(hostname: str, address: str) -> str:
        value = quote(f"{address} {hostname}", safe="")
        return f"/api/config/dns/hosts/{value}"

    def add(self, hostname: str, address: str) -> None:
        with self._session() as headers:
            self.http.request("PUT", self._path(hostname, address), headers=headers)

    def delete(self, hostname: str, address: str) -> None:
        with self._session() as headers:
            self.http.request("DELETE", self._path(hostname, address), headers=headers)
