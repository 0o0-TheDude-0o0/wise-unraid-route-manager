from __future__ import annotations

from typing import Any, Callable

from .technitium import TechnitiumClient


class TechnitiumAddressRecords:
    provider = "technitium"

    def __init__(self, client: TechnitiumClient, *, zone: str | None = None, ttl: int = 300):
        self.client = client
        self.zone = zone
        self.ttl = ttl

    def addresses(self, hostname: str) -> list[str]:
        value = self.client.get_records(hostname, self.zone)
        response = value.get("response") or {}
        records = response.get("records", []) if isinstance(response, dict) else []
        result: list[str] = []
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            rdata = record.get("rData") if isinstance(record.get("rData"), dict) else {}
            address = record.get("ipAddress") or rdata.get("ipAddress")
            if address:
                result.append(str(address))
        return result

    def add(self, hostname: str, address: str) -> None:
        self.client.add_address(hostname, address, ttl=self.ttl, zone=self.zone)

    def delete(self, hostname: str, address: str) -> None:
        self.client.delete_address(hostname, address, zone=self.zone)


class CallbackAddressRecords:
    """Small adapter for AdGuard/Pi-hole clients with exact record operations."""

    def __init__(
        self,
        provider: str,
        list_records: Callable[[], list[dict[str, Any]]],
        add_record: Callable[[str, str], None],
        delete_record: Callable[[str, str], None],
    ):
        self.provider = provider
        self._list = list_records
        self._add = add_record
        self._delete = delete_record

    def addresses(self, hostname: str) -> list[str]:
        wanted = hostname.rstrip(".").lower()
        return [
            str(record["answer"])
            for record in self._list()
            if str(record.get("hostname", "")).rstrip(".").lower() == wanted
            and record.get("enabled", True)
            and record.get("answer")
        ]

    def add(self, hostname: str, address: str) -> None:
        self._add(hostname, address)

    def delete(self, hostname: str, address: str) -> None:
        self._delete(hostname, address)
