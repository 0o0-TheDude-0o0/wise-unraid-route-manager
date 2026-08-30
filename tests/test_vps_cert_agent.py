import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.vps_cert_agent import AgentApplication, RateLimiter, extract_bundle
from test_certificate_sync import material


class VpsCertificateAgentTests(unittest.TestCase):
    def acme_file(self,root: Path):
        cert,key=material()
        value={"letsencrypt":{"Certificates":[{"domain":{"main":"example.com","sans":["*.example.com"]},"certificate":base64.b64encode(cert).decode(),"key":base64.b64encode(key).decode()}]}}
        path=root/"acme.json"; path.write_text(json.dumps(value)); return path

    def test_extracts_only_exact_requested_acme_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=self.acme_file(root)
            self.assertEqual(extract_bundle(path,"*.example.com").names,("*.example.com",))
            with self.assertRaisesRegex(RuntimeError,"not present"): extract_bundle(path,"other.example.com")

    def test_rate_limiter_has_fixed_window_budget(self):
        limiter=RateLimiter(2)
        self.assertTrue(limiter.allow("site",0)); self.assertTrue(limiter.allow("site",1)); self.assertFalse(limiter.allow("site",2)); self.assertTrue(limiter.allow("site",61))

    def test_http_endpoint_requires_token_and_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); acme=self.acme_file(root); token=root/"token"; token.write_text("x"*40); token.chmod(0o600)
            app=AgentApplication(acme,token,{"*.example.com"}); server=ThreadingHTTPServer(("127.0.0.1",0),app.handler()); thread=Thread(target=server.serve_forever,daemon=True); thread.start(); base=f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(HTTPError) as denied: urlopen(base+"/v1/certificate?name=*.example.com")
                self.assertEqual(denied.exception.code,401); denied.exception.close()
                with self.assertRaises(HTTPError) as forbidden: urlopen(Request(base+"/v1/certificate?name=other.example.com",headers={"Authorization":"Bearer "+"x"*40}))
                self.assertEqual(forbidden.exception.code,403); forbidden.exception.close()
                with urlopen(Request(base+"/v1/certificate?name=*.example.com",headers={"Authorization":"Bearer "+"x"*40})) as response: value=json.load(response)
                self.assertIn("BEGIN CERTIFICATE",value["certificate_pem"]); self.assertIn("PRIVATE KEY",value["private_key_pem"])
            finally: server.shutdown(); server.server_close(); thread.join()


if __name__ == "__main__": unittest.main()
