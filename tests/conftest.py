import base64
from email.policy import SMTP
import subprocess

import dkim
import pytest


@pytest.fixture(scope="session")
def key_material(tmp_path_factory):
    # Ephemeral test-only key/certificate; never used by the application.
    directory = tmp_path_factory.mktemp("test-signing-key")
    key, certificate = directory / "key.pem", directory / "cert.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(certificate), "-days", "1",
                    "-subj", "/CN=localhost"], check=True, capture_output=True)
    public = subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout",
                             "-outform", "DER"], check=True, capture_output=True).stdout
    return key, certificate, b"v=DKIM1; k=rsa; p=" + base64.b64encode(public)


@pytest.fixture
def sign_email(key_material, monkeypatch):
    key, _, public = key_material

    def lookup(name, timeout=5):
        assert name == b"test._domainkey.example.com."
        return public

    monkeypatch.setattr("photo_hub.authentication.lookup_dkim_key", lookup)

    def sign(message, headers=None, length=False, domain=b"example.com"):
        raw = message.as_bytes(policy=SMTP)
        signature = dkim.sign(raw, b"test", domain, key.read_bytes(),
                              include_headers=headers, length=length)
        return signature + raw

    return sign
