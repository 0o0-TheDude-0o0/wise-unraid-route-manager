import unittest

from app.inventory import caddy_inventory, correlate_routes, pangolin_resources, technitium_records
from app.models import RouteSpec
from app.providers.caddy import build_config
from test_models import VALID


class InventoryTests(unittest.TestCase):
    def test_caddy_routes_are_listed_separately(self):
        result=caddy_inventory(build_config([RouteSpec.from_dict(VALID)]))
        self.assertEqual(result[0]["hostname"],VALID["hostname"])
        self.assertEqual(result[0]["upstreams"],["https://192.168.1.10:11443"])

    def test_technitium_records_are_normalized(self):
        value={"response":{"records":[{"name":"app.example.com","type":"A","ttl":300,"rData":{"ipAddress":"192.168.1.20"},"disabled":False}]}}
        result=technitium_records(value,"example.com")
        self.assertEqual(result[0]["answer"],"192.168.1.20")
        self.assertEqual(result[0]["zone"],"example.com")

    def test_pangolin_inventory_includes_targets(self):
        class Client:
            def resources(self): return [{"resourceId":4,"domainId":8,"fullDomain":"app.example.com","name":"App","enabled":True,"sso":True}]
            def targets(self,_): return [{"targetId":9,"siteId":7,"method":"http","ip":"192.168.1.20","port":3000,"enabled":True,"hcHealth":"healthy"}]
        result=pangolin_resources(Client())
        self.assertEqual(result[0]["domain_id"],8)
        self.assertEqual(result[0]["targets"][0]["upstream"],"http://192.168.1.20:3000")
        self.assertEqual(result[0]["infrastructure_role"],"vps_edge")
        self.assertEqual(result[0]["proxy_ownership"],"pangolin_managed")

    def test_route_map_correlates_sources_without_merging_them(self):
        inventory={
            "pangolin":[{"hostname":"app.example.com","status":"configured"}],
            "technitium":[{"hostname":"app.example.com","status":"configured"},{"hostname":"printer.example.com","status":"configured"}],
            "reverse_proxy":[{"hostname":"app.example.com","status":"configured"}],
        }
        result=correlate_routes(inventory,{"app.example.com":{"status":"healthy","addresses":["192.168.1.10"]},"printer.example.com":{"status":"healthy","addresses":["192.168.1.30"]}})
        app=next(item for item in result if item["hostname"]=="app.example.com")
        printer=next(item for item in result if item["hostname"]=="printer.example.com")
        self.assertEqual(app["classification"],"lan_and_remote")
        self.assertEqual(app["sources"],{"vps_edge":1,"dns":1,"lan_proxy":1})
        self.assertEqual(printer["classification"],"dns_only")


if __name__ == "__main__": unittest.main()
