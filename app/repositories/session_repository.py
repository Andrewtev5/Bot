from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from app.core.config import Settings
from app.core.database import SqlServerConnectionPool
from app.domain.models import ChatMessage, ChatSession, MessageRole, utc_now


class SessionRepository(Protocol):
    def create_session(self, language: str, user_id: str | None = None) -> ChatSession:
        ...

    def get_session(self, session_id: str) -> ChatSession | None:
        ...

    def add_message(self, session: ChatSession, message: ChatMessage) -> None:
        ...

    def update_language(self, session: ChatSession, language: str) -> None:
        ...


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, ChatSession] = {}

    def create_session(self, language: str, user_id: str | None = None) -> ChatSession:
        session = ChatSession(id=uuid4().hex, language=language, user_id=user_id)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def add_message(self, session: ChatSession, message: ChatMessage) -> None:
        with self._lock:
            session.add_message(message)

    def update_language(self, session: ChatSession, language: str) -> None:
        with self._lock:
            session.language = language


class SqlServerSessionRepository:
    def __init__(self, pool: SqlServerConnectionPool) -> None:
        self._pool = pool

    def create_session(self, language: str, user_id: str | None = None) -> ChatSession:
        session = ChatSession(id=uuid4().hex, language=language)
        with self._pool.cursor() as cursor:
            # A user_id comes from the client, so an unknown or malformed value becomes an anonymous session.
            cursor.execute(
                """
                INSERT INTO dbo.chat_sessions (id, user_id, language, created_at, updated_at)
                OUTPUT CAST(inserted.user_id AS NVARCHAR(36)) AS user_id
                VALUES (
                    ?,
                    (SELECT id FROM dbo.users WHERE id = TRY_CONVERT(UNIQUEIDENTIFIER, CAST(? AS NVARCHAR(64)))),
                    ?,
                    ?,
                    ?
                );
                """,
                session.id,
                user_id,
                language,
                _to_sql_datetime(session.created_at),
                _to_sql_datetime(session.updated_at),
            )
            session.user_id = cursor.fetchone().user_id
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        with self._pool.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, CAST(user_id AS NVARCHAR(36)) AS user_id, language, created_at, updated_at
                FROM dbo.chat_sessions
                WHERE id = ?;
                """,
                session_id,
            )
            row = cursor.fetchone()
            if row is None:
                return None

            cursor.execute(
                """
                SELECT id, role, text, metadata, created_at
                FROM dbo.chat_messages
                WHERE session_id = ?
                ORDER BY created_at, CASE role WHEN N'user' THEN 0 ELSE 1 END;
                """,
                session_id,
            )
            messages = [_map_message(message_row) for message_row in cursor.fetchall()]

        return ChatSession(
            id=row.id,
            language=row.language,
            user_id=row.user_id,
            created_at=_from_sql_datetime(row.created_at),
            updated_at=_from_sql_datetime(row.updated_at),
            messages=messages,
        )

    def add_message(self, session: ChatSession, message: ChatMessage) -> None:
        with self._pool.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO dbo.chat_messages (id, session_id, role, text, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                message.id,
                session.id,
                message.role.value,
                message.text,
                json.dumps(message.metadata, ensure_ascii=False, default=str),
                _to_sql_datetime(message.created_at),
            )
            session.add_message(message)
            cursor.execute(
                "UPDATE dbo.chat_sessions SET updated_at = ? WHERE id = ?;",
                _to_sql_datetime(session.updated_at),
                session.id,
            )

    def update_language(self, session: ChatSession, language: str) -> None:
        if session.language == language:
            return

        with self._pool.cursor() as cursor:
            cursor.execute(
                "UPDATE dbo.chat_sessions SET language = ?, updated_at = ? WHERE id = ?;",
                language,
                _to_sql_datetime(utc_now()),
                session.id,
            )
        session.language = language


def build_session_repository(settings: Settings, pool: SqlServerConnectionPool) -> SessionRepository:
    if settings.product_db_mode == "mssql":
        return SqlServerSessionRepository(pool)

    return InMemorySessionRepository()


def _map_message(row: Any) -> ChatMessage:
    return ChatMessage(
        id=row.id,
        role=MessageRole(row.role),
        text=row.text,
        metadata=json.loads(row.metadata) if row.metadata else {},
        created_at=_from_sql_datetime(row.created_at),
    )


def _to_sql_datetime(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _from_sql_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc)
