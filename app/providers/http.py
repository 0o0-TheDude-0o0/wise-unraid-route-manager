from __future__ import annotations

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    pass


class JsonHttpClient:
    def __init__(self, base_url: str, token: str, *, verify_tls: bool = True, timeout: float = 10):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()

    def request(self, method: str, path: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        if query:
            url += "?" + urlencode({k: v for k, v in query.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else None
        request = Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "WiseRouteManager/0.1",
        })
        try:
            with urlopen(request, timeout=self.timeout, context=self.context) as response:
                value = json.load(response)
        except HTTPError as exc:
            raise ProviderError(f"provider returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise ProviderError(f"provider connection failed: {exc.reason if hasattr(exc, 'reason') else exc}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError("provider returned an invalid JSON response") from exc
        if not isinstance(value, dict):
            raise ProviderError("provider response must be a JSON object")
        return value

