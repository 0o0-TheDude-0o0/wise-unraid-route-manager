import unittest
from app.dns_discovery import DnsDiscovery
from app.providers.caddy import build_config, observe_config
from app.models import RouteSpec
from test_models import VALID

class FakeDns(DnsDiscovery):
    def __init__(self,value,response): super().__init__(value); self.response=response
    def _get(self,path,headers): return self.response
class LiveObservationTests(unittest.TestCase):
    def test_technitium_record_observation(self):
        client=FakeDns({"provider":"technitium","base_url":"http://127.0.0.1","credential":"x"},{"status":"ok","response":{"records":[{"rData":{"ipAddress":"192.168.1.20"}}]}})
        self.assertEqual(client.observe("app.example.com")["addresses"],["192.168.1.20"])
    def test_adguard_conflict_observation(self):
        client=FakeDns({"provider":"adguard","base_url":"http://127.0.0.1","username":"u","credential":"p"},[{"domain":"app.example.com","answer":"192.168.1.20"},{"domain":"app.example.com","answer":"192.168.1.21"}])
        self.assertTrue(client.observe("app.example.com")["conflict"])
    def test_caddy_observation(self):
        route=RouteSpec.from_dict(VALID); observed=observe_config(build_config([route]),route.hostname)
        self.assertEqual(observed["upstream"],route.upstream.url); self.assertFalse(observed["duplicate"])
if __name__=="__main__": unittest.main()
