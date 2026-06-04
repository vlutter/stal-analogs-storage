"""SQLite repository for agent sessions, messages and attached files."""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Session:
    id: int
    user_id: str
    created_at: datetime
    last_message_at: datetime
    status: str


@dataclass
class Message:
    id: int
    session_id: int
    role: str
    content: str
    tool_name: str | None
    tool_arguments: str | None
    tool_result: str | None
    created_at: datetime


@dataclass
class AttachedFile:
    id: int
    session_id: int
    filename: str
    s3_key: str
    content_type: str | None
    size_bytes: int
    created_at: datetime


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class SessionsRepository:
    """Thread-safe SQLite store for agent sessions, messages and attached files."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_message_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user_status
                    ON sessions(user_id, status);

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_name TEXT,
                    tool_arguments TEXT,
                    tool_result TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);

                CREATE TABLE IF NOT EXISTS attached_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    s3_key TEXT NOT NULL,
                    content_type TEXT,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_attached_files_session
                    ON attached_files(session_id, id);
                """
            )
        logger.info("SessionsRepository initialized at %s", self._db_path)

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            created_at=_parse_dt(row["created_at"]),
            last_message_at=_parse_dt(row["last_message_at"]),
            status=row["status"],
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            tool_name=row["tool_name"],
            tool_arguments=row["tool_arguments"],
            tool_result=row["tool_result"],
            created_at=_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_attached_file(row: sqlite3.Row) -> AttachedFile:
        return AttachedFile(
            id=row["id"],
            session_id=row["session_id"],
            filename=row["filename"],
            s3_key=row["s3_key"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            created_at=_parse_dt(row["created_at"]),
        )

    def get_active_session(self, user_id: str, ttl: timedelta) -> tuple[Session | None, int | None]:
        """Return active session if it exists and is not expired.

        When the session is expired it is closed and its id is returned as the second
        value so the caller can clean up attached files.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, created_at, last_message_at, status
                FROM sessions
                WHERE user_id = ? AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

            if row is None:
                return None, None

            session = self._row_to_session(row)
            now = datetime.now(timezone.utc)
            if now - session.last_message_at > ttl:
                conn.execute(
                    "UPDATE sessions SET status = 'closed' WHERE id = ?",
                    (session.id,),
                )
                logger.info(
                    "Session %d for user=%s expired (TTL %s) and was closed",
                    session.id, user_id, ttl,
                )
                return None, session.id
            return session, None

    def create_session(self, user_id: str) -> Session:
        now_iso = _utcnow_iso()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO sessions (user_id, created_at, last_message_at, status)
                VALUES (?, ?, ?, 'active')
                """,
                (user_id, now_iso, now_iso),
            )
            session_id = cur.lastrowid
            row = conn.execute(
                "SELECT id, user_id, created_at, last_message_at, status FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        logger.info("Created session %d for user=%s", session_id, user_id)
        return self._row_to_session(row)

    def get_active_session_ids(self, user_id: str) -> list[int]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM sessions WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchall()
        return [row["id"] for row in rows]

    def close_active_sessions(self, user_id: str) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE sessions SET status = 'closed' WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            return cur.rowcount or 0

    def touch_session(self, session_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET last_message_at = ? WHERE id = ?",
                (_utcnow_iso(), session_id),
            )

    def append_message(
        self,
        session_id: int,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_arguments: str | None = None,
        tool_result: str | None = None,
    ) -> Message:
        now_iso = _utcnow_iso()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO messages (
                    session_id, role, content, tool_name, tool_arguments, tool_result, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, tool_name, tool_arguments, tool_result, now_iso),
            )
            conn.execute(
                "UPDATE sessions SET last_message_at = ? WHERE id = ?",
                (now_iso, session_id),
            )
            row = conn.execute(
                """
                SELECT id, session_id, role, content, tool_name, tool_arguments, tool_result, created_at
                FROM messages WHERE id = ?
                """,
                (cur.lastrowid,),
            ).fetchone()
        return self._row_to_message(row)

    def get_last_messages(self, session_id: int, limit: int) -> list[Message]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, tool_name, tool_arguments, tool_result, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        messages = [self._row_to_message(row) for row in rows]
        messages.reverse()
        return messages

    def add_attached_file(
        self,
        session_id: int,
        filename: str,
        s3_key: str,
        content_type: str | None,
        size_bytes: int,
    ) -> AttachedFile:
        now_iso = _utcnow_iso()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO attached_files (
                    session_id, filename, s3_key, content_type, size_bytes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, filename, s3_key, content_type, size_bytes, now_iso),
            )
            row = conn.execute(
                """
                SELECT id, session_id, filename, s3_key, content_type, size_bytes, created_at
                FROM attached_files WHERE id = ?
                """,
                (cur.lastrowid,),
            ).fetchone()
        return self._row_to_attached_file(row)

    def get_last_attached_file(self, session_id: int) -> AttachedFile | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, filename, s3_key, content_type, size_bytes, created_at
                FROM attached_files
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return self._row_to_attached_file(row) if row else None

    def list_attached_files(self, session_id: int) -> list[AttachedFile]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, filename, s3_key, content_type, size_bytes, created_at
                FROM attached_files
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_attached_file(row) for row in rows]

    def delete_attached_files_for_session(self, session_id: int) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM attached_files WHERE session_id = ?",
                (session_id,),
            )
            return cur.rowcount or 0
