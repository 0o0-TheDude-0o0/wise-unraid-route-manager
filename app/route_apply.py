from __future__ import annotations

from pathlib import Path
from typing import Any

from .caddy_manager import CaddyConfigManager
from .dns_manager import DnsRecordManager
from .models import RouteSpec, ValidationError
from .pangolin_manager import PangolinResourceManager
from .providers.caddy import build_config
from .providers.dns_mutation import AdGuardAddressRecords, PiHoleAddressRecords
from .providers.dns_records import TechnitiumAddressRecords
from .providers.http import JsonHttpClient
from .providers.technitium import TechnitiumClient
from .providers.pangolin import PangolinClient
from .transaction import TransactionExecutor, TransactionResult, TransactionStep


def dns_records(integration: dict[str, Any]):
    provider = str(integration.get("provider", ""))
    base_url = str(integration.get("base_url", ""))
    credential = str(integration.get("credential", ""))
    common = {"verify_tls": bool(integration.get("verify_tls", True))}
    if provider == "technitium":
        client = TechnitiumClient(JsonHttpClient(base_url, credential, **common))
        return TechnitiumAddressRecords(
            client,
            zone=str(integration["zone"]) if integration.get("zone") else None,
            ttl=int(integration.get("ttl", 300)),
        )
    if provider == "adguard":
        return AdGuardAddressRecords(base_url, str(integration.get("username", "")), credential, **common)
    if provider == "pihole":
        return PiHoleAddressRecords(base_url, credential, **common)
    raise ValidationError("saved integration is not a supported DNS provider")


class RouteApplyService:
    """Compose reviewed provider mutations without persisting partial state."""

    def __init__(self, caddy_path: Path, *, caddy_manager: CaddyConfigManager | None = None):
        self.caddy = caddy_manager or CaddyConfigManager(caddy_path)

    def apply_lan(
        self,
        route: RouteSpec,
        existing_routes: list[dict[str, Any]],
        dns_integration: dict[str, Any],
    ) -> tuple[TransactionResult, list[dict[str, Any]]]:
        if route.mode not in {"lan", "lan_remote"} or not route.lan_address:
            raise ValidationError("LAN transaction requires a LAN-enabled route")
        return self.apply_route(route, existing_routes, dns_integration=dns_integration)

    def apply_route(
        self,
        route: RouteSpec,
        existing_routes: list[dict[str, Any]],
        *,
        dns_integration: dict[str, Any] | None = None,
        pangolin_integration: dict[str, Any] | None = None,
    ) -> tuple[TransactionResult, list[dict[str, Any]]]:
        desired = route.to_dict()
        routes = [item for item in existing_routes if item.get("hostname") != route.hostname]
        routes.append(desired)
        parsed = [RouteSpec.from_dict(item) for item in routes]
        steps: list[TransactionStep] = []
        if route.mode in {"lan", "lan_remote"}:
            if not route.lan_address or dns_integration is None:
                raise ValidationError("LAN routes require a saved DNS integration")
            dns = DnsRecordManager(dns_records(dns_integration))
            steps.extend([
                dns.transaction_step(route.hostname, route.lan_address),
                TransactionStep(
                    provider="caddy", action=f"reconcile proxy for {route.hostname}",
                    apply=lambda: self.caddy.apply(build_config(parsed)), rollback=self.caddy.rollback,
                ),
            ])
        if route.mode in {"remote", "lan_remote"}:
            if pangolin_integration is None:
                raise ValidationError("remote routes require a saved Pangolin integration")
            client = PangolinClient(
                JsonHttpClient(
                    str(pangolin_integration["base_url"]), str(pangolin_integration["credential"]),
                    verify_tls=bool(pangolin_integration.get("verify_tls", True)),
                ),
                str(pangolin_integration["organization_id"]),
            )
            steps.append(PangolinResourceManager(client).transaction_step(route))
        return TransactionExecutor().run(steps), routes
