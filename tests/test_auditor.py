import unittest
from app.auditor import audit_route, unmanaged_report
from app.models import RouteSpec
from test_models import VALID

class AuditorTests(unittest.TestCase):
    def setUp(self): self.route = RouteSpec.from_dict(VALID)
    def test_missing_dependencies_are_incomplete(self):
        report = audit_route(self.route, {})
        self.assertEqual(report.status, "incomplete"); self.assertEqual(len(report.corrections), 3)
    def test_matching_route_is_healthy(self):
        report = audit_route(self.route, {"technitium":{"addresses":["192.168.1.20"]},"caddy":{"upstream":"https://192.168.1.10:11443","healthy":True},"pangolin":{"site_id":1,"upstream":"https://192.168.1.10:11443","authentication":True,"healthy":True}})
        self.assertEqual(report.status, "healthy"); self.assertFalse(report.corrections)
    def test_conflict_wins(self):
        report = audit_route(self.route, {"technitium":{"conflict":True,"addresses":["192.168.1.21","192.168.1.22"]}})
        self.assertEqual(report.status, "conflict"); self.assertEqual(report.corrections[0].risk, "elevated")
    def test_drift_offers_specific_corrections(self):
        report = audit_route(self.route, {"technitium":{"addresses":["192.168.1.99"]},"caddy":{"upstream":"http://192.168.1.10:80"},"pangolin":{"site_id":99,"upstream":"http://bad:80","authentication":False}})
        self.assertEqual(report.status, "drifted")
        self.assertEqual({c.action for c in report.corrections},{"replace_dns","replace_proxy","update_resource"})
    def test_unmanaged_resources_can_be_adopted(self):
        report = unmanaged_report("old.example.com", ["technitium","pangolin"])
        self.assertEqual(report.status, "unmanaged"); self.assertTrue(all(c.action == "adopt" for c in report.corrections))
    def test_pangolin_connection_error_is_broken(self):
        report=audit_route(self.route,{"pangolin":{"error":"timeout"}})
        self.assertEqual(report.status,"broken"); self.assertTrue(any(f.provider=="pangolin" and f.status=="broken" for f in report.findings))

if __name__ == "__main__": unittest.main()
