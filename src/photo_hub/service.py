"""Photo Hub service orchestration."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Optional

from .config import AppConfig
from .images import normalize_jpeg, tv_canvas_jpeg
from .intake import IntakeError, image_attachments, normalize_sender, parse_submission
from .mailbox import GmailMailbox, MailItem
from .samsung import SamsungConfig, SamsungError, SamsungFrame
from .store import PendingTVJob, Store


class PhotoHubService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.state_dir = config.paths.state_dir
        self.image_dir = self.state_dir / "images"
        self.image_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.store = Store(self.state_dir / "photo-hub.sqlite3")
        self.mail = GmailMailbox(config.gmail)
        self.tv = SamsungFrame(
            SamsungConfig(
                host=config.tv.host,
                client_name=config.tv.client_name,
                timeout_seconds=config.tv.timeout_seconds,
            )
        )

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(self.config.poll_interval_seconds)

    def run_once(self) -> None:
        self.process_pending_tv()
        for item in self.mail.unseen(self.store.max_processed_uid()):
            if self.store.has_processed(item.uid):
                continue
            self.process_mail(item)
        self.process_pending_tv()

    def process_mail(self, item: MailItem) -> None:
        try:
            ignore_status = self.ignore_status(item)
            if ignore_status:
                self.store.mark_processed(item.uid, ignore_status)
                self.mail.mark_done(item.uid)
                return
            submission = parse_submission(
                item.message,
                self.config.allowed_senders,
                self.config.max_attachment_bytes,
            )
            if submission.destination in {"frame", "both"}:
                normalized = normalize_jpeg(submission.attachment.data)
                self.mail.send_photo(
                    self.config.aura.frame_email,
                    "Photo Hub Aura submission",
                    "photo-hub.jpg",
                    normalized,
                )
            if submission.destination in {"tv", "both"}:
                tv_path = self.image_dir / "{}-tv.jpg".format(item.uid)
                tv_path.write_bytes(tv_canvas_jpeg(submission.attachment.data))
                old_path = self.store.replace_pending_tv(
                    PendingTVJob(item.uid, submission.sender, tv_path)
                )
                if old_path and old_path.exists():
                    old_path.unlink()
            self.store.mark_processed(item.uid, "accepted")
            self.mail.mark_done(item.uid)
        except IntakeError as exc:
            self.store.mark_processed(item.uid, "rejected", str(exc))
            self.mail.mark_done(item.uid)
        except Exception as exc:
            self.store.mark_processed(item.uid, "failed", str(exc))
            self.mail.mark_failed(item.uid)

    def ignore_status(self, item: MailItem) -> Optional[str]:
        sender = normalize_sender(item.message.get("From", ""))
        if sender == self.config.gmail.email.lower():
            return "ignored_self"
        if sender not in self.config.allowed_senders and not any(
            image_attachments(item.message)
        ):
            return "ignored_non_submission"
        return None

    def process_pending_tv(self) -> None:
        if not self.config.tv.enabled:
            return
        pending = self.store.get_pending_tv()
        if pending is None:
            return
        try:
            previous = self.store.get_current_tv_content_id()
            content_id = self.tv.upload_select_replace(pending.image_path, previous)
            self.store.set_current_tv_content_id(content_id)
            self.store.clear_pending_tv()
            if pending.image_path.exists():
                pending.image_path.unlink()
        except SamsungError:
            return
