from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from app.server import Application


class ProviderState:
    def __init__(self):
        self.records: dict[str, list[str]] = {}
        self.resources: dict[int, dict] = {}
        self.targets: dict[int, list[dict]] = {}
        self.next_resource = 1
        self.next_target = 1
        self.fail_target = False


def provider_handler(state: ProviderState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def body(self):
            length=int(self.headers.get("Content-Length","0")); return json.loads(self.rfile.read(length) or b"{}")
        def reply(self,value,status=200):
            payload=json.dumps(value).encode(); self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(payload))); self.end_headers(); self.wfile.write(payload)
        def do_GET(self):
            parsed=urlsplit(self.path); path=parsed.path; query=parse_qs(parsed.query)
            if path=="/api/user/session/get": return self.reply({"status":"ok","response":{"username":"route-manager"}})
            if path=="/api/zones/records/get":
                hostname=query.get("domain",[""])[0]; records=[{"rData":{"ipAddress":address}} for address in state.records.get(hostname,[])]
                return self.reply({"status":"ok","response":{"records":records}})
            if path=="/v1/org/home/domains": return self.reply({"success":True,"data":{"domains":[{"domainId":"2","baseDomain":"example.test"}]}})
            if path=="/v1/org/home/sites": return self.reply({"success":True,"data":{"sites":[{"siteId":1,"niceId":"unraid","name":"Unraid","online":True,"status":"approved"}]}})
            if path=="/v1/org/home/public-resources": return self.reply({"success":True,"data":{"resources":list(state.resources.values())}})
            if path.startswith("/v1/public-resource/") and path.endswith("/targets"):
                resource_id=int(path.split("/")[3]); return self.reply({"success":True,"data":{"targets":state.targets.get(resource_id,[])}})
            return self.reply({"error":"not found"},404)
        def do_POST(self):
            parsed=urlsplit(self.path); path=parsed.path; query=parse_qs(parsed.query)
            if path=="/api/zones/records/add":
                hostname=query["domain"][0]; address=query["ipAddress"][0]; state.records.setdefault(hostname,[]).append(address)
                return self.reply({"status":"ok"})
            if path=="/api/zones/records/delete":
                hostname=query["domain"][0]; address=query["ipAddress"][0]; state.records.setdefault(hostname,[]).remove(address)
                return self.reply({"status":"ok"})
            if path.startswith("/v1/public-resource/"):
                resource_id=int(path.split("/")[3]); state.resources[resource_id].update(self.body()); return self.reply({"success":True,"data":state.resources[resource_id]})
            if path.startswith("/v1/target/"):
                target_id=int(path.split("/")[3]); body=self.body()
                target=next(item for values in state.targets.values() for item in values if item["targetId"]==target_id); target.update(body)
                return self.reply({"success":True,"data":target})
            return self.reply({"error":"not found"},404)
        def do_PUT(self):
            path=urlsplit(self.path).path; body=self.body()
            if path=="/v1/org/home/public-resource":
                resource_id=state.next_resource; state.next_resource+=1
                domain="example.test"; subdomain=body.get("subdomain"); full=f"{subdomain}.{domain}" if subdomain else domain
                resource={"resourceId":resource_id,"fullDomain":full,"name":body["name"],"enabled":True,"sso":True}
                state.resources[resource_id]=resource; state.targets[resource_id]=[]
                return self.reply({"success":True,"data":resource})
            if path.startswith("/v1/public-resource/") and path.endswith("/target"):
                if state.fail_target: return self.reply({"success":False,"error":True,"message":"injected target failure"})
                resource_id=int(path.split("/")[3]); target_id=state.next_target; state.next_target+=1
                target={"targetId":target_id,**body}; state.targets[resource_id].append(target)
                return self.reply({"success":True,"data":target})
            return self.reply({"error":"not found"},404)
        def do_DELETE(self):
            path=urlsplit(self.path).path
            if path.startswith("/v1/public-resource/"):
                resource_id=int(path.split("/")[3]); state.resources.pop(resource_id,None); state.targets.pop(resource_id,None)
                return self.reply({"success":True,"data":None})
            if path.startswith("/v1/target/"):
                target_id=int(path.split("/")[3])
                for values in state.targets.values(): values[:]=[item for item in values if item["targetId"]!=target_id]
                return self.reply({"success":True,"data":None})
            return self.reply({"error":"not found"},404)
    return Handler


@contextmanager
def running_server(handler):
    server=ThreadingHTTPServer(("127.0.0.1",0),handler); thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_port}"
    finally: server.shutdown(); server.server_close(); thread.join()


class ApiEndToEndTests(unittest.TestCase):
    def test_reviewed_apply_rollback_restart_and_secret_redaction(self):
        state=ProviderState(); responses=[]
        with tempfile.TemporaryDirectory() as directory, running_server(provider_handler(state)) as provider_url:
            root=Path(directory); (root/"config"/"caddy").mkdir(parents=True); fake_bin=root/"bin"; fake_bin.mkdir()
            caddy=fake_bin/"caddy"; caddy.write_text("#!/bin/sh\nexit 0\n"); caddy.chmod(0o755)
            old_path=os.environ.get("PATH",""); old_flag=os.environ.get("WISE_ENABLE_PROVIDER_MUTATIONS")
            os.environ["PATH"]=str(fake_bin)+os.pathsep+old_path; os.environ["WISE_ENABLE_PROVIDER_MUTATIONS"]="1"
            try:
                app=Application(root/"config",Path(__file__).parents[1]/"app"/"static")
                app.secrets.put({"id":"pangolin-primary","name":"Pangolin","provider":"pangolin","base_url":provider_url+"/v1","organization_id":"home","credential":"pangolin-secret","verify_tls":True,"status":"connected"})
                with running_server(app.handler()) as base:
                    def call(path,body=None):
                        data=None if body is None else json.dumps(body).encode(); request=Request(base+path,data=data,method="GET" if body is None else "POST",headers={"Authorization":f"Bearer {app.api_token}","Content-Type":"application/json"})
                        try:
                            with urlopen(request) as response: value=json.load(response); status=response.status
                        except HTTPError as exc:
                            try: value=json.load(exc); status=exc.code
                            finally: exc.close()
                        responses.append(value); return status,value
                    dns_secret="technitium-secret"
                    status,connected=call("/api/v1/integrations/test",{"provider":"technitium","name":"DNS","base_url":provider_url,"credential":dns_secret,"save":True})
                    self.assertEqual(status,200); dns_id=connected["integration"]["id"]
                    route={"name":"App","hostname":"app.example.test","mode":"lan_remote","lan_address":"192.168.1.50","dns_integration_id":dns_id,"upstream":{"scheme":"http","host":"192.168.1.10","port":8080},"pangolin_site_id":1,"pangolin_domain_id":2,"require_authentication":True}
                    _,plan=call("/api/v1/plans",route); status,result=call("/api/v1/apply",{"plan_id":plan["plan_id"],"confirmation_token":plan["confirmation_token"]})
                    self.assertEqual((status,result["status"]),(200,"applied")); self.assertEqual(state.records[route["hostname"]],["192.168.1.50"]); self.assertEqual(len(state.resources),1)
                    caddy_before=(root/"config"/"caddy"/"config.json").read_bytes()
                    status,inventory=call("/api/v1/inventory",{})
                    self.assertEqual(status,200)
                    self.assertEqual(inventory["pangolin"][0]["hostname"],route["hostname"])
                    self.assertEqual(inventory["reverse_proxy"][0]["hostname"],route["hostname"])
                    self.assertIn("technitium",inventory["errors"])

                    state.fail_target=True; failed={**route,"name":"Broken","hostname":"broken.example.test"}
                    _,plan=call("/api/v1/plans",failed); status,result=call("/api/v1/apply",{"plan_id":plan["plan_id"],"confirmation_token":plan["confirmation_token"]})
                    self.assertEqual((status,result["status"]),(409,"rolled_back")); self.assertEqual(state.records.get(failed["hostname"],[]),[]); self.assertEqual((root/"config"/"caddy"/"config.json").read_bytes(),caddy_before)

                restarted=Application(root/"config",Path(__file__).parents[1]/"app"/"static")
                self.assertEqual(restarted.api_token,app.api_token); self.assertEqual(restarted.store.load_routes()[0]["hostname"],route["hostname"])
                exposed=json.dumps(responses)+(root/"config"/"audit.jsonl").read_text()
                self.assertNotIn(dns_secret,exposed); self.assertNotIn("pangolin-secret",exposed)
            finally:
                os.environ["PATH"]=old_path
                if old_flag is None: os.environ.pop("WISE_ENABLE_PROVIDER_MUTATIONS",None)
                else: os.environ["WISE_ENABLE_PROVIDER_MUTATIONS"]=old_flag


if __name__ == "__main__": unittest.main()
