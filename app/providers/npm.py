from __future__ import annotations
import json, ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from ..integrations import IntegrationError, validate_local_url

class NginxProxyManagerClient:
    def __init__(self,base_url: str,token: str,*,verify_tls: bool=True,timeout: float=8):
        self.base_url=validate_local_url(base_url); self.token=token; self.timeout=timeout; self.context=ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        if not token: raise IntegrationError("Nginx Proxy Manager API token is required")
    def proxy_hosts(self) -> list[dict[str,Any]]:
        request=Request(self.base_url+"/api/nginx/proxy-hosts",headers={"Authorization":f"Bearer {self.token}","Accept":"application/json","User-Agent":"WiseRouteManager/0.1"})
        try:
            with urlopen(request,timeout=self.timeout,context=self.context) as response: value=json.load(response)
        except HTTPError as exc:
            try: exc.close()
            finally: raise IntegrationError(f"Nginx Proxy Manager rejected the request (HTTP {exc.code})") from exc
        except (URLError,TimeoutError) as exc: raise IntegrationError("Nginx Proxy Manager could not be reached") from exc
        except (json.JSONDecodeError,UnicodeDecodeError) as exc: raise IntegrationError("Nginx Proxy Manager returned invalid JSON") from exc
        if not isinstance(value,list): raise IntegrationError("Nginx Proxy Manager response did not contain proxy hosts")
        return [item for item in value if isinstance(item,dict)]
    def inventory(self) -> list[dict[str,Any]]:
        result=[]
        for host in self.proxy_hosts():
            scheme=str(host.get("forward_scheme") or "http").lower(); target=host.get("forward_host"); port=host.get("forward_port")
            domains=host.get("domain_names",[]) if isinstance(host.get("domain_names"),list) else []
            for hostname in domains:
                result.append({"hostname":str(hostname).lower().rstrip("."),"provider":"nginx_proxy_manager","proxy_host_id":host.get("id"),"upstreams":[f"{scheme}://{target}:{port}"],"enabled":bool(host.get("enabled",False)),"certificate_id":host.get("certificate_id"),"force_ssl":bool(host.get("ssl_forced",False)),"websocket":bool(host.get("allow_websocket_upgrade",False)),"status":"configured" if host.get("enabled") and target and port else "broken"})
        return result
