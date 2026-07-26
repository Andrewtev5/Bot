from __future__ import annotations

import unicodedata
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
    action: dict[str, object] | None = None


class ChatService:
    def __init__(
        self,
        session_repository: InMemorySessionRepository,
        product_repository: ProductRepository,
        ai_provider: AiProvider,
        default_language: str = "pl",
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
        effective_language = detect_response_language(clean_text, language or session.language or self._default_language)

        user_message = ChatMessage(
            role=MessageRole.USER,
            text=clean_text,
            metadata=metadata or {},
        )
        self._session_repository.add_message(session.id, user_message)

        reply = self._build_reply(clean_text, effective_language, session)
        assistant_message = ChatMessage(
            role=MessageRole.ASSISTANT,
            text=reply.text,
            metadata={
                "intent": reply.intent,
                "provider": reply.provider,
                "model": reply.model,
                "matched_product_ids": [product.id for product in reply.matched_products],
                "action": reply.action,
            },
        )
        session = self._session_repository.add_message(session.id, assistant_message)
        session.language = effective_language
        return session, assistant_message, reply.matched_products

    def _build_reply(self, text: str, language: str, session) -> AssistantReply:
        if is_out_of_scope(text):
            return AssistantReply(
                text=build_out_of_scope_reply(language),
                matched_products=[],
                intent="out_of_scope",
                provider="local_guard",
                model=None,
            )

        intent = detect_intent(text)

        matched_products: list[Product] = []
        if intent != "greeting":
            matched_products = self._product_repository.search_products(text, limit=self._max_products_for_ai)

        if intent in {"library_request", "cart_request"}:
            previous_products = get_previous_matched_products(session, self._product_repository, self._max_products_for_ai)
            if previous_products:
                matched_products = previous_products

        if not matched_products and intent == "product_details":
            matched_products = get_previous_matched_products(session, self._product_repository, self._max_products_for_ai)

        if intent in {"library_request", "cart_request"} and matched_products:
            selected_products = select_products_for_action(text, matched_products)
            action_type = "add_to_library" if intent == "library_request" else "add_to_cart"
            return AssistantReply(
                text=build_action_reply(language, action_type, selected_products),
                matched_products=selected_products,
                intent=intent,
                provider="local_action",
                model=None,
                action=build_chat_action(action_type, selected_products),
            )

        if not matched_products and intent == "recommendation":
            matched_products = self._product_repository.list_products()[: self._max_products_for_ai]

        ai_response = self._ai_provider.generate_consultation(
            user_text=text,
            products=matched_products,
            language=language,
        )
        return AssistantReply(
            text=ai_response.text,
            matched_products=matched_products,
            intent=intent,
            provider=ai_response.provider,
            model=ai_response.model,
        )


def normalize_message(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_for_matching(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    without_marks = without_marks.replace("ł", "l")
    return " ".join(without_marks.split())


def detect_intent(text: str) -> str:
    normalized = normalize_for_matching(text)
    if is_greeting_message(text):
        return "greeting"
    if any(token in normalized for token in {"opowiedz", "opis", "szczegoly", "details", "describe", "tell me about"}):
        return "product_details"
    if "bibliotek" in normalized or "library" in normalized or "zapisz" in normalized:
        return "library_request"
    if "koszyk" in normalized or "cart" in normalized:
        return "cart_request"
    if any(token in normalized for token in {"price", "cena", "koszt", "ile"}):
        return "price"
    if any(token in normalized for token in {"delivery", "dostawa"}):
        return "delivery"
    if any(token in normalized for token in {"return", "zwrot"}):
        return "return"
    if any(token in normalized for token in {"recommend", "suggest", "wybierz", "doradz", "polec", "pokaz"}):
        return "recommendation"
    return "consultation"


STORE_TOPIC_KEYWORDS = {
    "akcent",
    "barwa",
    "bial",
    "biur",
    "ciepl",
    "ciem",
    "cena",
    "czujnik",
    "dostawa",
    "gwarancja",
    "jasn",
    "kabel",
    "kinkiet",
    "klosz",
    "kolor",
    "koszyk",
    "koszt",
    "kuch",
    "lamp",
    "led",
    "loft",
    "lumen",
    "lazien",
    "moc",
    "noc",
    "opraw",
    "oswietl",
    "platnosc",
    "pokoj",
    "produkt",
    "przedpokoj",
    "reklamacja",
    "salon",
    "sklep",
    "sypial",
    "swiatl",
    "zamow",
    "zarow",
    "zwrot",
}

ACTION_NUMBER_WORDS = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "jeden": 1,
    "jedna": 1,
    "jedno": 1,
    "dwa": 2,
    "dwie": 2,
    "trzy": 3,
    "cztery": 4,
    "piec": 5,
    "five": 5,
    "four": 4,
    "one": 1,
    "three": 3,
    "two": 2,
}

ACTION_ORDINAL_KEYWORDS = {
    "pierwsz": 0,
    "first": 0,
    "drug": 1,
    "second": 1,
    "trzec": 2,
    "third": 2,
    "czwart": 3,
    "fourth": 3,
    "piat": 4,
    "fifth": 4,
}

GREETING_KEYWORDS = {
    "czesc",
    "dzien dobry",
    "dobry wieczor",
    "hej",
    "hello",
    "hi",
    "siema",
    "siemka",
    "witam",
}

SOCIAL_STORE_KEYWORDS = {
    "co potrafisz",
    "dziekuje",
    "help",
    "jak dzialasz",
    "kim jestes",
    "ok",
    "okej",
    "pomoc",
    "super",
    "thanks",
}

OUT_OF_SCOPE_KEYWORDS = {
    "adwokat",
    "atak",
    "bitwa",
    "bron",
    "choroba",
    "diagnoza",
    "finanse",
    "gielda",
    "kredyt",
    "leczenie",
    "lek",
    "medycyna",
    "modlitwa",
    "polityka",
    "prawnik",
    "programowanie",
    "przemoc",
    "religia",
    "sad",
    "terroryzm",
    "wojna",
    "wybory",
    "zabij",
    "zdrowie",
    "bomb",
    "court",
    "diagnosis",
    "election",
    "finance",
    "kill",
    "law",
    "lawyer",
    "medicine",
    "politics",
    "religion",
    "stock",
    "terror",
    "violence",
    "war",
    "weapon",
}


def is_out_of_scope(text: str) -> bool:
    normalized = normalize_for_matching(text)

    if contains_blocked_topic(normalized):
        return True

    if is_greeting_message(text) or contains_social_store_phrase(normalized):
        return False

    return not contains_store_topic(normalized)


def is_greeting_message(text: str) -> bool:
    normalized = normalize_for_matching(text)
    words_count = len(normalized.split())
    return words_count <= 5 and any(keyword in normalized for keyword in GREETING_KEYWORDS)


def contains_social_store_phrase(normalized: str) -> bool:
    return any(keyword in normalized for keyword in SOCIAL_STORE_KEYWORDS)


def contains_blocked_topic(normalized: str) -> bool:
    words = set(normalized.split())
    return any(
        keyword in normalized if " " in keyword else keyword in words
        for keyword in OUT_OF_SCOPE_KEYWORDS
    )


def contains_store_topic(normalized: str) -> bool:
    words = normalized.split()
    return any(word.startswith(keyword) for word in words for keyword in STORE_TOPIC_KEYWORDS)


def get_previous_matched_products(session, product_repository: ProductRepository, limit: int) -> list[Product]:
    for message in reversed(session.messages):
        product_ids = message.metadata.get("matched_product_ids") if message.metadata else None
        if not product_ids:
            continue

        products = [
            product
            for product_id in product_ids[:limit]
            if (product := product_repository.get_product(str(product_id))) is not None
        ]
        if products:
            return products

    return []


def select_products_for_action(text: str, products: list[Product]) -> list[Product]:
    normalized = normalize_for_matching(text)
    if "wszystk" in normalized or "all" in normalized:
        return products

    for keyword, index in ACTION_ORDINAL_KEYWORDS.items():
        if keyword in normalized and index < len(products):
            return [products[index]]

    words = normalized.split()
    for word in words:
        count = ACTION_NUMBER_WORDS.get(word)
        if count:
            return products[: min(count, len(products))]

    return products[:1]


def build_chat_action(action_type: str, products: list[Product]) -> dict[str, object]:
    return {
        "type": action_type,
        "items": [{"product_id": product.id, "quantity": 1} for product in products],
        "product_ids": [product.id for product in products],
    }


def build_action_reply(language: str, action_type: str, products: list[Product]) -> str:
    names = ", ".join(product.name for product in products)
    if language == "en":
        target = "library" if action_type == "add_to_library" else "cart"
        return f"I will try to add this to your {target}: {names}."

    target = "biblioteki" if action_type == "add_to_library" else "koszyka"
    return f"Dobrze, próbuję dodać do {target}: {names}."


def detect_response_language(text: str, fallback: str) -> str:
    normalized = normalize_for_matching(text)
    words = set(normalized.split())

    english_hints = {"hello", "hi", "thanks", "please", "show", "tell", "lamp", "light", "room", "cart", "library"}
    polish_hints = {
        "czesc",
        "dzien",
        "dobry",
        "siema",
        "siemka",
        "prosze",
        "pokaz",
        "opowiedz",
        "lampa",
        "lampki",
        "swiatlo",
        "koszyk",
        "biblioteki",
    }

    if words & english_hints and not words & polish_hints:
        return "en"
    if words & polish_hints:
        return "pl"
    return "en" if fallback == "en" else "pl"


def build_out_of_scope_reply(language: str) -> str:
    if language == "en":
        return (
            "I can help only with the lighting store: lamps, bulbs, product choice, cart, orders, delivery, "
            "returns and warranty. Tell me what room or type of light you need, and I will suggest suitable products."
        )

    return (
        "Mogę pomagać tylko w sprawach sklepu z oświetleniem: lampy, żarówki, dobór produktu, koszyk, zamówienia, "
        "dostawa, zwroty i gwarancja. Napisz, do jakiego pomieszczenia lub jakiego typu światła potrzebujesz, "
        "a zaproponuję odpowiednie produkty."
    )
