from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import unittest
from app.health import probe_upstream
from app.models import RouteSpec

class Healthy(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def do_HEAD(self): self.send_response(200); self.end_headers()
class HealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.server=ThreadingHTTPServer(("127.0.0.1",0),Healthy); cls.thread=Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
    def test_private_http_upstream(self):
        route=RouteSpec.from_dict({"name":"Test","hostname":"app.example.com","mode":"lan","lan_address":"192.168.1.20","upstream":{"scheme":"http","host":"127.0.0.1","port":self.server.server_port}})
        result=probe_upstream(route); self.assertTrue(result["dns"]); self.assertTrue(result["tcp"]); self.assertTrue(result["http"])
    def test_public_target_is_refused(self):
        route=RouteSpec.from_dict({"name":"Test","hostname":"app.example.com","mode":"lan","lan_address":"192.168.1.20","upstream":{"scheme":"https","host":"8.8.8.8","port":443}})
        result=probe_upstream(route); self.assertFalse(result["dns"]); self.assertIn("private",result["error"])
if __name__=="__main__": unittest.main()
