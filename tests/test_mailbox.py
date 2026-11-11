from email.message import EmailMessage
import re
import ssl

import pytest

from photo_hub.config import GmailConfig
from photo_hub.mailbox import GmailMailbox


def mailbox(**kwargs):
    return GmailMailbox(GmailConfig("hub@example.com", "test-only-password"), **kwargs)


class FakeIMAP:
    def __init__(self, bodies):
        self.bodies = bodies
        self.calls = []
        self.reported = {uid: len(raw) for uid, raw in bodies.items()}
        self.failure_uid = None
        self.closed = False

    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def select(self, name): return "OK", [str(len(self.bodies)).encode()]
    def response(self, name): return name, [str(max(self.bodies) + 1).encode()]
    def fetch(self, sequence, fields): return "OK", [b"1 (UID %d)" % min(self.bodies)]

    def uid(self, command, *args):
        self.calls.append((command, args))
        if command == "search":
            lower, upper = map(int, args[-1].split(":"))
            return "OK", [b" ".join(str(uid).encode() for uid in sorted(self.bodies)
                                     if lower <= uid <= upper)]
        uid, fields = int(args[0]), args[1]
        if self.failure_uid == uid:
            return "NO", []
        if fields == "(UID RFC822.SIZE)":
            return "OK", [b"1 (UID %d RFC822.SIZE %d)" % (uid, self.reported[uid])]
        limit = int(re.search(r"<0\.(\d+)>", fields).group(1))
        raw = self.bodies[uid][:limit]
        return "OK", [(b"1 (UID %d BODY[]<0> {%d})" % (uid, len(raw)), raw), b")"]


def connect(monkeypatch, client, **kwargs):
    mail = mailbox(**kwargs)
    monkeypatch.setattr(mail, "_imap", lambda: client)
    return mail


def body(uid): return b"From: anyone@example.com\r\n\r\nphoto %d" % uid


def test_retrieval_is_lazy_and_bounded_by_count(monkeypatch):
    client = FakeIMAP({uid: body(uid) for uid in range(1, 101)})
    mail = connect(monkeypatch, client, batch_size=2)
    items = mail.inbox()
    assert client.calls == []
    assert next(items).uid == "1"
    assert not any(args[0] == "2" for command, args in client.calls if command == "fetch")
    assert [item.uid for item in items] == ["2"]
    assert client.closed


def test_oversized_message_rejected_without_body_fetch(monkeypatch):
    client = FakeIMAP({1: body(1), 2: body(2)})
    client.reported[1] = 1000
    mail = connect(monkeypatch, client, max_message_bytes=100)
    items = list(mail.inbox())
    assert items[0].rejection and items[0].raw_message == b""
    assert items[1].raw_message == body(2)
    assert not any(args[0] == "1" and "BODY" in args[1]
                   for command, args in client.calls if command == "fetch")


def test_actual_body_is_limited_and_checked(monkeypatch):
    client = FakeIMAP({1: b"x" * 1000})
    client.reported[1] = 50
    mail = connect(monkeypatch, client, max_message_bytes=100)
    item = next(mail.inbox())
    assert item.rejection
    assert ("fetch", ("1", "(UID BODY.PEEK[]<0.101>)")) in client.calls


def test_aggregate_byte_budget_defers_next_body(monkeypatch):
    client = FakeIMAP({1: body(1), 2: body(2)})
    mail = connect(monkeypatch, client, max_message_bytes=100, max_batch_bytes=100)
    client.bodies = {1: b"x" * 60, 2: b"x" * 60}
    client.reported = {1: 60, 2: 60}
    assert [item.uid for item in mail.inbox()] == ["1"]
    assert not any(args[0] == "2" and "BODY" in args[1]
                   for command, args in client.calls if command == "fetch")


def test_partial_fetch_also_enforces_remaining_byte_budget(monkeypatch):
    client = FakeIMAP({1: b"a" * 60, 2: b"b" * 100})
    client.reported[2] = 10
    mail = connect(monkeypatch, client, max_message_bytes=100, max_batch_bytes=100)
    items = list(mail.inbox())
    assert items[1].rejection
    assert ("fetch", ("2", "(UID BODY.PEEK[]<0.41>)")) in client.calls


def test_unsigned_nested_mime_never_parsed_during_retrieval(monkeypatch):
    raw = b"From: you@example.com\r\nSubject: frame\r\nContent-Type: multipart/mixed; boundary=b0\r\n\r\n"
    for index in range(1000):
        raw += ("--b%d\r\nContent-Type: multipart/mixed; boundary=b%d\r\n\r\n"
                % (index, index + 1)).encode()
    mail = connect(monkeypatch, FakeIMAP({1: raw}))
    item = next(mail.inbox())
    assert item.raw_message == raw and not item.rejection
    from photo_hub.intake import IntakeError, parse_submission
    with pytest.raises(IntakeError, match="DKIM"):
        parse_submission(item.raw_message, ["you@example.com"], 100)


def test_header_budget_rejection(monkeypatch):
    raw = b"From: you@example.com\r\nX-Padding: " + b"a" * 65_536 + b"\r\n\r\nbody"
    mail = connect(monkeypatch, FakeIMAP({1: raw}))
    assert next(mail.inbox()).rejection == "Email headers are missing or too large."


def test_uid_windows_handle_gaps_and_cursor(monkeypatch):
    client = FakeIMAP({9: body(9), 2500: body(2500), 3500: body(3500)})
    mail = connect(monkeypatch, client)
    assert [item.uid for item in mail.inbox("9")] == ["2500", "3500"]
    for command, args in client.calls:
        if command == "search":
            lower, upper = map(int, args[-1].split(":"))
            assert upper - lower < 1000 and "*" not in args[-1]


def test_fetch_failure_does_not_skip_lower_uid(monkeypatch):
    client = FakeIMAP({1: body(1), 2: body(2)})
    client.failure_uid = 1
    mail = connect(monkeypatch, client)
    with pytest.raises(RuntimeError, match="size"):
        list(mail.inbox())
    assert not any(args[0] == "2" for command, args in client.calls if command == "fetch")


@pytest.fixture(params=["imap", "smtp"])
def transport_context(request, monkeypatch):
    contexts = []
    class Client:
        def __init__(self, host, port, **kwargs): contexts.append(next(iter(kwargs.values())))
        def login(self, *args): pass
        def send_message(self, *args): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    mail = mailbox()
    if request.param == "imap":
        monkeypatch.setattr("photo_hub.mailbox.imaplib.IMAP4_SSL", Client)
        mail._imap()
    else:
        monkeypatch.setattr("photo_hub.mailbox.smtplib.SMTP_SSL", Client)
        mail._send(EmailMessage())
    context = contexts[0]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    return context


@pytest.mark.parametrize("trusted,hostname,valid", [(False, "localhost", False),
                                                   (True, "wrong.invalid", False),
                                                   (True, "localhost", True)])
def test_transport_tls_handshake(transport_context, key_material, trusted, hostname, valid):
    key, certificate, _ = key_material
    if trusted:
        transport_context.load_verify_locations(cafile=str(certificate))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(certificate), str(key))
    client_in, client_out, server_in, server_out = [ssl.MemoryBIO() for _ in range(4)]
    client = transport_context.wrap_bio(client_in, client_out, server_hostname=hostname)
    server = server_context.wrap_bio(server_in, server_out, server_side=True)

    def handshake():
        for _ in range(10):
            try:
                client.do_handshake()
                return
            except ssl.SSLWantReadError:
                pass
            server_in.write(client_out.read())
            try: server.do_handshake()
            except ssl.SSLWantReadError: pass
            client_in.write(server_out.read())
        pytest.fail("TLS handshake did not finish")

    if valid:
        handshake()
    else:
        with pytest.raises(ssl.SSLCertVerificationError): handshake()
