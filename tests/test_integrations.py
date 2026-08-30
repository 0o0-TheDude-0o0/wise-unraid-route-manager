import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from app.integrations import IntegrationError, IntegrationTester, validate_local_url
from app.models import ValidationError

class FakeProvider(BaseHTTPRequestHandler):
    deleted = False
    def log_message(self, *_): pass
    def _send(self, value):
        payload=json.dumps(value).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(payload))); self.end_headers(); self.wfile.write(payload)
    def do_GET(self):
        if self.path == "/api/user/session/get":
            self._send({"status":"ok","username":"route-user"} if self.headers.get("Authorization")=="Bearer tech-token" else {"status":"invalid-token"})
        elif self.path == "/control/status":
            self._send({"dns_port":53}) if self.headers.get("Authorization","").startswith("Basic ") else self.send_error(401)
        else: self.send_error(404)
    def do_POST(self):
        if self.path != "/api/auth": return self.send_error(404)
        body=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._send({"session":{"valid":True,"sid":"temporary","validity":300}}) if body.get("password")=="app-pass" else self.send_error(401)
    def do_DELETE(self):
        FakeProvider.deleted=True; self.send_response(204); self.end_headers()

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),FakeProvider); cls.thread=Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start(); cls.url=f"http://127.0.0.1:{cls.server.server_port}"
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
    def test_public_provider_url_is_rejected(self):
        with self.assertRaises(ValidationError): validate_local_url("https://8.8.8.8")
    def test_url_credentials_are_rejected(self):
        with self.assertRaises(ValidationError): validate_local_url("http://user:pass@127.0.0.1")
    def test_technitium_token(self):
        result=IntegrationTester().test("technitium",self.url,"tech-token"); self.assertEqual(result["identity"],"route-user")
    def test_pihole_app_password_and_logout(self):
        FakeProvider.deleted=False; result=IntegrationTester().test("pihole",self.url,"app-pass"); self.assertEqual(result["status"],"connected"); self.assertTrue(FakeProvider.deleted)
    def test_adguard_basic_auth(self):
        result=IntegrationTester().test("adguard",self.url,"password","route-user"); self.assertEqual(result["dns_port"],53)

if __name__ == "__main__": unittest.main()
