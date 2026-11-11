"""Gmail IMAP/SMTP integration."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage, Message
import imaplib
import re
import smtplib
import ssl
from typing import Iterator, Optional

from .config import GmailConfig
from .authentication import AuthenticationError, message_headers


@dataclass(frozen=True)
class MailItem:
    uid: str
    message: Message
    raw_message: bytes = b""
    rejection: Optional[str] = None


class GmailMailbox:
    def __init__(self, config: GmailConfig, max_message_bytes: int = 35_000_000,
                 batch_size: int = 25, max_batch_bytes: int = 64_000_000):
        self.config = config
        if not 0 < max_message_bytes <= max_batch_bytes or batch_size <= 0:
            raise ValueError("Invalid mailbox retrieval limits")
        self.max_message_bytes = max_message_bytes
        self.batch_size = batch_size
        self.max_batch_bytes = max_batch_bytes

    def _imap(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port,
                                  ssl_context=ssl.create_default_context())
        client.login(self.config.email, self.config.app_password)
        return client

    def inbox(self, since_uid: str | None = None) -> Iterator[MailItem]:
        with self._imap() as client:
            status, count = client.select("INBOX")
            if status != "OK":
                raise RuntimeError("Could not select INBOX")
            if int(count[0]) == 0:
                return
            # Fixed UID windows bound SEARCH responses, including on first startup.
            status, first = client.fetch("1", "(UID)")
            first_uid = self._number(first, rb"\bUID (\d+)") if status == "OK" else None
            _, uidnext = client.response("UIDNEXT")
            if first_uid is None or not uidnext or not uidnext[0]:
                raise RuntimeError("Could not determine mailbox UID range")
            start = max(first_uid, int(since_uid or "0") + 1)
            stop = int(uidnext[0])
            processed = total_bytes = 0
            for lower in range(start, stop, 1000):
                upper = min(lower + 999, stop - 1)
                status, data = client.uid("search", None, "UID", "{}:{}".format(lower, upper))
                if status != "OK":
                    raise RuntimeError("Could not search INBOX")
                uids = sorted({int(uid) for uid in data[0].split()})
                for uid_number in uids:
                    if not lower <= uid_number <= upper:
                        raise RuntimeError("Unexpected UID in mailbox search")
                    if processed >= self.batch_size:
                        return
                    uid = str(uid_number)
                    status, metadata = client.uid("fetch", uid, "(UID RFC822.SIZE)")
                    size = self._number(metadata, rb"\bRFC822.SIZE (\d+)")
                    returned_uid = self._number(metadata, rb"\bUID (\d+)")
                    if status != "OK" or size is None or returned_uid != uid_number:
                        # Stop rather than skipping a lower UID and losing it to the cursor.
                        raise RuntimeError("Could not read message size")
                    processed += 1
                    if size > self.max_message_bytes:
                        yield MailItem(uid, Message(), rejection="Email message is too large.")
                        continue
                    if total_bytes + size > self.max_batch_bytes:
                        return
                    limit = min(self.max_message_bytes, self.max_batch_bytes - total_bytes) + 1
                    status, fetched = client.uid("fetch", uid, "(UID BODY.PEEK[]<0.{}>)".format(limit))
                    entries = [entry for entry in fetched if isinstance(entry, tuple)]
                    if status != "OK" or len(entries) != 1:
                        raise RuntimeError("Could not retrieve message")
                    header, raw = entries[0]
                    if self._number([header], rb"\bUID (\d+)") != uid_number:
                        raise RuntimeError("Unexpected UID in message response")
                    total_bytes += len(raw)
                    if len(raw) > self.max_message_bytes or len(raw) != size:
                        yield MailItem(uid, Message(), rejection="Email size is invalid or too large.")
                    else:
                        try:
                            message = message_headers(raw)
                        except AuthenticationError as exc:
                            yield MailItem(uid, Message(), rejection=str(exc))
                        else:
                            yield MailItem(uid, message, raw)
                    # Do not retain the previous body while downloading the next one.
                    del raw, entries, fetched

    @staticmethod
    def _number(data, pattern: bytes) -> Optional[int]:
        for entry in data:
            if isinstance(entry, bytes):
                match = re.search(pattern, entry)
                if match:
                    return int(match.group(1))
        return None

    def unseen(self, since_uid: str | None = None) -> Iterator[MailItem]:
        return self.inbox(since_uid)

    def mark_done(self, uid: str) -> None:
        with self._imap() as client:
            client.select("INBOX")
            client.uid("store", uid, "+FLAGS", r"(\Seen)")
            client.uid("store", uid, "-X-GM-LABELS", r"(\Inbox)")

    def mark_failed(self, uid: str) -> None:
        with self._imap() as client:
            client.select("INBOX")
            client.uid("store", uid, "+FLAGS", r"(\Seen)")

    def send_text(self, to_addr: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.config.email
        message["To"] = to_addr
        message["Subject"] = subject
        message.set_content(body)
        self._send(message)

    def send_photo(self, to_addr: str, subject: str, filename: str, data: bytes) -> None:
        message = EmailMessage()
        message["From"] = self.config.email
        message["To"] = to_addr
        message["Subject"] = subject
        message.set_content("Photo Hub submission attached.")
        message.add_attachment(data, maintype="image", subtype="jpeg", filename=filename)
        self._send(message)

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port,
                              context=ssl.create_default_context()) as smtp:
            smtp.login(self.config.email, self.config.app_password)
            smtp.send_message(message)


def summary_subject(prefix: str) -> str:
    return "Photo Hub: {}".format(prefix)
