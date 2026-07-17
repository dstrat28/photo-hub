"""SQLite persistence for Photo Hub."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import List, Optional


@dataclass(frozen=True)
class PendingTVJob:
    message_uid: str
    sender: str
    image_path: Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.init()

    def init(self) -> None:
        self.conn.executescript(
            """
            create table if not exists processed_messages (
                uid text primary key,
                status text not null,
                error text,
                created_at text not null default current_timestamp
            );
            create table if not exists pending_tv (
                id integer primary key check (id = 1),
                message_uid text not null,
                sender text not null,
                image_path text not null,
                updated_at text not null default current_timestamp
            );
            create table if not exists tv_state (
                id integer primary key check (id = 1),
                current_content_id text,
                updated_at text not null default current_timestamp
            );
            """
        )
        self.conn.commit()

    def has_processed(self, uid: str) -> bool:
        row = self.conn.execute(
            "select uid from processed_messages where uid = ?", (uid,)
        ).fetchone()
        return row is not None

    def mark_processed(self, uid: str, status: str, error: Optional[str] = None) -> None:
        self.conn.execute(
            """
            insert into processed_messages(uid, status, error)
            values (?, ?, ?)
            on conflict(uid) do update set status = excluded.status, error = excluded.error
            """,
            (uid, status, error),
        )
        self.conn.commit()

    def recent_processed(self, limit: int = 10) -> List[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                select uid, status, error, created_at
                from processed_messages
                order by created_at desc
                limit ?
                """,
                (limit,),
            )
        )

    def max_processed_uid(self) -> Optional[str]:
        row = self.conn.execute(
            """
            select max(cast(uid as integer)) as max_uid
            from processed_messages
            where uid glob '[0-9]*'
            """
        ).fetchone()
        if row is None or row["max_uid"] is None:
            return None
        return str(row["max_uid"])

    def replace_pending_tv(self, job: PendingTVJob) -> Optional[Path]:
        previous = self.get_pending_tv()
        self.conn.execute(
            """
            insert into pending_tv(id, message_uid, sender, image_path)
            values (1, ?, ?, ?)
            on conflict(id) do update set
                message_uid = excluded.message_uid,
                sender = excluded.sender,
                image_path = excluded.image_path,
                updated_at = current_timestamp
            """,
            (job.message_uid, job.sender, str(job.image_path)),
        )
        self.conn.commit()
        if previous and previous.image_path != job.image_path:
            return previous.image_path
        return None

    def get_pending_tv(self) -> Optional[PendingTVJob]:
        row = self.conn.execute("select * from pending_tv where id = 1").fetchone()
        if row is None:
            return None
        return PendingTVJob(
            message_uid=row["message_uid"],
            sender=row["sender"],
            image_path=Path(row["image_path"]),
        )

    def clear_pending_tv(self) -> None:
        self.conn.execute("delete from pending_tv where id = 1")
        self.conn.commit()

    def get_current_tv_content_id(self) -> Optional[str]:
        row = self.conn.execute("select current_content_id from tv_state where id = 1").fetchone()
        return None if row is None else row["current_content_id"]

    def set_current_tv_content_id(self, content_id: Optional[str]) -> None:
        self.conn.execute(
            """
            insert into tv_state(id, current_content_id)
            values (1, ?)
            on conflict(id) do update set current_content_id = excluded.current_content_id,
                updated_at = current_timestamp
            """,
            (content_id,),
        )
        self.conn.commit()
