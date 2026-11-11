from email.message import EmailMessage

from photo_hub.config import AppConfig, AuraConfig, GmailConfig, PathsConfig, TVConfig
from photo_hub.mailbox import MailItem
from photo_hub.service import PhotoHubService
from photo_hub.authentication import AuthenticationUnavailable
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
from PIL import Image
import pytest


def service_with_config(tmp_path):
    service = PhotoHubService.__new__(PhotoHubService)
    service.config = AppConfig(
        gmail=GmailConfig(email="photo@example.com", app_password="test-app-password"),
        aura=AuraConfig(frame_email="frame@example.com"),
        tv=TVConfig(host="192.168.1.50"),
        paths=PathsConfig(state_dir=tmp_path),
        allowed_senders=["user@example.com"],
    )
    return service


def test_ignore_status_ignores_service_sender(tmp_path):
    service = service_with_config(tmp_path)
    message = EmailMessage()
    message["From"] = "photo@example.com"
    message["Subject"] = "Photo Hub: accepted"
    message.set_content("Accepted.")

    assert service.ignore_status(MailItem("1", message)) == "ignored_self"


def test_ignore_status_ignores_automated_non_submission(tmp_path):
    service = service_with_config(tmp_path)
    message = EmailMessage()
    message["From"] = "Google <no-reply@accounts.google.com>"
    message["Subject"] = "Security alert"
    message.set_content("Security alert.")

    assert service.ignore_status(MailItem("1", message)) == "ignored_non_submission"


def test_ignore_status_does_not_ignore_unauthorized_photo(tmp_path):
    service = service_with_config(tmp_path)
    message = EmailMessage()
    message["From"] = "other@example.com"
    message["Subject"] = "frame"
    message.set_content("frame")
    message.add_attachment(b"fake", maintype="image", subtype="jpeg", filename="x.jpg")

    assert service.ignore_status(MailItem("1", message)) is None


class FakeMail:
    def __init__(self, items=()):
        self.items = items
        self.sent = []
        self.done = []
    def unseen(self, since): return iter(self.items)
    def send_photo(self, *args): self.sent.append(args)
    def mark_done(self, uid): self.done.append(uid)
    def mark_failed(self, uid): pytest.fail("Unexpected delivery failure")


def delivery_service(tmp_path):
    config = service_with_config(tmp_path).config
    service = PhotoHubService(config)
    service.mail = FakeMail()
    return service


def photo_message(destination):
    message = EmailMessage()
    message["From"] = "user@example.com"
    message["Subject"] = destination
    message.set_content("family photo")
    output = BytesIO()
    Image.new("RGB", (16, 16), (240, 40, 30)).save(output, "PNG")
    message.add_attachment(output.getvalue(), maintype="image", subtype="png", filename="photo.png")
    return message


@pytest.mark.parametrize("destination", ["frame", "tv", "both"])
def test_authenticated_photo_keeps_delivery_routes(tmp_path, sign_email, destination):
    service = delivery_service(tmp_path)
    raw = sign_email(photo_message(destination))
    item = MailItem("1", BytesParser(policy=default).parsebytes(raw), raw)
    service.process_mail(item)
    assert service.store.recent_processed()[0]["status"] == "accepted"
    assert bool(service.mail.sent) == (destination in {"frame", "both"})
    assert bool(service.store.get_pending_tv()) == (destination in {"tv", "both"})
    if service.mail.sent:
        assert service.mail.sent[0][0] == "frame@example.com"
        assert service.mail.sent[0][-1].startswith(b"\xff\xd8")
    assert service.mail.done == ["1"]


def test_wire_size_rejection_is_checkpointed_and_archived(tmp_path):
    service = delivery_service(tmp_path)
    service.process_mail(MailItem("1", EmailMessage(), rejection="Email message is too large."))
    assert service.store.recent_processed()[0]["status"] == "rejected"
    assert service.store.max_processed_uid() == "1"
    assert service.mail.done == ["1"] and service.mail.sent == []


def test_spoofed_email_never_reaches_delivery(tmp_path):
    service = delivery_service(tmp_path)
    message = photo_message("both")
    message["Authentication-Results"] = "mx.google.com; dkim=pass; dmarc=pass"
    service.process_mail(MailItem("1", message, message.as_bytes()))
    assert service.store.recent_processed()[0]["status"] == "rejected"
    assert service.store.get_pending_tv() is None and service.mail.sent == []


def test_dns_outage_does_not_advance_cursor_past_pending_mail(tmp_path, monkeypatch):
    service = delivery_service(tmp_path)
    message = photo_message("frame")
    service.mail.items = [MailItem(str(uid), message, message.as_bytes()) for uid in [1, 2]]
    monkeypatch.setattr(service, "process_pending_tv", lambda: None)
    def unavailable(*args): raise AuthenticationUnavailable("offline")
    monkeypatch.setattr("photo_hub.service.parse_submission", unavailable)
    service.run_once()
    assert service.store.max_processed_uid() is None
    assert service.mail.done == [] and service.mail.sent == []


def test_untrusted_message_copy_cannot_override_signed_bytes(tmp_path, sign_email):
    service = delivery_service(tmp_path)
    raw = sign_email(photo_message("frame"))
    service.process_mail(MailItem("1", photo_message("both"), raw))
    assert len(service.mail.sent) == 1 and service.store.get_pending_tv() is None
