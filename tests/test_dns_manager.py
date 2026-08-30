import unittest

from app.dns_manager import DnsRecordManager
from app.providers.http import ProviderError
from app.transaction import TransactionExecutor, TransactionStep


class FakeRecords:
    provider = "fake-dns"

    def __init__(self, addresses=()):
        self.values = list(addresses)
        self.calls = []
        self.fail_delete = None

    def addresses(self, hostname):
        self.calls.append(("list", hostname))
        return list(self.values)

    def add(self, hostname, address):
        self.calls.append(("add", hostname, address))
        if address not in self.values:
            self.values.append(address)

    def delete(self, hostname, address):
        self.calls.append(("delete", hostname, address))
        if address == self.fail_delete:
            self.fail_delete = None
            raise RuntimeError("delete failed")
        self.values.remove(address)


class DnsRecordManagerTests(unittest.TestCase):
    def test_idempotent_apply_does_not_mutate(self):
        records = FakeRecords(["192.168.1.10"])
        state = DnsRecordManager(records).apply("App.Example.com.", "192.168.1.10")
        self.assertEqual(state["addresses"], ["192.168.1.10"])
        self.assertEqual(records.calls, [("list", "app.example.com")])

    def test_conflict_requires_explicit_replacement(self):
        records = FakeRecords(["192.168.1.20"])
        with self.assertRaises(ProviderError):
            DnsRecordManager(records).apply("app.example.com", "192.168.1.10")
        self.assertEqual(records.values, ["192.168.1.20"])

    def test_replace_and_rollback_restore_exact_snapshot(self):
        records = FakeRecords(["192.168.1.20", "192.168.1.21"])
        manager = DnsRecordManager(records)
        state = manager.apply("app.example.com", "192.168.1.10", replace_conflicts=True)
        self.assertEqual(records.values, ["192.168.1.10"])
        manager.rollback(state)
        self.assertCountEqual(records.values, ["192.168.1.20", "192.168.1.21"])

    def test_partial_apply_failure_is_compensated(self):
        records = FakeRecords(["192.168.1.20", "192.168.1.21"])
        records.fail_delete = "192.168.1.21"
        with self.assertRaises(RuntimeError):
            DnsRecordManager(records).apply(
                "app.example.com", "192.168.1.10", replace_conflicts=True
            )
        self.assertCountEqual(records.values, ["192.168.1.20", "192.168.1.21"])

    def test_transaction_step_rolls_back_when_later_provider_fails(self):
        records = FakeRecords([])
        manager = DnsRecordManager(records)
        failure = TransactionStep(
            provider="next-provider",
            action="fail",
            apply=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            rollback=lambda state: None,
        )
        result = TransactionExecutor().run([
            manager.transaction_step("app.example.com", "192.168.1.10"),
            failure,
        ])
        self.assertEqual(result.status, "rolled_back")
        self.assertEqual(records.values, [])
        self.assertEqual(result.steps[0].rollback_status, "rolled_back")


if __name__ == "__main__":
    unittest.main()
