import unittest
from app.transaction import TransactionExecutor,TransactionStep

class TransactionTests(unittest.TestCase):
    def test_successful_transaction(self):
        events=[]
        steps=[TransactionStep("dns","create",lambda:(events.append("dns") or {"before":None}),lambda state:events.append("undo-dns")),TransactionStep("caddy","create",lambda:(events.append("caddy") or {"before":None}),lambda state:events.append("undo-caddy"))]
        result=TransactionExecutor().run(steps)
        self.assertEqual(result.status,"applied"); self.assertEqual(events,["dns","caddy"])
    def test_failure_rolls_back_reverse_order(self):
        events=[]
        def fail(): events.append("pangolin-fail"); raise RuntimeError("injected")
        steps=[TransactionStep("dns","create",lambda:(events.append("dns") or {"id":1}),lambda state:events.append("undo-dns")),TransactionStep("caddy","create",lambda:(events.append("caddy") or {"id":2}),lambda state:events.append("undo-caddy")),TransactionStep("pangolin","create",fail,lambda state:None)]
        result=TransactionExecutor().run(steps)
        self.assertEqual(result.status,"rolled_back"); self.assertEqual(events,["dns","caddy","pangolin-fail","undo-caddy","undo-dns"])
    def test_rollback_failure_is_reported(self):
        def rollback(_): raise RuntimeError("cannot restore")
        def fail(): raise RuntimeError("apply failed")
        result=TransactionExecutor().run([TransactionStep("dns","create",lambda:{"old":"x"},rollback),TransactionStep("caddy","create",fail,lambda _:None)])
        self.assertEqual(result.status,"rollback_failed"); self.assertEqual(len(result.rollback_errors),1)
    def test_missing_rollback_state_fails_safely(self):
        result=TransactionExecutor().run([TransactionStep("dns","create",lambda:None,lambda _:None)])
        self.assertEqual(result.status,"rolled_back"); self.assertIn("rollback state",result.error)
if __name__=="__main__": unittest.main()
