from __future__ import annotations
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .integrations import IntegrationError, validate_local_url

QUERY = """query WiseRouteContainerDiscovery { dockerContainers { id names state status image ports { ip privatePort publicPort type } lanIpPorts webUiUrl templatePorts { ip privatePort publicPort type } } }"""

_PROXY_SIGNATURES = (
    ("nginx-proxy-manager", ("nginx-proxy-manager", "jc21/nginx-proxy-manager", "npm")),
    ("swag", ("linuxserver/swag", "swag")),
    ("traefik", ("traefik",)),
    ("caddy", ("caddy",)),
)


def discover_reverse_proxies(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Identify likely existing reverse proxies without inspecting Docker or mutating them."""
    discovered: list[dict[str, Any]] = []
    for container in containers:
        haystack = f"{container.get('name', '')} {container.get('image', '')}".lower()
        kind = next((name for name, terms in _PROXY_SIGNATURES if any(term in haystack for term in terms)), None)
        if kind is None:
            continue
        discovered.append({
            "kind": kind,
            "container_id": container.get("id"),
            "container_name": container.get("name"),
            "image": container.get("image"),
            "running": container.get("state") == "running",
            "services": container.get("services", []),
            "recommended": container.get("state") == "running",
            "management": "native" if kind == "caddy" else "connection_required",
        })
    discovered.sort(key=lambda item: (not item["running"], item["kind"], str(item["container_name"])))
    if discovered:
        for item in discovered:
            item["recommended"] = item is discovered[0] and item["running"]
    return discovered


def discover_newt(containers: list[dict[str, Any]]) -> dict[str, Any] | None:
    for container in containers:
        haystack=f"{container.get('name','')} {container.get('image','')}".lower()
        if "fosrl/newt" in haystack or container.get("name", "").lower() == "newt":
            return {
                "container_id": container.get("id"), "container_name": container.get("name"),
                "image": container.get("image"), "running": container.get("state") == "running",
                "status": container.get("status"),
            }
    return None

class UnraidClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 8): self.base_url=validate_local_url(base_url); self.api_key=api_key; self.timeout=timeout
    def containers(self) -> list[dict[str, Any]]:
        request=Request(self.base_url+"/graphql",data=json.dumps({"query":QUERY}).encode(),method="POST",headers={"x-api-key":self.api_key,"Content-Type":"application/json","Accept":"application/json"})
        try:
            with urlopen(request,timeout=self.timeout) as response: value=json.load(response)
        except HTTPError as exc: raise IntegrationError(f"Unraid API rejected the request (HTTP {exc.code})") from exc
        except (URLError,TimeoutError) as exc: raise IntegrationError("Unraid API could not be reached") from exc
        except (json.JSONDecodeError,UnicodeDecodeError) as exc: raise IntegrationError("Unraid API returned invalid JSON") from exc
        if value.get("errors"): raise IntegrationError("Unraid API query failed: "+str(value["errors"][0].get("message","unknown error")))
        containers=value.get("data",{}).get("dockerContainers")
        if not isinstance(containers,list): raise IntegrationError("Unraid API response did not contain containers")
        return [self._normalize(item) for item in containers]
    def observe_source(self, container_id: str | None, container_name: str | None, port: int | None) -> dict[str,Any]:
        containers=self.containers(); match=next((c for c in containers if c.get("id")==container_id),None)
        if match is None and container_name: match=next((c for c in containers if c.get("name")==container_name),None)
        if match is None: return {"exists":False,"running":False,"port_available":False}
        available=False
        for service in match.get("services",[]):
            if service.get("port")==port: available=True
            if service.get("url"):
                from urllib.parse import urlsplit
                parsed=urlsplit(service["url"]); actual=parsed.port or (443 if parsed.scheme=="https" else 80)
                if actual==port: available=True
        return {"exists":True,"running":match.get("state")=="running","port_available":available,"state":match.get("state"),"services":match.get("services",[]),"container_id":match.get("id"),"container_name":match.get("name")}
    @staticmethod
    def _normalize(item: dict[str,Any]) -> dict[str,Any]:
        names=item.get("names") or []; name=str(names[0] if names else item.get("id","unknown")).lstrip("/")
        ports=item.get("ports") or item.get("templatePorts") or []; services=[]
        for port in ports:
            public=port.get("publicPort"); private=port.get("privatePort")
            if public is None or str(port.get("type","TCP")).upper()!="TCP": continue
            host_ip=str(port.get("ip") or "0.0.0.0")
            services.append({"port":int(public),"container_port":int(private) if private is not None else None,"protocol":"http","source":"published_port","host_ip":host_ip,"binding":"all_interfaces" if host_ip in {"0.0.0.0","::",""} else "specific_interface"})
        if item.get("webUiUrl"): services.insert(0,{"url":str(item["webUiUrl"]),"source":"webui"})
        lan_addresses=item.get("lanIpPorts") or []
        return {"id":item.get("id"),"name":name,"image":item.get("image"),"state":str(item.get("state","UNKNOWN")).lower(),"status":item.get("status"),"lan_addresses":lan_addresses,"network_mode":"custom_ip" if lan_addresses else ("published_ports" if ports else "internal"),"services":services}
