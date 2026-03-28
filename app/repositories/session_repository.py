from __future__ import annotations

from threading import Lock
from uuid import uuid4

from app.domain.models import ChatMessage, ChatSession


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

    def add_message(self, session_id: str, message: ChatMessage) -> ChatSession:
        with self._lock:
            session = self._sessions[session_id]
            session.add_message(message)
            return session
