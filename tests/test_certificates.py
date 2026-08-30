import unittest

from app.certificates import certificate_settings
from app.models import ValidationError


class CertificateSettingsTests(unittest.TestCase):
    def test_independent_dns01_uses_separate_lan_key(self):
        value=certificate_settings({"mode":"independent_dns01"})
        self.assertEqual(value["key_scope"],"lan_only")
        self.assertNotIn("credential",value)

    def test_newt_sync_is_private_and_pull_only(self):
        value=certificate_settings({"mode":"pangolin_newt_sync","endpoint":"https://cert-sync.internal/v1/certificate","credential":"secret","expected_name":"*.example.com","auto_renew":True})
        self.assertEqual(value["transport"],"newt")
        self.assertEqual(value["access"],"pull_only")
        self.assertTrue(value["auto_renew"])
        self.assertFalse(value["initial_sync_approved"])

    def test_newt_sync_rejects_public_endpoint(self):
        with self.assertRaises(ValidationError):
            certificate_settings({"mode":"pangolin_newt_sync","endpoint":"https://example.com","credential":"secret","expected_name":"*.example.com"})


if __name__ == "__main__": unittest.main()
