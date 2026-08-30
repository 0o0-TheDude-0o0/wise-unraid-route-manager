from __future__ import annotations

from typing import Any

from .http import JsonHttpClient, ProviderError


class TechnitiumClient:
    def __init__(self, http: JsonHttpClient):
        self.http = http

    @staticmethod
    def _check(value: dict[str, Any]) -> dict[str, Any]:
        status = value.get("status")
        if status != "ok":
            message = value.get("errorMessage") or f"Technitium status: {status}"
            raise ProviderError(str(message))
        return value

    def get_records(self, domain: str, zone: str | None = None) -> dict[str, Any]:
        return self._check(self.http.request("GET", "/api/zones/records/get", query={"domain": domain, "zone": zone}))

    def add_address(self, domain: str, address: str, *, ttl: int = 300, zone: str | None = None, overwrite: bool = False) -> dict[str, Any]:
        record_type = "AAAA" if ":" in address else "A"
        return self._check(self.http.request("POST", "/api/zones/records/add", query={
            "domain": domain, "zone": zone, "type": record_type, "ttl": ttl,
            "overwrite": str(overwrite).lower(), "ipAddress": address,
        }))

    def delete_address(self, domain: str, address: str, *, zone: str | None = None) -> dict[str, Any]:
        record_type = "AAAA" if ":" in address else "A"
        return self._check(self.http.request("POST", "/api/zones/records/delete", query={
            "domain": domain, "zone": zone, "type": record_type, "ipAddress": address,
        }))

