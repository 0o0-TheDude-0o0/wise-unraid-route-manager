import tempfile
import unittest
from pathlib import Path

from app.caddy_manager import CaddyConfigManager
from app.models import RouteSpec
from app.route_apply import RouteApplyService
from app.transaction import TransactionStep
from test_models import VALID

LAN = dict(VALID, mode="lan")


class FakeDns:
    provider="fake"
    def __init__(self): self.values=[]
    def addresses(self, hostname): return list(self.values)
    def add(self, hostname, address): self.values.append(address)
    def delete(self, hostname, address): self.values.remove(address)


class RouteApplyTests(unittest.TestCase):
    def test_caddy_failure_rolls_back_dns(self):
        import app.route_apply as module
        dns=FakeDns(); original=module.dns_records; module.dns_records=lambda integration: dns
        try:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/"config.json"
                caddy=CaddyConfigManager(path,validator=lambda path: None,reloader=lambda path: (_ for _ in ()).throw(RuntimeError("reload failed")))
                result,routes=RouteApplyService(path,caddy_manager=caddy).apply_lan(RouteSpec.from_dict(LAN),[],{"provider":"fake"})
                self.assertEqual(result.status,"rolled_back")
                self.assertEqual(dns.values,[])
                self.assertFalse(path.exists())
                self.assertEqual(len(routes),1)
        finally:
            module.dns_records=original

    def test_success_returns_routes_for_post_transaction_persistence(self):
        import app.route_apply as module
        dns=FakeDns(); original=module.dns_records; module.dns_records=lambda integration: dns
        try:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/"config.json"
                caddy=CaddyConfigManager(path,validator=lambda path: None,reloader=lambda path: None)
                result,routes=RouteApplyService(path,caddy_manager=caddy).apply_lan(RouteSpec.from_dict(LAN),[],{"provider":"fake"})
                self.assertEqual(result.status,"applied")
                self.assertEqual(routes[0]["hostname"],VALID["hostname"])
                self.assertTrue(path.exists())
        finally:
            module.dns_records=original

    def test_combined_pangolin_failure_rolls_back_caddy_and_dns(self):
        import app.route_apply as module
        dns=FakeDns(); old_dns=module.dns_records; old_manager=module.PangolinResourceManager
        class FailingPangolin:
            def __init__(self,client): pass
            def transaction_step(self,route):
                return TransactionStep("pangolin","fail",lambda: (_ for _ in ()).throw(RuntimeError("pangolin failed")),lambda state: None)
        module.dns_records=lambda integration: dns; module.PangolinResourceManager=FailingPangolin
        try:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/"config.json"
                caddy=CaddyConfigManager(path,validator=lambda path: None,reloader=lambda path: None)
                result,_=RouteApplyService(path,caddy_manager=caddy).apply_route(
                    RouteSpec.from_dict(VALID),[],dns_integration={"provider":"fake"},
                    pangolin_integration={"base_url":"https://pangolin.local/v1","credential":"x","organization_id":"home"},
                )
                self.assertEqual(result.status,"rolled_back")
                self.assertEqual(dns.values,[])
                self.assertFalse(path.exists())
                self.assertEqual(result.steps[0].rollback_status,"rolled_back")
                self.assertEqual(result.steps[1].rollback_status,"rolled_back")
        finally:
            module.dns_records=old_dns; module.PangolinResourceManager=old_manager


if __name__ == "__main__": unittest.main()
