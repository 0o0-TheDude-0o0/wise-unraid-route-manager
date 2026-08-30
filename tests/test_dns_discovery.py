import unittest
from app.dns_discovery import DnsDiscovery

class FakeDiscovery(DnsDiscovery):
    def __init__(self,value,response): super().__init__(value); self.response=response
    def _get(self,path,headers): return self.response
class FakePihole(DnsDiscovery):
    def _pihole_hosts(self,credential): return [("192.168.1.20","app.example.com")]
class DnsDiscoveryTests(unittest.TestCase):
    def test_technitium_zones(self):
        result=FakeDiscovery({"provider":"technitium","base_url":"http://127.0.0.1","credential":"x"},{"status":"ok","response":{"zones":[{"name":"example.com","type":"Primary"}]}}).discover()
        self.assertEqual(result["zones"][0]["name"],"example.com")
    def test_technitium_lists_records_for_every_zone(self):
        class Routed(FakeDiscovery):
            def _get(self,path,headers):
                if path=="/api/zones/list": return {"status":"ok","response":{"zones":[{"name":"example.com","type":"Primary"}]}}
                return {"status":"ok","response":{"records":[{"name":"app.example.com","type":"A","ttl":300,"rData":{"ipAddress":"192.168.1.20"}}]}}
        result=Routed({"provider":"technitium","base_url":"http://127.0.0.1","credential":"x"},{}).discover()
        self.assertEqual(result["records"][0]["hostname"],"app.example.com")
    def test_adguard_rewrites(self):
        result=FakeDiscovery({"provider":"adguard","base_url":"http://127.0.0.1","username":"u","credential":"p"},[{"domain":"app.example.com","answer":"192.168.1.20"}]).discover()
        self.assertEqual(result["records"][0]["answer"],"192.168.1.20")
    def test_pihole_hosts_are_discovered(self):
        result=FakePihole({"provider":"pihole","base_url":"http://127.0.0.1","credential":"p"}).discover()
        self.assertEqual(result["records"][0],{"hostname":"app.example.com","answer":"192.168.1.20","enabled":True})
if __name__=="__main__": unittest.main()
