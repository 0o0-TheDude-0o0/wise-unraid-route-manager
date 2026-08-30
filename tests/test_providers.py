import unittest

from app.models import RouteSpec
from app.providers.caddy import build_config, build_route, route_id
from app.providers.http import ProviderError
from app.providers.technitium import TechnitiumClient
from test_models import VALID


class FakeHttp:
    def __init__(self, response=None): self.response=response or {"status":"ok"}; self.calls=[]
    def request(self, method, path, **kwargs): self.calls.append((method,path,kwargs)); return self.response


class TechnitiumTests(unittest.TestCase):
    def test_add_a_record_uses_official_parameters(self):
        http=FakeHttp(); client=TechnitiumClient(http)
        client.add_address("unraid.example.com", "192.168.1.20")
        method,path,kwargs=http.calls[0]
        self.assertEqual((method,path),("POST","/api/zones/records/add"))
        self.assertEqual(kwargs["query"]["type"],"A")
        self.assertEqual(kwargs["query"]["overwrite"],"false")

    def test_error_status_is_rejected(self):
        with self.assertRaises(ProviderError):
            TechnitiumClient(FakeHttp({"status":"error","errorMessage":"denied"})).get_records("x.example")


class CaddyTests(unittest.TestCase):
    def test_route_has_stable_id_and_https_transport(self):
        route=RouteSpec.from_dict(VALID); value=build_route(route)
        self.assertEqual(value["@id"],route_id(route.hostname))
        self.assertIn("tls",value["handle"][0]["transport"])

    def test_remote_only_route_not_added_to_lan_server(self):
        value=dict(VALID,mode="remote",lan_address=None)
        config=build_config([RouteSpec.from_dict(value)])
        self.assertEqual(config["apps"]["http"]["servers"]["lan"]["routes"],[])

    def test_user_certificate_and_standard_https_ports(self):
        config=build_config([RouteSpec.from_dict(VALID)])
        servers=config["apps"]["http"]["servers"]
        self.assertEqual(servers["lan_http"]["listen"],[":80"])
        self.assertEqual(servers["lan"]["listen"],[":443"])
        pair=config["apps"]["tls"]["certificates"]["load_files"][0]
        self.assertEqual(pair["key"],"/config/tls/tls.key")

class PangolinTests(unittest.TestCase):
    def test_current_create_and_delete_paths(self):
        from app.providers.pangolin import PangolinClient
        http=FakeHttp({"success":True,"data":{"resourceId":12}})
        client=PangolinClient(http,"home")
        client.create_http_resource(name="App",domain_id=3,subdomain="app")
        method,path,kwargs=http.calls[-1]
        self.assertEqual((method,path),("PUT","/org/home/public-resource"))
        self.assertEqual(kwargs["body"],{"name":"App","domainId":"3","mode":"http","subdomain":"app"})
        http.response={"success":True,"data":None}
        client.delete_resource(12)
        self.assertEqual(http.calls[-1][:2],("DELETE","/public-resource/12"))

    def test_current_target_paths(self):
        from app.providers.pangolin import PangolinClient
        http=FakeHttp({"success":True,"data":{"targetId":9}})
        client=PangolinClient(http,"home")
        client.create_target(12,site_id=7,host="192.168.1.10",port=3000,method="http")
        self.assertEqual(http.calls[-1][:2],("PUT","/public-resource/12/target"))
        client.update_target(9,{"siteId":7,"ip":"192.168.1.11"})
        self.assertEqual(http.calls[-1][:2],("POST","/target/9"))
    def test_sites_are_normalized(self):
        from app.providers.pangolin import PangolinClient
        http=FakeHttp({"success":True,"data":{"sites":[{"siteId":7,"niceId":"newt-id","name":"Unraid","online":True,"status":"approved","newtVersion":"1.16.0"}]}})
        sites=PangolinClient(http,"home").sites()
        self.assertEqual(sites[0]["site_id"],7); self.assertEqual(sites[0]["connector_id"],"newt-id"); self.assertTrue(sites[0]["online"])

    def test_resource_observation_includes_target_and_auth(self):
        from app.providers.pangolin import PangolinClient
        class RoutedHttp:
            def request(self,method,path,**kwargs):
                if path.endswith("public-resources"): return {"data":{"resources":[{"resourceId":4,"niceId":"app","fullDomain":"app.example.com","enabled":True,"sso":True}]}}
                return {"data":{"targets":[{"targetId":9,"siteId":7,"ip":"192.168.1.10","port":3000,"method":"http","enabled":True,"hcEnabled":True,"hcHealth":"healthy","hcPath":"/"}]}}
        observed=PangolinClient(RoutedHttp(),"home").observe_resource("app.example.com",7)
        self.assertEqual(observed["upstream"],"http://192.168.1.10:3000"); self.assertTrue(observed["authentication"]); self.assertTrue(observed["healthy"])

    def test_duplicate_resources_are_conflict(self):
        from app.providers.pangolin import PangolinClient
        http=FakeHttp({"data":{"resources":[{"resourceId":1,"fullDomain":"app.example.com"},{"resourceId":2,"fullDomain":"app.example.com"}]}})
        self.assertTrue(PangolinClient(http,"home").observe_resource("app.example.com")["duplicate"])


if __name__ == "__main__": unittest.main()
