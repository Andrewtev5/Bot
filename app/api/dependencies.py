from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, load_settings
from app.repositories.product_repository import build_product_repository
from app.repositories.session_repository import InMemorySessionRepository
from app.services.ai_provider import build_ai_provider
from app.services.chat_service import ChatService


@lru_cache
def get_settings() -> Settings:
    return load_settings()


@lru_cache
def get_product_repository():
    return build_product_repository(get_settings())


@lru_cache
def get_session_repository():
    return InMemorySessionRepository()


@lru_cache
def get_ai_provider():
    return build_ai_provider(get_settings())


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(
        session_repository=get_session_repository(),
        product_repository=get_product_repository(),
        ai_provider=get_ai_provider(),
        default_language=get_settings().default_language,
        max_products_for_ai=get_settings().max_products_for_ai,
    )
