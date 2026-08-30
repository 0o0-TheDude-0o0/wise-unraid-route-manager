from pathlib import Path
import tempfile
import unittest

from cryptography.fernet import Fernet
from app.secrets_store import SecretsStore

class SecretsStoreTests(unittest.TestCase):
    def test_round_trip_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SecretsStore(Path(directory)); public=store.put({"id":"one","provider":"pihole","credential":"top-secret"})
            self.assertNotIn("credential",public); self.assertEqual(store.get("one")["credential"],"top-secret")
            self.assertNotIn(b"top-secret",store.data_path.read_bytes())
            self.assertEqual(store.key_path.stat().st_mode & 0o777,0o600)
            self.assertEqual(store.data_path.stat().st_mode & 0o777,0o600)
    def test_delete_removes_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SecretsStore(Path(directory)); store.put({"id":"one","credential":"secret"})
            self.assertTrue(store.delete("one")); self.assertFalse(store.delete("one")); self.assertEqual(store.list_public(),[])
    def test_wrong_key_fails_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory); store=SecretsStore(path); store.put({"id":"one","credential":"secret"})
            path.joinpath("master.key").write_bytes(Fernet.generate_key()+b"\n"); path.joinpath("master.key").chmod(0o600)
            with self.assertRaisesRegex(RuntimeError,"authenticated"): SecretsStore(path).list_public()

if __name__ == "__main__": unittest.main()
