from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProductResponse(BaseModel):
    id: str
    name: str
    price: float
    currency: str
    category: str
    description: str
    stock_status: str
    image_url: str | None
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    text: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatSessionResponse(BaseModel):
    id: str
    language: str
    user_id: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageResponse]


class CreateSessionRequest(BaseModel):
    language: str | None = None
    user_id: str | None = None


class SendMessageRequest(BaseModel):
    text: str
    session_id: str | None = None
    language: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SendMessageResponse(BaseModel):
    session: ChatSessionResponse
    reply: ChatMessageResponse
    matched_products: list[ProductResponse]
