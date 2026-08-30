import json
import unittest

from app.providers.dns_mutation import AdGuardAddressRecords, PiHoleAddressRecords


class Response:
    def __init__(self, value=None):
        self.payload = b"" if value is None else json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return self.payload


class Opener:
    def __init__(self, responses): self.responses=list(responses); self.requests=[]
    def __call__(self, request, **kwargs):
        self.requests.append(request)
        return Response(self.responses.pop(0))


class AdGuardMutationTests(unittest.TestCase):
    def test_exact_rewrite_operations(self):
        opener=Opener([[{"domain":"app.example.com","answer":"192.168.1.10"}],None,None])
        records=AdGuardAddressRecords("http://192.168.1.2","route-manager","secret",opener=opener)
        self.assertEqual(records.addresses("app.example.com"),["192.168.1.10"])
        records.add("new.example.com","192.168.1.11")
        records.delete("new.example.com","192.168.1.11")
        self.assertEqual([r.full_url for r in opener.requests],[
            "http://192.168.1.2/control/rewrite/list",
            "http://192.168.1.2/control/rewrite/add",
            "http://192.168.1.2/control/rewrite/delete",
        ])
        self.assertEqual(json.loads(opener.requests[1].data),{"domain":"new.example.com","answer":"192.168.1.11"})


class PiHoleMutationTests(unittest.TestCase):
    @staticmethod
    def login(): return {"session":{"valid":True,"sid":"temporary"}}

    def test_reads_and_logs_out(self):
        opener=Opener([self.login(),{"config":{"dns":{"hosts":["192.168.1.10 app.example.com alias.example.com"]}}},None])
        records=PiHoleAddressRecords("http://192.168.1.2","app-password",opener=opener)
        self.assertEqual(records.addresses("alias.example.com"),["192.168.1.10"])
        self.assertEqual(opener.requests[-1].method,"DELETE")
        self.assertEqual(opener.requests[-1].headers["X-ftl-sid"],"temporary")

    def test_item_level_add_uses_encoded_host_entry(self):
        opener=Opener([self.login(),None,None])
        records=PiHoleAddressRecords("http://192.168.1.2","app-password",opener=opener)
        records.add("app.example.com","192.168.1.10")
        self.assertEqual(opener.requests[1].method,"PUT")
        self.assertTrue(opener.requests[1].full_url.endswith("/api/config/dns/hosts/192.168.1.10%20app.example.com"))
        self.assertEqual(opener.requests[2].method,"DELETE")


if __name__ == "__main__": unittest.main()
