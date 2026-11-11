"""Authenticate original message bytes, never claimed authentication headers."""

from email.message import Message
from email.errors import MultipartInvariantViolationDefect
from email.parser import BytesHeaderParser, BytesParser
from email.policy import default
import json
import ssl
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener

import dkim
import dns.rdata
import dns.rdataclass
import dns.rdatatype


class AuthenticationError(RuntimeError):
    """A message does not have an acceptable authenticated sender."""


class AuthenticationUnavailable(RuntimeError):
    """Authentication infrastructure failed; leave the message for a later pass."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def lookup_dkim_key(name: bytes, timeout: int = 5) -> bytes:
    """Use authenticated HTTPS DNS so a local DNS interceptor cannot replace keys."""
    query = urlencode({"name": name.decode("ascii"), "type": "TXT",
                       "edns_client_subnet": "0.0.0.0/0"})
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open("https://dns.google/resolve?" + query, timeout=timeout) as response:
            raw = response.read(65_537)
        result = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise AuthenticationUnavailable("DKIM key lookup is unavailable.") from exc
    if len(raw) > 65_536:
        raise AuthenticationError("DKIM DNS response is too large.")
    if result.get("Status") not in {0, 3} or result.get("TC"):
        raise AuthenticationUnavailable("DKIM key lookup is unavailable.")
    if result.get("Status") != 0:
        raise AuthenticationError("DKIM DNS lookup failed.")
    records = [answer for answer in result.get("Answer", []) if answer.get("type") == 16]
    if len(records) != 1:
        raise AuthenticationError("DKIM key is missing or ambiguous.")
    record = dns.rdata.from_text(dns.rdataclass.IN, dns.rdatatype.TXT, records[0]["data"])
    return b"".join(record.strings)


def message_headers(raw: bytes) -> Message:
    ends = [position for separator in (b"\r\n\r\n", b"\n\n")
            if (position := raw.find(separator)) >= 0]
    if not ends or min(ends) > 65_536:
        raise AuthenticationError("Email headers are missing or too large.")
    # Supply only the header block; do not copy or recursively parse the MIME body.
    header_end = min(ends)
    message = BytesHeaderParser(policy=default).parsebytes(raw[:header_end] + b"\r\n\r\n")
    # Python 3.9 reports the deliberately omitted multipart body as a defect.
    if any(not isinstance(defect, MultipartInvariantViolationDefect) for defect in message.defects):
        raise AuthenticationError("Malformed email message.")
    return message


def authenticate_message(raw: bytes, allowed_senders: Iterable[str]) -> Message:
    message = message_headers(raw)
    protected = {"from", "subject", "content-type", "content-transfer-encoding",
                 "content-disposition", "mime-version"}
    for header in protected:
        values = message.get_all(header, [])
        if len(values) > 1 or any(getattr(value, "defects", ()) for value in values):
            raise AuthenticationError("Ambiguous email headers.")
    from_header = message.get("From")
    addresses = getattr(from_header, "addresses", ())
    if len(addresses) != 1:
        raise AuthenticationError("Email must have exactly one sender.")
    address = addresses[0]
    sender = address.addr_spec.lower()
    if not address.domain or sender not in {item.lower() for item in allowed_senders}:
        raise AuthenticationError("Sender is not authorized for Photo Hub.")
    domain = address.domain.encode("idna").lower()
    required = {name.encode("ascii") for name in protected if message.get_all(name)}
    verifier = dkim.DKIM(raw, timeout=5)
    # Use the same raw representation as the cryptographic verifier. Decoding an
    # RFC2047 encoded word here could change d=/h= while verification uses raw tags.
    signatures = [value for name, value in verifier.headers if name.lower() == b"dkim-signature"]
    if not 1 <= len(signatures) <= 5:
        raise AuthenticationError("Email requires a valid sender-domain DKIM signature.")
    unavailable = False
    for index, header in enumerate(signatures):
        try:
            fields = dkim.util.parse_tag_value(header)
            signed_headers = {name.strip().lower() for name in fields.get(b"h", b"").split(b":")}
            if (fields.get(b"d", b"").lower() != domain or b"l" in fields
                    or fields.get(b"a") != b"rsa-sha256" or not required <= signed_headers):
                continue
            if verifier.verify(idx=index, dnsfunc=lookup_dkim_key):
                try:
                    return BytesParser(policy=default).parsebytes(raw)
                except (RecursionError, ValueError) as exc:
                    raise AuthenticationError("Malformed MIME message.") from exc
        except AuthenticationUnavailable:
            unavailable = True
        except Exception:
            # Malformed signatures, unavailable keys and failed verification all fail closed.
            continue
    if unavailable:
        raise AuthenticationUnavailable("DKIM key lookup is unavailable.")
    raise AuthenticationError("Email requires a valid sender-domain DKIM signature.")
