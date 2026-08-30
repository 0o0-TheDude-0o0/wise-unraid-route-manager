from __future__ import annotations

from typing import Any

from .models import RouteSpec, ValidationError
from .providers.http import ProviderError
from .providers.pangolin import PangolinClient
from .transaction import TransactionStep


RESOURCE_FIELDS = ("name", "enabled", "sso")
TARGET_FIELDS = (
    "siteId", "ip", "mode", "method", "port", "enabled", "hcEnabled",
    "hcPath", "hcScheme", "hcMode", "hcHostname", "hcPort", "hcInterval",
    "hcUnhealthyInterval", "hcTimeout", "hcHeaders", "hcFollowRedirects",
    "hcMethod", "hcStatus", "hcTlsServerName", "hcHealthyThreshold",
    "hcUnhealthyThreshold", "path", "pathMatchType", "rewritePath",
    "rewritePathType", "priority",
)

TARGET_NULLABLE = (
    "hcPath", "hcScheme", "hcMode", "hcHostname", "hcPort", "hcInterval",
    "hcUnhealthyInterval", "hcTimeout", "hcHeaders", "hcFollowRedirects",
    "hcMethod", "hcStatus", "hcTlsServerName", "hcHealthyThreshold",
    "hcUnhealthyThreshold", "path", "pathMatchType", "rewritePath",
    "rewritePathType",
)


def _snapshot(value: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: value[field] for field in fields if field in value}


def _target_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    for required in ("siteId", "ip", "port", "enabled"):
        if required not in value: raise ProviderError(f"existing Pangolin target omitted {required}; safe adoption is not possible")
    result = _snapshot(value, TARGET_FIELDS)
    result.setdefault("mode", "http")
    result.setdefault("method", "http")
    result.setdefault("hcEnabled", False)
    for field in TARGET_NULLABLE: result.setdefault(field, None)
    return result


class PangolinResourceManager:
    """Reconcile one public HTTP resource without claiming unrelated objects."""

    provider = "pangolin"

    def __init__(self, client: PangolinClient): self.client = client

    def _matching_resource(self, hostname: str) -> dict[str, Any] | None:
        matches = [item for item in self.client.resources(hostname)
                   if str(item.get("fullDomain", "")).rstrip(".").lower() == hostname]
        if len(matches) > 1: raise ProviderError(f"multiple Pangolin resources claim {hostname}")
        return matches[0] if matches else None

    def _subdomain(self, route: RouteSpec) -> str | None:
        value = self.client.domains()
        data = self.client._data(value) or {}
        domains = data.get("domains", []) if isinstance(data, dict) else []
        selected = next((item for item in domains if str(item.get("domainId")) == str(route.pangolin_domain_id)), None)
        if not isinstance(selected, dict): raise ProviderError("selected Pangolin domain was not found")
        base = str(selected.get("baseDomain") or selected.get("domain") or selected.get("name") or "").rstrip(".").lower()
        if not base or not (route.hostname == base or route.hostname.endswith("." + base)):
            raise ValidationError("route hostname is not within the selected Pangolin domain")
        return None if route.hostname == base else route.hostname[:-(len(base) + 1)]

    @staticmethod
    def _id(value: Any, label: str) -> int:
        try: return int(value)
        except (TypeError, ValueError): raise ProviderError(f"Pangolin did not return a {label} ID") from None

    def apply(self, route: RouteSpec) -> dict[str, Any]:
        if route.mode not in {"remote", "lan_remote"} or route.pangolin_site_id is None or route.pangolin_domain_id is None:
            raise ValidationError("Pangolin transaction requires a remote-enabled route")
        state: dict[str, Any] = {"resource_created": False, "target_created": False}
        resource = self._matching_resource(route.hostname)
        try:
            if resource is None:
                resource = self.client.create_http_resource(
                    name=route.name, domain_id=route.pangolin_domain_id,
                    subdomain=self._subdomain(route),
                )
                state["resource_created"] = True
            resource_id = self._id(resource.get("resourceId"), "resource")
            state["resource_id"] = resource_id
            if not state["resource_created"]:
                for required in RESOURCE_FIELDS:
                    if required not in resource: raise ProviderError(f"existing Pangolin resource omitted {required}; safe adoption is not possible")
                state["resource_before"] = _snapshot(resource, RESOURCE_FIELDS)
            self.client.update_resource(resource_id, {
                "name": route.name, "enabled": route.enabled,
                "sso": route.require_authentication,
            })

            targets = self.client.targets(resource_id)
            target = next((item for item in targets if item.get("siteId") == route.pangolin_site_id), None)
            target_body = {
                "siteId": route.pangolin_site_id, "ip": route.upstream.host,
                "mode": "http", "method": route.upstream.scheme,
                "port": route.upstream.port, "enabled": route.enabled,
                "hcEnabled": True, "hcPath": route.health_path,
                "hcScheme": route.upstream.scheme, "hcHostname": route.upstream.host,
                "hcPort": route.upstream.port,
            }
            if target is None:
                created = self.client.create_target(resource_id, site_id=route.pangolin_site_id,
                    host=route.upstream.host, port=route.upstream.port, method=route.upstream.scheme,
                    hcEnabled=True, hcPath=route.health_path, hcScheme=route.upstream.scheme,
                    hcHostname=route.upstream.host, hcPort=route.upstream.port)
                state["target_created"] = True
                state["target_id"] = self._id(created.get("targetId"), "target")
            else:
                target_id = self._id(target.get("targetId"), "target")
                state["target_id"] = target_id
                state["target_before"] = _target_snapshot(target)
                self.client.update_target(target_id, target_body)
            return state
        except Exception:
            self.rollback(state)
            raise

    def rollback(self, state: dict[str, Any]) -> None:
        if state.get("resource_created") and state.get("resource_id"):
            self.client.delete_resource(int(state["resource_id"]))
            return
        if state.get("target_created") and state.get("target_id"):
            self.client.delete_target(int(state["target_id"]))
        elif state.get("target_before") and state.get("target_id"):
            self.client.update_target(int(state["target_id"]), dict(state["target_before"]))
        if state.get("resource_before") and state.get("resource_id"):
            self.client.update_resource(int(state["resource_id"]), dict(state["resource_before"]))

    def transaction_step(self, route: RouteSpec) -> TransactionStep:
        return TransactionStep(
            provider="pangolin", action=f"reconcile public resource for {route.hostname}",
            apply=lambda: self.apply(route), rollback=self.rollback,
        )
