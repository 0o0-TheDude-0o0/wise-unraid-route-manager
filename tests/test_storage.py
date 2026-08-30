import json
from pathlib import Path
import tempfile
import unittest

from app.storage import JsonStore


class JsonStoreTests(unittest.TestCase):
    def test_save_is_persistent_and_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonStore(Path(directory))
            store.save_routes([{"hostname": "one.example.com"}])
            store.save_routes([{"hostname": "two.example.com"}])
            self.assertEqual(store.load_routes()[0]["hostname"], "two.example.com")
            self.assertEqual(len(list(store.backups_dir.glob("routes-*.json"))), 1)
            self.assertEqual(store.routes_path.stat().st_mode & 0o777, 0o600)

    def test_audit_is_json_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonStore(Path(directory))
            store.audit({"event": "test", "secret": "redacted"})
            value = json.loads(store.audit_path.read_text().strip())
            self.assertEqual(value["event"], "test")
            self.assertIn("timestamp", value)

    def test_corrupt_routes_are_quarantined_and_latest_valid_backup_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            store=JsonStore(Path(directory))
            store.save_routes([{"hostname":"safe.example.com"}])
            store.save_routes([{"hostname":"new.example.com"}])
            store.routes_path.write_text("{broken",encoding="utf-8")
            recovered=store.load_routes()
            self.assertEqual(recovered,[{"hostname":"safe.example.com"}])
            self.assertEqual(json.loads(store.routes_path.read_text()),recovered)
            self.assertEqual(len(list(Path(directory).glob("routes.corrupt-*.json"))),1)
            self.assertIn('"event":"routes.recovered"',store.audit_path.read_text())

    def test_corrupt_routes_without_backup_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store=JsonStore(Path(directory)); store.routes_path.write_text("not-json",encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"no valid backup"):
                store.load_routes()


if __name__ == "__main__":
    unittest.main()
