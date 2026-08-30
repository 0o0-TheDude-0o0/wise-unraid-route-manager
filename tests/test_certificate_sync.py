from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.certificate_sync import CertificateInstaller, renewal_comparison, validate_bundle
from app.models import ValidationError


def material(name="*.example.com"):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)]))
          .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"Test CA")]))
          .public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=60))
          .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]),critical=False).sign(key,hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM),key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())


class CertificateSyncTests(unittest.TestCase):
    def test_validates_matching_wildcard_and_key(self):
        cert,key=material(); bundle=validate_bundle(cert,key,"*.example.com")
        self.assertIn("*.example.com",bundle.names)
        self.assertEqual(len(bundle.fingerprint),64)

    def test_rejects_mismatched_private_key(self):
        cert,_=material(); _,other=material()
        with self.assertRaisesRegex(ValidationError,"do not match"): validate_bundle(cert,other,"*.example.com")

    def test_installer_rolls_back_both_files_on_reload_failure(self):
        cert,key=material(); bundle=validate_bundle(cert,key,"*.example.com")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); tls=root/"tls"; tls.mkdir(); (tls/"tls.crt").write_bytes(b"old-cert"); (tls/"tls.key").write_bytes(b"old-key"); config=root/"config.json"; config.write_text("{}")
            installer=CertificateInstaller(tls,config,validator=lambda _:None,reloader=lambda _:(_ for _ in ()).throw(RuntimeError("reload failed")))
            with self.assertRaisesRegex(RuntimeError,"reload failed"): installer.install(bundle)
            self.assertEqual((tls/"tls.crt").read_bytes(),b"old-cert")
            self.assertEqual((tls/"tls.key").read_bytes(),b"old-key")

    def test_renewal_requires_a_different_later_certificate(self):
        cert,key=material(); bundle=validate_bundle(cert,key,"*.example.com")
        current={"status":"installed","fingerprint_sha256":bundle.fingerprint,"not_after":bundle.not_after}
        self.assertFalse(renewal_comparison(current,bundle)["update_available"])
        older={"status":"installed","fingerprint_sha256":"different","not_after":"2026-01-01T00:00:00+00:00"}
        self.assertTrue(renewal_comparison(older,bundle)["update_available"])


if __name__ == "__main__": unittest.main()
