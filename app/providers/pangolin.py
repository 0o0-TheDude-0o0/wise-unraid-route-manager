from __future__ import annotations

from typing import Any

from .http import JsonHttpClient, ProviderError


class PangolinClient:
    def __init__(self, http: JsonHttpClient, organization_id: str):
        self.http = http
        self.organization_id = organization_id

    def domains(self) -> dict[str, Any]:
        return self.http.request("GET", f"/org/{self.organization_id}/domains")

    @staticmethod
    def _data(value: dict[str, Any]) -> Any:
        if value.get("success") is False or value.get("error") is True:
            raise ProviderError(str(value.get("message") or "Pangolin rejected the request"))
        return value.get("data")

    def resources(self, hostname: str | None = None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"pageSize": 100, "page": 1}
        if hostname: query["query"] = hostname
        value = self.http.request("GET", f"/org/{self.organization_id}/public-resources", query=query)
        data = self._data(value) or {}
        resources = data.get("resources", []) if isinstance(data, dict) else []
        if not isinstance(resources, list): raise ProviderError("Pangolin response did not contain resources")
        return [item for item in resources if isinstance(item, dict)]

    def targets(self, resource_id: int) -> list[dict[str, Any]]:
        value = self.http.request("GET", f"/public-resource/{resource_id}/targets", query={"limit": 1000, "offset": 0})
        data = self._data(value) or {}
        targets = data.get("targets", []) if isinstance(data, dict) else []
        if not isinstance(targets, list): raise ProviderError("Pangolin response did not contain targets")
        return [item for item in targets if isinstance(item, dict)]

    def sites(self) -> list[dict[str, Any]]:
        value = self.http.request("GET", f"/org/{self.organization_id}/sites", query={"pageSize": 100, "page": 1})
        if value.get("success") is False: raise RuntimeError(str(value.get("message") or "Pangolin rejected the site query"))
        sites = value.get("data", {}).get("sites", [])
        if not isinstance(sites, list): raise RuntimeError("Pangolin response did not contain sites")
        return [{"site_id": s.get("siteId"), "connector_id": s.get("niceId"), "name": s.get("name"), "online": s.get("online"), "status": s.get("status"), "address": s.get("address"), "newt_version": s.get("newtVersion"), "resource_count": s.get("resourceCount", 0)} for s in sites]

    def observe_resource(self, hostname: str, preferred_site_id: int | None = None) -> dict[str, Any] | None:
        resources=self.resources(hostname)
        matches=[r for r in resources if str(r.get("fullDomain","")).rstrip(".").lower()==hostname.rstrip(".").lower()]
        if not matches: return None
        if len(matches)>1: return {"duplicate":True,"resource_ids":[r.get("resourceId") for r in matches]}
        resource=matches[0]; resource_id=resource.get("resourceId")
        targets=self.targets(int(resource_id))
        target=next((t for t in targets if t.get("siteId")==preferred_site_id),targets[0] if targets else None)
        authentication=bool(resource.get("sso") or resource.get("passwordId") or resource.get("pincodeId") or resource.get("whitelist") or resource.get("headerAuthId"))
        if target is None: return {"resource_id":resource_id,"site_id":None,"upstream":None,"authentication":authentication,"healthy":False,"enabled":resource.get("enabled",False)}
        method=str(target.get("method") or "http").lower(); upstream=f"{method}://{target.get('ip')}:{target.get('port')}"
        health=target.get("hcHealth"); healthy=bool(resource.get("enabled",False) and target.get("enabled",False) and (not target.get("hcEnabled") or health in {None,"healthy","unknown"}))
        return {"resource_id":resource_id,"resource_nice_id":resource.get("niceId"),"site_id":target.get("siteId"),"upstream":upstream,"authentication":authentication,"healthy":healthy,"enabled":resource.get("enabled"),"target_id":target.get("targetId"),"health_status":health,"health_path":target.get("hcPath")}

    def create_http_resource(self, *, name: str, domain_id: int, subdomain: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, "domainId": str(domain_id), "mode": "http"}
        if subdomain:
            body["subdomain"] = subdomain
        return self._data(self.http.request("PUT", f"/org/{self.organization_id}/public-resource", body=body))

    def create_target(self, resource_id: int, *, site_id: int, host: str, port: int, method: str, **settings: Any) -> dict[str, Any]:
        body = {
            "siteId": site_id, "ip": host, "port": port, "method": method,
            "mode": "http", "enabled": True,
        }
        body.update(settings)
        return self._data(self.http.request("PUT", f"/public-resource/{resource_id}/target", body=body))

    def update_resource(self, resource_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return self._data(self.http.request("POST", f"/public-resource/{resource_id}", body=body))

    def delete_resource(self, resource_id: int) -> None:
        self._data(self.http.request("DELETE", f"/public-resource/{resource_id}"))

    def update_target(self, target_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return self._data(self.http.request("POST", f"/target/{target_id}", body=body))

    def delete_target(self, target_id: int) -> None:
        self._data(self.http.request("DELETE", f"/target/{target_id}"))
