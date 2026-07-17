from email.message import EmailMessage

from photo_hub.config import AppConfig, AuraConfig, GmailConfig, PathsConfig, TVConfig
from photo_hub.mailbox import MailItem
from photo_hub.service import PhotoHubService


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
