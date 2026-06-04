from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ChatMessage, MessageRole, Product
from app.repositories.product_repository import ProductRepository
from app.repositories.session_repository import InMemorySessionRepository
from app.services.ai_provider import AiProvider


@dataclass(slots=True)
class AssistantReply:
    text: str
    matched_products: list[Product]
    intent: str
    provider: str
    model: str | None = None


class ChatService:
    def __init__(
        self,
        session_repository: InMemorySessionRepository,
        product_repository: ProductRepository,
        ai_provider: AiProvider,
        default_language: str = "ru",
        max_products_for_ai: int = 5,
    ) -> None:
        self._session_repository = session_repository
        self._product_repository = product_repository
        self._ai_provider = ai_provider
        self._default_language = default_language
        self._max_products_for_ai = max_products_for_ai

    def create_session(self, language: str | None = None, user_id: str | None = None):
        return self._session_repository.create_session(language=language or self._default_language, user_id=user_id)

    def get_session(self, session_id: str):
        session = self._session_repository.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} was not found.")
        return session

    def process_message(
        self,
        text: str,
        session_id: str | None = None,
        language: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ):
        clean_text = normalize_message(text)
        if not clean_text:
            raise ValueError("Message text must not be empty.")

        session = self.get_session(session_id) if session_id else self.create_session(language=language, user_id=user_id)
        effective_language = language or session.language or self._default_language

        user_message = ChatMessage(
            role=MessageRole.USER,
            text=clean_text,
            metadata=metadata or {},
        )
        self._session_repository.add_message(session.id, user_message)

        reply = self._build_reply(clean_text, effective_language)
        assistant_message = ChatMessage(
            role=MessageRole.ASSISTANT,
            text=reply.text,
            metadata={
                "intent": reply.intent,
                "provider": reply.provider,
                "model": reply.model,
                "matched_product_ids": [product.id for product in reply.matched_products],
            },
        )
        session = self._session_repository.add_message(session.id, assistant_message)
        session.language = effective_language
        return session, assistant_message, reply.matched_products

    def _build_reply(self, text: str, language: str) -> AssistantReply:
        matched_products = self._product_repository.search_products(text, limit=self._max_products_for_ai)
        if not matched_products and detect_intent(text) == "recommendation":
            matched_products = self._product_repository.list_products()[: self._max_products_for_ai]

        ai_response = self._ai_provider.generate_consultation(
            user_text=text,
            products=matched_products,
            language=language,
        )
        return AssistantReply(
            text=ai_response.text,
            matched_products=matched_products,
            intent=detect_intent(text),
            provider=ai_response.provider,
            model=ai_response.model,
        )


def normalize_message(value: str) -> str:
    return " ".join(value.strip().split())


def detect_intent(text: str) -> str:
    normalized = text.lower()
    if any(token in normalized for token in {"цена", "price", "cena", "сколько"}):
        return "price"
    if any(token in normalized for token in {"доставка", "delivery", "dostawa"}):
        return "delivery"
    if any(token in normalized for token in {"возврат", "return", "zwrot"}):
        return "return"
    if any(token in normalized for token in {"подбери", "посоветуй", "recommend", "suggest", "wybierz"}):
        return "recommendation"
    return "consultation"
