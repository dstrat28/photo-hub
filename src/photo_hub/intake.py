"""Email intake parsing."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
from email.utils import parseaddr
from typing import Iterable, Optional


VALID_DESTINATIONS = {"frame", "tv", "both"}
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/tiff", "image/heic", "image/heif"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif"}


class IntakeError(RuntimeError):
    """A submitted email cannot be accepted."""


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class Submission:
    sender: str
    destination: str
    attachment: Attachment
    subject: str


def normalize_sender(value: str) -> str:
    _, address = parseaddr(value or "")
    return address.lower()


def parse_destination(subject: str, body: str) -> Optional[str]:
    candidates = []
    for source in (subject or "", first_nonempty_line(body or "")):
        token = source.strip().split(maxsplit=1)[0].lower() if source.strip() else ""
        token = token.rstrip(":,-")
        if token in VALID_DESTINATIONS:
            candidates.append(token)
    if not candidates:
        return None
    if len(set(candidates)) > 1:
        raise IntakeError("Destination is ambiguous; use one of frame, tv, or both.")
    return candidates[0]


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line
    return ""


def text_body(message: Message) -> str:
    if message.is_multipart():
        parts = []
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                parts.append(payload.decode(charset, errors="replace"))
        return "\n".join(parts)
    payload = message.get_payload(decode=True) or b""
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def is_image_part(part: Message) -> bool:
    filename = part.get_filename() or ""
    lowered = filename.lower()
    return part.get_content_type().lower() in IMAGE_MIME_TYPES or any(
        lowered.endswith(ext) for ext in IMAGE_EXTENSIONS
    )


def image_attachments(message: Message) -> Iterable[Attachment]:
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if payload is None or not is_image_part(part):
            continue
        yield Attachment(
            filename=part.get_filename() or "photo",
            content_type=part.get_content_type().lower(),
            data=payload,
        )


def parse_submission(
    message: Message,
    allowed_senders: Iterable[str],
    max_attachment_bytes: int,
) -> Submission:
    sender = normalize_sender(message.get("From", ""))
    if sender not in {item.lower() for item in allowed_senders}:
        raise IntakeError("Sender is not authorized for Photo Hub.")

    subject = message.get("Subject", "")
    destination = parse_destination(subject, text_body(message))
    if destination is None:
        raise IntakeError("Missing destination. Start the subject/body with frame, tv, or both.")

    attachments = list(image_attachments(message))
    if len(attachments) != 1:
        raise IntakeError("Attach exactly one image.")
    attachment = attachments[0]
    if len(attachment.data) > max_attachment_bytes:
        raise IntakeError("Image attachment is too large.")
    return Submission(sender=sender, destination=destination, attachment=attachment, subject=subject)
