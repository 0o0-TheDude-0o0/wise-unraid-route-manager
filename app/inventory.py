from __future__ import annotations

import socket
from typing import Any


def resolution_status(hostname: str) -> dict[str, Any]:
    """Resolve a hostname without opening a connection to the returned address."""
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, None)})
    except (socket.gaierror, OSError) as exc:
        return {"status": "broken", "addresses": [], "error": str(exc)}
    return {"status": "healthy" if addresses else "broken", "addresses": addresses}


def caddy_inventory(config: dict[str, Any]) -> list[dict[str, Any]]:
    routes = config.get("apps", {}).get("http", {}).get("servers", {}).get("lan", {}).get("routes", [])
    result: list[dict[str, Any]] = []
    for route in routes if isinstance(routes, list) else []:
        hosts = [host for match in route.get("match", []) for host in match.get("host", [])]
        for handler in route.get("handle", []):
            if handler.get("handler") != "reverse_proxy":
                continue
            scheme = "https" if handler.get("transport", {}).get("tls") is not None else "http"
            upstreams = [f"{scheme}://{item.get('dial')}" for item in handler.get("upstreams", []) if item.get("dial")]
            for hostname in hosts:
                result.append({
                    "hostname": hostname,
                    "upstreams": upstreams,
                    "route_id": route.get("@id"),
                    "provider": "caddy",
                    "status": "configured" if upstreams else "broken",
                })
    return result


def technitium_records(value: dict[str, Any], zone: str) -> list[dict[str, Any]]:
    response = value.get("response") or {}
    records = response.get("records", []) if isinstance(response, dict) else []
    result = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        rdata = record.get("rData") if isinstance(record.get("rData"), dict) else {}
        answer = rdata.get("ipAddress") or rdata.get("cname") or rdata.get("value")
        result.append({
            "hostname": record.get("name") or record.get("domain"),
            "type": record.get("type"),
            "answer": answer,
            "ttl": record.get("ttl"),
            "disabled": bool(record.get("disabled", False)),
            "zone": zone,
            "status": "disabled" if record.get("disabled") else "configured",
        })
    return result


def pangolin_resources(client: Any) -> list[dict[str, Any]]:
    result = []
    for resource in client.resources():
        resource_id = resource.get("resourceId")
        targets = client.targets(int(resource_id)) if resource_id is not None else []
        result.append({
            "hostname": resource.get("fullDomain"),
            "name": resource.get("name"),
            "resource_id": resource_id,
            "domain_id": resource.get("domainId"),
            "enabled": bool(resource.get("enabled", False)),
            "authentication": bool(resource.get("sso") or resource.get("passwordId") or resource.get("pincodeId") or resource.get("whitelist") or resource.get("headerAuthId")),
            "targets": [{
                "target_id": target.get("targetId"),
                "site_id": target.get("siteId"),
                "upstream": f"{str(target.get('method') or 'http').lower()}://{target.get('ip')}:{target.get('port')}",
                "enabled": bool(target.get("enabled", False)),
                "health": target.get("hcHealth"),
            } for target in targets],
            "status": "configured" if resource.get("enabled") and targets else "broken",
            "infrastructure_role": "vps_edge",
            "proxy_ownership": "pangolin_managed",
        })
    return result


def correlate_routes(inventory: dict[str, Any], resolution: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a hostname index without assuming every DNS record is an application route."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    source_map = {"pangolin": "vps_edge", "technitium": "dns", "reverse_proxy": "lan_proxy"}
    for source, role in source_map.items():
        for item in inventory.get(source, []):
            hostname = str(item.get("hostname") or "").rstrip(".").lower()
            if not hostname:
                continue
            grouped.setdefault(hostname, {"vps_edge": [], "dns": [], "lan_proxy": []})[role].append(item)
    result = []
    for hostname, sources in sorted(grouped.items()):
        present = [name for name, items in sources.items() if items]
        issues = []
        resolved = resolution.get(hostname, {"status": "unknown", "addresses": []})
        if resolved.get("status") == "broken":
            issues.append("hostname does not resolve from Route Manager")
        for name, items in sources.items():
            if len(items) > 1:
                issues.append(f"duplicate {name} entries")
            if any(item.get("status") in {"broken", "disabled"} for item in items):
                issues.append(f"{name} contains a disabled or incomplete entry")
        if present == ["dns"]:
            classification = "dns_only"
        elif "vps_edge" in present and "lan_proxy" in present and "dns" in present:
            classification = "lan_and_remote"
        elif "vps_edge" in present:
            classification = "remote_or_incomplete"
        elif "lan_proxy" in present:
            classification = "lan_or_incomplete"
        else:
            classification = "partial"
        result.append({
            "hostname": hostname, "classification": classification,
            "sources": {name: len(items) for name, items in sources.items()},
            "resolution": resolved, "issues": issues,
            "status": "attention" if issues else "healthy",
        })
    return result
