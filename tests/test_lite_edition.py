from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.request import urlopen

from app.server import Application


class LiteEditionTests(unittest.TestCase):
    def test_lite_edition_serves_route_only_shell_and_script(self):
        previous=os.environ.get("WISE_EDITION")
        os.environ["WISE_EDITION"]="lite"
        try:
            with tempfile.TemporaryDirectory() as directory:
                app=Application(Path(directory),Path(__file__).parents[1]/"app"/"static")
                server=ThreadingHTTPServer(("127.0.0.1",0),app.handler())
                thread=Thread(target=server.serve_forever,daemon=True); thread.start()
                try:
                    base=f"http://127.0.0.1:{server.server_port}"
                    html=urlopen(base+"/").read().decode()
                    script=urlopen(base+"/app.js").read().decode()
                    self.assertIn("Route Manager Lite",html)
                    self.assertNotIn("Unraid service discovery",html)
                    self.assertIn("/api/v1/audits/all",script)
                    self.assertIn("/api/v1/unraid/reverse-proxies",script)
                finally:
                    server.shutdown(); server.server_close(); thread.join()
        finally:
            if previous is None: os.environ.pop("WISE_EDITION",None)
            else: os.environ["WISE_EDITION"]=previous


if __name__ == "__main__": unittest.main()
