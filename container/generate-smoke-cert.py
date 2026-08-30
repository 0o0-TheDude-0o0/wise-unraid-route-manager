from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

directory=Path("/config/tls")
directory.mkdir(parents=True,exist_ok=True)
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"app.example.test")])
now=datetime.now(timezone.utc)
certificate=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
    .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
    .not_valid_after(now+timedelta(hours=1)).add_extension(
        x509.SubjectAlternativeName([x509.DNSName("app.example.test"),x509.IPAddress(ip_address("127.0.0.1"))]),False)
    .sign(key,hashes.SHA256()))
(directory/"tls.key").write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
(directory/"tls.crt").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
(directory/"tls.key").chmod(0o600)
