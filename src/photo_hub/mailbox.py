"""Gmail IMAP/SMTP integration."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.policy import default
import imaplib
import smtplib
from typing import Iterable, List, Tuple

from .config import GmailConfig


@dataclass(frozen=True)
class MailItem:
    uid: str
    message: Message


class GmailMailbox:
    def __init__(self, config: GmailConfig):
        self.config = config

    def _imap(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        client.login(self.config.email, self.config.app_password)
        return client

    def inbox(self, since_uid: str | None = None) -> List[MailItem]:
        with self._imap() as client:
            client.select("INBOX")
            if since_uid is None:
                status, data = client.uid("search", None, "ALL")
            else:
                next_uid = str(int(since_uid) + 1)
                status, data = client.uid("search", None, "UID", "{}:*".format(next_uid))
            if status != "OK":
                return []
            uids = data[0].split()
            items: List[MailItem] = []
            for raw_uid in uids:
                uid = raw_uid.decode("ascii")
                fetch_status, fetch_data = client.uid("fetch", raw_uid, "(RFC822)")
                if fetch_status != "OK":
                    continue
                for entry in fetch_data:
                    if isinstance(entry, tuple):
                        message = BytesParser(policy=default).parsebytes(entry[1])
                        items.append(MailItem(uid=uid, message=message))
                        break
            return items

    def unseen(self, since_uid: str | None = None) -> List[MailItem]:
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
        with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port) as smtp:
            smtp.login(self.config.email, self.config.app_password)
            smtp.send_message(message)


def summary_subject(prefix: str) -> str:
    return "Photo Hub: {}".format(prefix)
