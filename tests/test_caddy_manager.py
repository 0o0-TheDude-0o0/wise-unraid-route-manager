from pathlib import Path
import json
import tempfile
import unittest
from app.caddy_manager import CaddyConfigManager

class CaddyManagerTests(unittest.TestCase):
    def test_apply_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"config.json"; path.write_text('{"old":true}\n'); events=[]
            manager=CaddyConfigManager(path,lambda p:events.append(("validate",json.loads(p.read_text()))),lambda p:events.append(("reload",json.loads(p.read_text()))))
            state=manager.apply({"new":True}); self.assertEqual(json.loads(path.read_text()),{"new":True})
            manager.rollback(state); self.assertEqual(json.loads(path.read_text()),{"old":True}); self.assertEqual(len(events),4)
    def test_validation_failure_preserves_old_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"config.json"; path.write_text('{"old":true}\n')
            def fail(_): raise RuntimeError("invalid")
            with self.assertRaises(RuntimeError): CaddyConfigManager(path,fail,lambda _:None).apply({"bad":True})
            self.assertEqual(json.loads(path.read_text()),{"old":True})
    def test_reload_failure_restores_old_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"config.json"; original=b'{"format":"preserved"}\n'; path.write_bytes(original)
            def fail(_): raise RuntimeError("reload failed")
            with self.assertRaises(RuntimeError): CaddyConfigManager(path,lambda _:None,fail).apply({"new":True})
            self.assertEqual(path.read_bytes(),original)
if __name__=="__main__": unittest.main()
