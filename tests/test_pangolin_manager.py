import unittest

from app.models import RouteSpec
from app.pangolin_manager import PangolinResourceManager
from app.providers.http import ProviderError
from test_models import VALID


class FakeClient:
    def __init__(self,resource=None,target=None):
        self.resource=resource; self.target=target; self.calls=[]; self.fail=None
    @staticmethod
    def _data(value): return value.get("data")
    def domains(self): return {"data":{"domains":[{"domainId":"2","baseDomain":"wisecompound.com"}]}}
    def resources(self,hostname=None): return [] if self.resource is None else [dict(self.resource)]
    def targets(self,resource_id): return [] if self.target is None else [dict(self.target)]
    def create_http_resource(self,**kwargs):
        self.calls.append(("create_resource",kwargs)); self.resource={"resourceId":4,"name":kwargs["name"],"enabled":True,"sso":True}; return dict(self.resource)
    def update_resource(self,resource_id,body):
        self.calls.append(("update_resource",resource_id,dict(body)))
        if self.fail=="update_resource": raise RuntimeError("resource update failed")
        if self.resource is not None: self.resource.update(body)
        return dict(self.resource or {})
    def delete_resource(self,resource_id): self.calls.append(("delete_resource",resource_id)); self.resource=None; self.target=None
    def create_target(self,resource_id,**kwargs):
        self.calls.append(("create_target",resource_id,kwargs))
        if self.fail=="create_target": raise RuntimeError("target creation failed")
        self.target={"targetId":9,"siteId":kwargs["site_id"],"ip":kwargs["host"],"port":kwargs["port"],"method":kwargs["method"]}; return dict(self.target)
    def update_target(self,target_id,body):
        self.calls.append(("update_target",target_id,dict(body)))
        if self.fail=="update_target": raise RuntimeError("target update failed")
        if self.target is not None: self.target.update(body)
        return dict(self.target or {})
    def delete_target(self,target_id): self.calls.append(("delete_target",target_id)); self.target=None


class PangolinManagerTests(unittest.TestCase):
    def test_new_resource_failure_deletes_created_resource(self):
        client=FakeClient(); client.fail="create_target"
        with self.assertRaises(RuntimeError): PangolinResourceManager(client).apply(RouteSpec.from_dict(VALID))
        self.assertIsNone(client.resource)
        self.assertIn(("delete_resource",4),client.calls)

    def test_existing_resource_and_target_are_restored(self):
        resource={"resourceId":4,"fullDomain":"unraid.wisecompound.com","name":"Old","enabled":False,"sso":False}
        target={"targetId":9,"siteId":1,"ip":"192.168.1.20","mode":"http","method":"http","port":8080,"enabled":False,"hcEnabled":False}
        client=FakeClient(resource,target); manager=PangolinResourceManager(client)
        state=manager.apply(RouteSpec.from_dict(VALID))
        self.assertEqual(client.target["ip"],VALID["upstream"]["host"])
        manager.rollback(state)
        self.assertEqual(client.resource["name"],"Old")
        self.assertFalse(client.resource["sso"])
        self.assertEqual(client.target["ip"],"192.168.1.20")
        self.assertEqual(client.target["port"],8080)

    def test_duplicate_hostname_is_never_mutated(self):
        class Duplicate(FakeClient):
            def resources(self,hostname=None): return [
                {"resourceId":1,"fullDomain":"unraid.wisecompound.com"},
                {"resourceId":2,"fullDomain":"unraid.wisecompound.com"},
            ]
        client=Duplicate()
        with self.assertRaises(ProviderError): PangolinResourceManager(client).apply(RouteSpec.from_dict(VALID))
        self.assertEqual(client.calls,[])


if __name__ == "__main__": unittest.main()
