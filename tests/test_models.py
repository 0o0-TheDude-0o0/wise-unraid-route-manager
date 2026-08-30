import unittest

from app.models import RouteSpec, ValidationError
from app.planner import PlanStore, build_initial_plan


VALID = {
    "name": "Unraid",
    "hostname": "unraid.wisecompound.com",
    "mode": "lan_remote",
    "lan_address": "192.168.1.20",
    "upstream": {"scheme": "https", "host": "192.168.1.10", "port": 11443},
    "pangolin_site_id": 1,
    "pangolin_domain_id": 2,
    "require_authentication": True,
}


class RouteSpecTests(unittest.TestCase):
    def test_valid_route(self):
        route = RouteSpec.from_dict(VALID)
        self.assertEqual(route.hostname, "unraid.wisecompound.com")
        self.assertEqual(route.upstream.url, "https://192.168.1.10:11443")

    def test_remote_route_rejects_lan_address(self):
        value = dict(VALID, mode="remote")
        with self.assertRaisesRegex(ValidationError, "only valid for LAN"):
            RouteSpec.from_dict(value)

    def test_lan_route_does_not_require_pangolin_ids(self):
        value = dict(VALID, mode="lan", pangolin_site_id=None, pangolin_domain_id=None)
        route = RouteSpec.from_dict(value)
        self.assertEqual([s.provider for s in build_initial_plan(route)], ["technitium", "caddy"])

    def test_unprotected_public_route_is_elevated_risk(self):
        route = RouteSpec.from_dict(dict(VALID, require_authentication=False))
        self.assertEqual(build_initial_plan(route)[-1].risk, "elevated")

    def test_invalid_hostname_rejected(self):
        with self.assertRaises(ValidationError):
            RouteSpec.from_dict(dict(VALID, hostname="not a hostname"))


class PlanStoreTests(unittest.TestCase):
    def test_token_is_single_use(self):
        route = RouteSpec.from_dict(VALID)
        store = PlanStore()
        plan = store.create(route, build_initial_plan(route))
        self.assertEqual(store.consume(plan.plan_id, plan.confirmation_token), plan)
        with self.assertRaises(ValueError):
            store.consume(plan.plan_id, plan.confirmation_token)

    def test_wrong_token_consumes_plan(self):
        route = RouteSpec.from_dict(VALID)
        store = PlanStore()
        plan = store.create(route, [])
        with self.assertRaises(ValueError):
            store.consume(plan.plan_id, "wrong")
        with self.assertRaises(ValueError):
            store.consume(plan.plan_id, plan.confirmation_token)


if __name__ == "__main__":
    unittest.main()

