from email.message import EmailMessage
import json
import ssl
from urllib.error import URLError

import pytest

from photo_hub.authentication import AuthenticationUnavailable, lookup_dkim_key
from photo_hub.intake import IntakeError, parse_submission


def email():
    message = EmailMessage()
    message["From"] = "Family <you@example.com>"
    message["Subject"] = "frame"
    message.set_content("hello")
    message.add_attachment(b"image", maintype="image", subtype="jpeg", filename="photo.jpg")
    return message


def accept(raw):
    return parse_submission(raw, ["you@example.com"], 100)


def test_rejects_spoofed_from_and_authentication_results():
    message = email()
    message["Authentication-Results"] = "mx.google.com; dkim=pass; dmarc=pass"
    message["Received"] = "from attacker by mx.google.com"
    with pytest.raises(IntakeError, match="DKIM"):
        accept(message.as_bytes())


def test_verifies_signed_photo_and_routing(sign_email):
    assert accept(sign_email(email())).destination == "frame"


@pytest.mark.parametrize("mutation", [
    lambda raw: raw.replace(b"Subject: frame", b"Subject: both"),
    lambda raw: raw.replace(b"aW1hZ2U=", b"ZXZpbCE="),
    lambda raw: raw + b"\r\nappended attacker data\r\n",
    lambda raw: b"From: attacker@evil.example\r\n" + raw,
    lambda raw: b"Subject: tv\r\n" + raw,
    lambda raw: b"Content-Type: text/plain\r\n" + raw,
])
def test_rejects_modified_signed_message(sign_email, mutation):
    with pytest.raises(IntakeError):
        accept(mutation(sign_email(email())))


@pytest.mark.parametrize("headers", [[b"from"], [b"from", b"subject"]])
def test_rejects_unsigned_routing_or_mime_headers(sign_email, headers):
    with pytest.raises(IntakeError, match="DKIM"):
        accept(sign_email(email(), headers=headers))


def test_rejects_partial_body_signature(sign_email):
    with pytest.raises(IntakeError, match="DKIM"):
        accept(sign_email(email(), length=True))


def test_rejects_wrong_signing_domain_before_dns(sign_email, monkeypatch):
    raw = sign_email(email(), domain=b"attacker.example")
    monkeypatch.setattr("photo_hub.authentication.lookup_dkim_key",
                        lambda *a, **kw: pytest.fail("Unaligned domain was queried"))
    with pytest.raises(IntakeError, match="DKIM"):
        accept(raw)


def test_encoded_signer_tag_is_not_treated_as_decoded_identity(sign_email, monkeypatch):
    raw = sign_email(email()).replace(b"d=example.com", b"d==?utf-8?q?example.com?=")
    monkeypatch.setattr("photo_hub.authentication.lookup_dkim_key",
                        lambda *a, **kw: pytest.fail("Encoded signer identity was trusted"))
    with pytest.raises(IntakeError, match="DKIM"):
        accept(raw)


def test_multiple_from_addresses_rejected(sign_email):
    message = email()
    message.replace_header("From", "you@example.com, attacker@example.com")
    with pytest.raises(IntakeError, match="one sender"):
        accept(sign_email(message))


def test_later_valid_signature_can_authenticate(sign_email):
    raw = b"DKIM-Signature: invalid\r\n" + sign_email(email())
    assert accept(raw).sender == "you@example.com"


def test_dns_outage_is_retryable(sign_email, monkeypatch):
    def unavailable(*args, **kwargs):
        raise AuthenticationUnavailable("offline")
    monkeypatch.setattr("photo_hub.authentication.lookup_dkim_key", unavailable)
    with pytest.raises(AuthenticationUnavailable):
        accept(sign_email(email()))


def test_signature_attempt_limit(sign_email):
    with pytest.raises(IntakeError, match="DKIM"):
        accept(b"DKIM-Signature: invalid\r\n" * 5 + sign_email(email()))


def test_https_dns_uses_verified_tls_and_bounded_response(monkeypatch):
    observed = {}
    payload = json.dumps({"Status": 0, "Answer": [{"type": 16,
                         "data": '"v=DKIM1; " "p=test"'}]}).encode()

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            observed["limit"] = limit
            return payload

    class Opener:
        def open(self, url, timeout):
            observed.update(url=url, timeout=timeout)
            return Response()

    def build(*handlers):
        context = handlers[1]._context
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert handlers[0].redirect_request(None, None, None, None, None, None) is None
        return Opener()

    monkeypatch.setattr("photo_hub.authentication.build_opener", build)
    assert lookup_dkim_key(b"test._domainkey.example.com.") == b"v=DKIM1; p=test"
    assert observed["url"].startswith("https://dns.google/resolve?")
    assert observed["timeout"] == 5 and observed["limit"] == 65_537


def test_https_dns_transport_failure_is_retryable(monkeypatch):
    class Opener:
        def open(self, *args, **kwargs): raise URLError("offline")
    monkeypatch.setattr("photo_hub.authentication.build_opener", lambda *args: Opener())
    with pytest.raises(AuthenticationUnavailable):
        lookup_dkim_key(b"test._domainkey.example.com.")
