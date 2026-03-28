from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain.models import ChatMessage, MessageRole, Product
from app.repositories.product_repository import ProductRepository
from app.repositories.session_repository import InMemorySessionRepository


@dataclass(slots=True)
class AssistantReply:
    text: str
    matched_products: list[Product]
    intent: str


class RuleBasedAssistantEngine:
    def __init__(self, product_repository: ProductRepository) -> None:
        self._product_repository = product_repository

    def generate_reply(self, text: str, language: str) -> AssistantReply:
        normalized = self._normalize(text)
        products = self._product_repository.search_products(normalized, limit=3)

        if any(token in normalized for token in {"привет", "hello", "hi", "dzie", "czesc"}):
            return AssistantReply(
                text=self._message(
                    language,
                    "Привет. Я пока работаю без ИИ, но уже могу отвечать по товарам, цене, наличию и доставке.",
                    "Hello. I work without AI for now, but I can already answer about products, prices, stock, and delivery.",
                    "Czesc. Na razie dzialam bez AI, ale juz moge odpowiadac o produktach, cenach, dostepnosci i dostawie.",
                ),
                matched_products=[],
                intent="greeting",
            )

        if any(token in normalized for token in {"доставка", "delivery", "dostawa"}):
            return AssistantReply(
                text=self._message(
                    language,
                    "Базовый ответ по доставке: сейчас модуль оформлен как заглушка. Позже сюда можно подключить реальные тарифы, сроки и API логистики.",
                    "Basic delivery answer: this module is currently a placeholder. Real rates, timings, and logistics APIs can be connected later.",
                    "Podstawowa odpowiedz o dostawie: ten modul jest teraz placeholderem. Pozniej mozna podlaczyc prawdziwe stawki, terminy i API logistyki.",
                ),
                matched_products=[],
                intent="delivery",
            )

        if any(token in normalized for token in {"возврат", "return", "zwrot"}):
            return AssistantReply(
                text=self._message(
                    language,
                    "По возврату сейчас работает только базовый сценарий. Позже можно подключить правила магазина, сроки возврата и создание заявок.",
                    "For returns, only a basic flow is prepared now. Later you can connect store rules, return windows, and request creation.",
                    "Dla zwrotow przygotowany jest teraz tylko podstawowy scenariusz. Pozniej mozna podlaczyc zasady sklepu, terminy i tworzenie zgloszen.",
                ),
                matched_products=[],
                intent="return",
            )

        if any(token in normalized for token in {"цена", "price", "cena", "сколько"}):
            if products:
                first = products[0]
                return AssistantReply(
                    text=self._message(
                        language,
                        f"Нашёл товар {first.name}. Текущая цена в базе: {first.price:.0f} {first.currency}.",
                        f"I found {first.name}. Current price in the catalog: {first.price:.0f} {first.currency}.",
                        f"Znalazlem produkt {first.name}. Aktualna cena w katalogu: {first.price:.0f} {first.currency}.",
                    ),
                    matched_products=products,
                    intent="price",
                )

        if any(token in normalized for token in {"налич", "stock", "available", "dostep"}):
            if products:
                first = products[0]
                return AssistantReply(
                    text=self._message(
                        language,
                        f"По товару {first.name} текущий статус: {self._stock_label(first.stock_status, language)}.",
                        f"For {first.name}, the current stock status is: {self._stock_label(first.stock_status, language)}.",
                        f"Dla produktu {first.name} aktualny status to: {self._stock_label(first.stock_status, language)}.",
                    ),
                    matched_products=products,
                    intent="stock",
                )

        if any(token in normalized for token in {"подбери", "recommend", "suggest", "wybierz", "посоветуй"}):
            recommended = products or self._default_recommendations()
            return AssistantReply(
                text=self._recommendation_message(recommended, language),
                matched_products=recommended,
                intent="recommendation",
            )

        if products:
            lines = [
                self._message(
                    language,
                    "Я нашёл подходящие товары в каталоге:",
                    "I found matching products in the catalog:",
                    "Znalazlem pasujace produkty w katalogu:",
                )
            ]
            lines.extend(self._format_product_line(product, language) for product in products)
            lines.append(
                self._message(
                    language,
                    "Могу отдельно подсказать по цене, наличию, доставке или подобрать вариант под комнату.",
                    "I can also help with price, stock, delivery, or choosing a lamp for a room.",
                    "Moge tez pomoc z cena, dostepnoscia, dostawa albo doborem lampy do pomieszczenia.",
                )
            )
            return AssistantReply(text="\n".join(lines), matched_products=products, intent="product_search")

        return AssistantReply(
            text=self._message(
                language,
                "Я пока работаю по правилам, без ИИ. Попробуй спросить про конкретную лампу, цену, наличие, доставку или попроси подобрать товар.",
                "I currently work by rules, without AI. Try asking about a specific lamp, price, stock, delivery, or ask me to recommend a product.",
                "Dzialam teraz na prostych zasadach, bez AI. Zapytaj o konkretna lampe, cene, dostepnosc, dostawe albo popros o rekomendacje.",
            ),
            matched_products=[],
            intent="fallback",
        )

    def _default_recommendations(self) -> list[Product]:
        return self._product_repository.list_products()[:3]

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.lower().strip().split())

    @staticmethod
    def _message(language: str, ru: str, en: str, pl: str) -> str:
        if language == "en":
            return en
        if language == "pl":
            return pl
        return ru

    def _recommendation_message(self, products: Iterable[Product], language: str) -> str:
        items = list(products)
        intro = self._message(
            language,
            "Вот базовая подборка из каталога:",
            "Here is a basic selection from the catalog:",
            "Oto podstawowy zestaw z katalogu:",
        )
        lines = [intro]
        lines.extend(self._format_product_line(product, language) for product in items)
        lines.append(
            self._message(
                language,
                "Позже этот блок можно заменить на рекомендации от ИИ, но API останется тем же.",
                "Later this block can be replaced with AI recommendations while keeping the same API.",
                "Pozniej ten blok mozna zastapic rekomendacjami AI, zachowujac to samo API.",
            )
        )
        return "\n".join(lines)

    def _format_product_line(self, product: Product, language: str) -> str:
        label = self._message(language, "Цена", "Price", "Cena")
        return f"- {product.name} | {label}: {product.price:.0f} {product.currency} | {product.description}"

    @staticmethod
    def _stock_label(stock_status: str, language: str) -> str:
        variants = {
            "in_stock": {"ru": "в наличии", "en": "in stock", "pl": "dostepny"},
            "out_of_stock": {"ru": "нет в наличии", "en": "out of stock", "pl": "brak w magazynie"},
            "unknown": {"ru": "статус неизвестен", "en": "status unknown", "pl": "status nieznany"},
        }
        return variants.get(stock_status, variants["unknown"]).get(language, variants["unknown"]["ru"])


class ChatService:
    def __init__(
        self,
        session_repository: InMemorySessionRepository,
        assistant_engine: RuleBasedAssistantEngine,
        default_language: str = "ru",
    ) -> None:
        self._session_repository = session_repository
        self._assistant_engine = assistant_engine
        self._default_language = default_language

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
        clean_text = " ".join(text.strip().split())
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

        reply = self._assistant_engine.generate_reply(clean_text, effective_language)
        assistant_message = ChatMessage(
            role=MessageRole.ASSISTANT,
            text=reply.text,
            metadata={
                "intent": reply.intent,
                "matched_product_ids": [product.id for product in reply.matched_products],
            },
        )
        session = self._session_repository.add_message(session.id, assistant_message)
        session.language = effective_language
        return session, assistant_message, reply.matched_products
