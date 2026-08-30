import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import unittest
from app.providers.npm import NginxProxyManagerClient

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def do_GET(self):
        if self.headers.get("Authorization")!="Bearer secret": self.send_response(401); self.end_headers(); return
        payload=json.dumps([{"id":7,"domain_names":["app.example.com","alias.example.com"],"forward_scheme":"http","forward_host":"192.168.1.20","forward_port":3000,"enabled":1,"certificate_id":4,"ssl_forced":1,"allow_websocket_upgrade":1}]).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(payload))); self.end_headers(); self.wfile.write(payload)

class NginxProxyManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.server=ThreadingHTTPServer(("127.0.0.1",0),Handler); cls.thread=Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def test_read_only_inventory_normalizes_each_domain(self):
        routes=NginxProxyManagerClient(f"http://127.0.0.1:{self.server.server_port}","secret").inventory()
        self.assertEqual(len(routes),2); self.assertEqual(routes[0]["upstreams"],["http://192.168.1.20:3000"]); self.assertTrue(routes[0]["force_ssl"]); self.assertEqual(routes[0]["provider"],"nginx_proxy_manager")

if __name__=="__main__": unittest.main()
