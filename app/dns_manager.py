from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .providers.http import ProviderError
from .transaction import TransactionStep


class AddressRecords(Protocol):
    provider: str

    def addresses(self, hostname: str) -> list[str]: ...
    def add(self, hostname: str, address: str) -> None: ...
    def delete(self, hostname: str, address: str) -> None: ...


@dataclass(frozen=True)
class DnsSnapshot:
    hostname: str
    addresses: tuple[str, ...]

    def to_state(self) -> dict[str, object]:
        return {"hostname": self.hostname, "addresses": list(self.addresses)}


class DnsRecordManager:
    """Reconcile one hostname while preserving an exact rollback snapshot.

    The adapter is deliberately record-scoped: unrelated DNS records and aliases
    are never replaced as a side effect of applying a route.
    """

    def __init__(self, records: AddressRecords):
        self.records = records

    def snapshot(self, hostname: str) -> DnsSnapshot:
        normalized = self._hostname(hostname)
        return DnsSnapshot(normalized, tuple(dict.fromkeys(self.records.addresses(normalized))))

    def apply(self, hostname: str, address: str, *, replace_conflicts: bool = False) -> dict[str, object]:
        before = self.snapshot(hostname)
        desired = address.strip()
        if not desired:
            raise ValueError("DNS address is required")
        conflicts = [item for item in before.addresses if item != desired]
        if conflicts and not replace_conflicts:
            raise ProviderError(
                f"{self.records.provider} has conflicting answers for {before.hostname}; "
                "approve conflict replacement before applying"
            )

        if desired not in before.addresses:
            self.records.add(before.hostname, desired)
        try:
            if replace_conflicts:
                for old in conflicts:
                    self.records.delete(before.hostname, old)
        except Exception:
            self._restore(before)
            raise
        return before.to_state()

    def rollback(self, state: dict[str, object]) -> None:
        hostname = self._hostname(str(state["hostname"]))
        raw = state.get("addresses", [])
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ValueError("invalid DNS rollback state")
        self._restore(DnsSnapshot(hostname, tuple(dict.fromkeys(raw))))

    def transaction_step(
        self,
        hostname: str,
        address: str,
        *,
        replace_conflicts: bool = False,
    ) -> TransactionStep:
        """Build a composable step for the route-wide transaction executor."""
        return TransactionStep(
            provider=self.records.provider,
            action=f"reconcile DNS answer for {self._hostname(hostname)}",
            apply=lambda: self.apply(
                hostname, address, replace_conflicts=replace_conflicts
            ),
            rollback=self.rollback,
        )

    def _restore(self, snapshot: DnsSnapshot) -> None:
        current = tuple(dict.fromkeys(self.records.addresses(snapshot.hostname)))
        for address in current:
            if address not in snapshot.addresses:
                self.records.delete(snapshot.hostname, address)
        for address in snapshot.addresses:
            if address not in current:
                self.records.add(snapshot.hostname, address)

    @staticmethod
    def _hostname(value: str) -> str:
        hostname = value.strip().rstrip(".").lower()
        if not hostname:
            raise ValueError("DNS hostname is required")
        return hostname
