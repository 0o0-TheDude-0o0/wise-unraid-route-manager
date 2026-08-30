import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import unittest
from app.unraid import UnraidClient, discover_newt, discover_reverse_proxies

class FakeUnraid(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"])); payload=json.dumps({"data":{"dockerContainers":[{"id":"1","names":["/open-webui"],"image":"open-webui:latest","state":"RUNNING","status":"Up","ports":[{"privatePort":8080,"publicPort":3000,"type":"TCP"},{"privatePort":53,"publicPort":53,"type":"UDP"}],"lanIpPorts":["192.168.1.10:3000"],"webUiUrl":"http://192.168.1.10:3000"}]}}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(payload))); self.end_headers(); self.wfile.write(payload)
class UnraidTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.server=ThreadingHTTPServer(("127.0.0.1",0),FakeUnraid); cls.thread=Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
    def test_discovery_normalizes_services(self):
        value=UnraidClient(f"http://127.0.0.1:{self.server.server_port}","key").containers()[0]
        self.assertEqual(value["name"],"open-webui"); self.assertEqual(value["state"],"running"); self.assertEqual(len(value["services"]),2); self.assertEqual(value["services"][1]["port"],3000)
    def test_reverse_proxy_discovery_prefers_running_existing_proxy(self):
        proxies=discover_reverse_proxies([
            {"id":"1","name":"SWAG","image":"lscr.io/linuxserver/swag","state":"running","services":[]},
            {"id":"2","name":"caddy-old","image":"caddy:2","state":"exited","services":[]},
            {"id":"3","name":"app","image":"example/app","state":"running","services":[]},
        ])
        self.assertEqual([item["kind"] for item in proxies],["swag","caddy"])
        self.assertTrue(proxies[0]["recommended"])
        self.assertEqual(proxies[0]["management"],"connection_required")
        self.assertFalse(proxies[1]["recommended"])
    def test_newt_discovery_is_separate_from_lan_proxy(self):
        value=discover_newt([{"id":"n1","name":"newt","image":"fosrl/newt:latest","state":"running","status":"Up"}])
        self.assertEqual(value["container_name"],"newt")
        self.assertTrue(value["running"])
if __name__=="__main__": unittest.main()
