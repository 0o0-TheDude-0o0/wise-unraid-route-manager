import unittest
from app.auditor import audit_route
from app.models import RouteSpec
from test_models import VALID

class UnraidDriftTests(unittest.TestCase):
    def route(self): return RouteSpec.from_dict({**VALID,"source_container_id":"abc","source_container_name":"open-webui","source_port":3000})
    def test_running_container_and_port_are_healthy(self):
        report=audit_route(self.route(),{"unraid":{"exists":True,"running":True,"port_available":True}})
        self.assertTrue(any(f.provider=="unraid" and f.status=="healthy" for f in report.findings))
    def test_stopped_container_is_broken(self):
        report=audit_route(self.route(),{"unraid":{"exists":True,"running":False,"state":"exited"}})
        self.assertEqual(report.status,"broken")
    def test_changed_port_is_drift(self):
        report=audit_route(self.route(),{"unraid":{"exists":True,"running":True,"port_available":False,"services":[]},"technitium":{"addresses":["192.168.1.20"]},"caddy":{"upstream":"https://192.168.1.10:11443"},"pangolin":{"site_id":1,"upstream":"https://192.168.1.10:11443","authentication":True}})
        self.assertEqual(report.status,"drifted")
if __name__=="__main__": unittest.main()
