from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass(slots=True)
class Product:
    id: str
    name: str
    price: float
    currency: str
    category: str
    description: str
    tags: list[str]
    keywords: list[str]
    stock_status: str = "unknown"
    image_url: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ChatMessage:
    role: MessageRole
    text: str
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(slots=True)
class ChatSession:
    id: str
    language: str
    user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    messages: list[ChatMessage] = field(default_factory=list)

    def add_message(self, message: ChatMessage) -> None:
        self.messages.append(message)
        self.updated_at = utc_now()
