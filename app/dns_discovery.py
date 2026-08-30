from __future__ import annotations
import base64
import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .integrations import IntegrationError

class DnsDiscovery:
    def __init__(self, integration: dict[str,Any], timeout: float=8):
        self.value=integration; self.timeout=timeout
        self.context=ssl.create_default_context() if integration.get("verify_tls",True) else ssl._create_unverified_context()
    def _get(self,path:str,headers:dict[str,str]) -> Any:
        try:
            with urlopen(Request(str(self.value["base_url"])+path,headers={"Accept":"application/json",**headers}),timeout=self.timeout,context=self.context) as response: return json.load(response)
        except HTTPError as exc:
            try: exc.close()
            finally: raise IntegrationError(f"DNS discovery failed (HTTP {exc.code})") from exc
        except (URLError,TimeoutError) as exc: raise IntegrationError("DNS provider could not be reached") from exc
    def discover(self) -> dict[str,Any]:
        provider=str(self.value.get("provider")); credential=str(self.value.get("credential",""))
        if provider=="technitium":
            value=self._get("/api/zones/list",{"Authorization":f"Bearer {credential}"})
            if value.get("status")!="ok": raise IntegrationError("Technitium rejected zone discovery")
            response=value.get("response") or {}; zones=response.get("zones") if isinstance(response,dict) else response
            zones=zones if isinstance(zones,list) else []
            normalized=[{"name":z.get("name") or z.get("zone"),"type":z.get("type")} if isinstance(z,dict) else {"name":str(z)} for z in zones]
            from urllib.parse import urlencode
            from .inventory import technitium_records
            records=[]
            for zone in normalized:
                name=str(zone.get("name") or "")
                if not name: continue
                record_value=self._get("/api/zones/records/get?"+urlencode({"domain":name,"zone":name,"listZone":"true"}),{"Authorization":f"Bearer {credential}"})
                if record_value.get("status")!="ok": raise IntegrationError(f"Technitium rejected record discovery for {name}")
                records.extend(technitium_records(record_value,name))
            return {"provider":provider,"zones":normalized,"records":records}
        if provider=="adguard":
            username=str(self.value.get("username","")); encoded=base64.b64encode(f"{username}:{credential}".encode()).decode()
            records=self._get("/control/rewrite/list",{"Authorization":f"Basic {encoded}"})
            if not isinstance(records,list): raise IntegrationError("AdGuard response did not contain rewrites")
            return {"provider":provider,"zones":[],"records":[{"hostname":r.get("domain"),"answer":r.get("answer"),"enabled":r.get("enabled",True)} for r in records if isinstance(r,dict)]}
        if provider=="pihole":
            hosts=self._pihole_hosts(credential)
            return {"provider":provider,"zones":[],"records":[{"hostname":name,"answer":address,"enabled":True} for address,name in hosts]}
        raise IntegrationError("integration is not a DNS provider")

    def observe(self, hostname: str) -> dict[str, Any] | None:
        provider=str(self.value.get("provider")); credential=str(self.value.get("credential",""))
        if provider=="technitium":
            from urllib.parse import urlencode
            value=self._get("/api/zones/records/get?"+urlencode({"domain":hostname}),{"Authorization":f"Bearer {credential}"})
            if value.get("status")!="ok": return None
            response=value.get("response") or {}; records=response.get("records",[]) if isinstance(response,dict) else []
            addresses=[]
            for record in records:
                if not isinstance(record,dict): continue
                rdata=record.get("rData") if isinstance(record.get("rData"),dict) else {}
                answer=record.get("ipAddress") or rdata.get("ipAddress")
                if answer: addresses.append(str(answer))
            return {"addresses":addresses,"conflict":len(set(addresses))>1}
        if provider=="adguard":
            records=self.discover()["records"]
            answers=[str(r["answer"]) for r in records if str(r.get("hostname","")).rstrip(".").lower()==hostname.rstrip(".").lower() and r.get("enabled",True)]
            return None if not answers else {"addresses":answers,"conflict":len(set(answers))>1}
        if provider=="pihole":
            answers=[address for address,name in self._pihole_hosts(credential) if name.rstrip(".").lower()==hostname.rstrip(".").lower()]
            return None if not answers else {"addresses":answers,"conflict":len(set(answers))>1}
        return None

    def _pihole_hosts(self, credential: str) -> list[tuple[str,str]]:
        base=str(self.value["base_url"])
        login=Request(base+"/api/auth",data=json.dumps({"password":credential}).encode(),method="POST",headers={"Content-Type":"application/json","Accept":"application/json"})
        try:
            with urlopen(login,timeout=self.timeout,context=self.context) as response: session=json.load(response).get("session",{})
            sid=session.get("sid") if session.get("valid") else None
            if not sid: raise IntegrationError("Pi-hole rejected the application password")
            value=self._get("/api/config/dns/hosts",{"X-FTL-SID":str(sid)})
            raw=value.get("config",{}).get("dns",{}).get("hosts",[]); result=[]
            for item in raw if isinstance(raw,list) else []:
                parts=str(item).split()
                if len(parts)>=2:
                    for name in parts[1:]: result.append((parts[0],name))
            return result
        finally:
            if 'sid' in locals() and sid:
                try: urlopen(Request(base+"/api/auth",method="DELETE",headers={"X-FTL-SID":str(sid)}),timeout=self.timeout,context=self.context).close()
                except Exception: pass
