"""High-level orchestration of agent sessions: TTL, history, attached files."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.repositories.sessions_repository import (
    AttachedFile,
    Message,
    Session,
    SessionsRepository,
)
from app.services.file_storage_service import FileStorageError, FileStorageService
from app.utils.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class AttachedFileBytes:
    filename: str
    content: bytes
    s3_key: str


class SessionService:
    def __init__(
        self,
        repository: SessionsRepository | None = None,
        file_storage: FileStorageService | None = None,
        history_limit: int | None = None,
        ttl_minutes: int | None = None,
    ) -> None:
        self._repo = repository or SessionsRepository(settings.sessions_db_path)
        self._files = file_storage
        self._history_limit = history_limit if history_limit is not None else settings.agent_history_limit
        self._ttl = timedelta(minutes=ttl_minutes if ttl_minutes is not None else settings.agent_session_ttl_minutes)

    @property
    def file_storage(self) -> FileStorageService | None:
        return self._files

    def get_or_create(self, user_id: str) -> Session:
        session = self._repo.get_active_session(user_id, self._ttl)
        if session is not None:
            return session
        return self._repo.create_session(user_id)

    def reset(self, user_id: str) -> Session:
        closed = self._repo.close_active_sessions(user_id)
        logger.info("Reset agent session for user=%s (closed=%d)", user_id, closed)
        return self._repo.create_session(user_id)

    def record_user_message(
        self,
        session: Session,
        content: str,
        attached_filename: str | None = None,
    ) -> Message:
        if attached_filename:
            content = f"{content}\n\n[Прикреплён файл: {attached_filename}]"
        return self._repo.append_message(session.id, role="user", content=content)

    def record_assistant_message(
        self,
        session: Session,
        content: str,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
    ) -> Message:
        return self._repo.append_message(
            session.id,
            role="assistant",
            content=content,
            tool_name=tool_name,
            tool_arguments=json.dumps(tool_arguments, ensure_ascii=False) if tool_arguments else None,
            tool_result=json.dumps(tool_result, ensure_ascii=False) if tool_result else None,
        )

    def save_attached_file(
        self,
        session: Session,
        filename: str,
        file_bytes: bytes,
        content_type: str | None = None,
    ) -> AttachedFile:
        if self._files is None:
            raise FileStorageError("File storage is not configured")
        s3_key, ctype = self._files.upload(filename, file_bytes, content_type=content_type)
        return self._repo.add_attached_file(
            session_id=session.id,
            filename=filename,
            s3_key=s3_key,
            content_type=ctype,
            size_bytes=len(file_bytes),
        )

    def get_last_attached_file_meta(self, session: Session) -> AttachedFile | None:
        return self._repo.get_last_attached_file(session.id)

    def get_active_file(self, session: Session) -> AttachedFileBytes | None:
        """Return the most recently attached file in the session, downloaded from S3."""
        meta = self._repo.get_last_attached_file(session.id)
        if meta is None:
            return None
        if self._files is None:
            logger.warning(
                "Session %d has attached file '%s' but file storage is not configured",
                session.id, meta.filename,
            )
            return None
        try:
            content = self._files.download(meta.s3_key)
        except FileStorageError:
            logger.exception("Failed to download active file for session %d", session.id)
            return None
        return AttachedFileBytes(filename=meta.filename, content=content, s3_key=meta.s3_key)

    def build_history_for_llm(self, session: Session) -> list[dict[str, str]]:
        """Build a list of {role, content} entries for OpenAI responses.create(input=...)."""
        messages = self._repo.get_last_messages(session.id, self._history_limit)
        history: list[dict[str, str]] = []
        for msg in messages:
            content = msg.content or ""
            if msg.role == "assistant" and msg.tool_name:
                summary = self._summarize_tool_call(msg)
                if summary:
                    content = f"{content}\n\n[Действие: {summary}]" if content else f"[Действие: {summary}]"
            history.append({"role": msg.role, "content": content})
        return history

    @staticmethod
    def _summarize_tool_call(msg: Message) -> str:
        try:
            args = json.loads(msg.tool_arguments) if msg.tool_arguments else {}
        except json.JSONDecodeError:
            args = {}

        tool = msg.tool_name or ""
        if tool in {"add_aliases", "set_aliases", "remove_aliases"}:
            stal = args.get("stal_code", "")
            aliases = args.get("aliases", []) or []
            return f"{tool} STAL={stal}, aliases={aliases}"
        if tool == "delete_mapping":
            return f"delete_mapping STAL={args.get('stal_code', '')}"
        if tool == "search_article":
            return f"search_article article={args.get('article', '')}"
        if tool == "search_by_stal":
            return f"search_by_stal STAL={args.get('stal_code', '')}"
        if tool == "get_mapping":
            return f"get_mapping STAL={args.get('stal_code', '')}"
        if tool == "bulk_upsert":
            items = args.get("items", []) or []
            return f"bulk_upsert items={len(items)}"
        if tool == "ingest_file":
            return "ingest_file (использован файл из сессии)"
        if tool == "deep_extraction_file":
            return "deep_extraction_file (использован файл из сессии)"
        return tool
