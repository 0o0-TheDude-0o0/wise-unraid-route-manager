from __future__ import annotations

import json
from typing import Any, Iterable

from ..models import RouteSpec


def route_id(hostname: str) -> str:
    return "wise-route-" + hostname.replace(".", "-")


def build_route(route: RouteSpec) -> dict[str, Any]:
    upstream: dict[str, Any] = {"dial": f"{route.upstream.host}:{route.upstream.port}"}
    transport: dict[str, Any] = {"protocol": "http"}
    if route.upstream.scheme == "https":
        tls: dict[str, Any] = {}
        if route.upstream.tls_server_name:
            tls["server_name"] = route.upstream.tls_server_name
        transport["tls"] = tls
    handler: dict[str, Any] = {"handler": "reverse_proxy", "upstreams": [upstream]}
    handler["transport"] = transport
    return {
        "@id": route_id(route.hostname),
        "match": [{"host": [route.hostname]}],
        "handle": [handler],
        "terminal": True,
    }


def build_config(routes: Iterable[RouteSpec]) -> dict[str, Any]:
    lan_routes = [build_route(route) for route in routes if route.enabled and route.mode in {"lan", "lan_remote"}]
    return {
        "admin": {"listen": "unix//run/wise-route-manager/caddy-admin.sock"},
        "apps": {
            "tls": {"certificates": {"load_files": [{
                "certificate": "/config/tls/tls.crt",
                "key": "/config/tls/tls.key",
                "tags": ["wise-user-supplied"],
            }]}},
            "http": {"servers": {
                "lan_http": {
                    "listen": [":80"],
                    "routes": [{"handle": [{
                        "handler": "static_response", "status_code": 308,
                        "headers": {"Location": ["https://{http.request.host}{http.request.uri}"]},
                    }]}],
                    "automatic_https": {"disable": True},
                },
                "lan": {
                    "listen": [":443"], "routes": lan_routes,
                    "tls_connection_policies": [{"certificate_selection": {"any_tag": ["wise-user-supplied"]}}],
                    "automatic_https": {"disable": True},
                },
            }},
        },
    }


def serialized_config(routes: Iterable[RouteSpec]) -> bytes:
    return (json.dumps(build_config(routes), sort_keys=True, separators=(",", ":")) + "\n").encode()

def observe_config(config: dict[str, Any], hostname: str) -> dict[str, Any] | None:
    routes=config.get("apps",{}).get("http",{}).get("servers",{}).get("lan",{}).get("routes",[]); matches=[]
    for route in routes:
        hosts=[host for match in route.get("match",[]) for host in match.get("host",[])]
        if hostname not in hosts and route.get("@id")!=route_id(hostname): continue
        for handler in route.get("handle",[]):
            if handler.get("handler")!="reverse_proxy": continue
            scheme="https" if handler.get("transport",{}).get("tls") is not None else "http"
            for upstream in handler.get("upstreams",[]): matches.append(f"{scheme}://{upstream.get('dial')}")
    if not matches: return None
    return {"upstream":matches[0],"upstreams":matches,"duplicate":len(matches)>1,"healthy":None}
