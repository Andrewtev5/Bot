from __future__ import annotations

from dataclasses import dataclass, field, replace
from random import SystemRandom
import unicodedata

from app.domain.models import ChatMessage, MessageRole, Product
from app.repositories.product_repository import ProductRepository
from app.repositories.session_repository import SessionRepository
from app.search.ranking import (
    is_product_allowed_for_light_preference,
    light_preference_for_query,
    rank_products,
    relevant_products,
)
from app.services.ai_provider import (
    HISTORY_MESSAGE_LENGTH,
    HISTORY_MESSAGES,
    AiProvider,
    AiResponse,
    Consultation,
)
from app.services.dialogue import (
    ChatCommand,
    PriceRequest,
    asks_for_recommendation,
    detect_command,
    detect_lighting_tip,
    detect_small_talk,
    detect_store_topic,
    fold,
    has_prefix,
    is_generic_product_request,
    parse_price_request,
    parse_quantity,
    refers_to_previous_products,
    remove_price_words,
    selected_ordinal,
    words_of,
)
from app.services.polish_language import enrich_with_polish_lemmas, polish_lemmas

_random = SystemRandom()
ACTION_INTENT_PREFIXES = ("add_to_", "remove_from_", "open_")


class SessionNotFoundError(Exception):
    pass


class EmptyMessageError(Exception):
    pass


@dataclass(slots=True)
class AssistantReply:
    text: str
    matched_products: list[Product]
    intent: str
    provider: str
    model: str | None = None
    action: dict[str, object] | None = None
    # Everything considered for the reply. Questions like "which is cheapest?" compare these, not only the cards shown.
    candidates: list[Product] = field(default_factory=list)


class ChatService:
    def __init__(
        self,
        session_repository: SessionRepository,
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
            raise SessionNotFoundError(session_id)
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
            raise EmptyMessageError()

        session = self.get_session(session_id) if session_id else self.create_session(language=language, user_id=user_id)
        effective_language = detect_response_language(clean_text, language or session.language or self._default_language)

        user_message = ChatMessage(
            role=MessageRole.USER,
            text=clean_text,
            metadata=metadata or {},
        )
        self._session_repository.add_message(session, user_message)

        reply = self._build_reply(clean_text, effective_language, session)
        assistant_message = ChatMessage(
            role=MessageRole.ASSISTANT,
            text=reply.text,
            metadata={
                "intent": reply.intent,
                "provider": reply.provider,
                "model": reply.model,
                "matched_product_ids": [product.id for product in reply.matched_products],
                "matched_product_names": [product.name for product in reply.matched_products],
                "candidate_product_ids": [product.id for product in reply.candidates],
                "action": reply.action,
            },
        )
        self._session_repository.add_message(session, assistant_message)
        self._session_repository.update_language(session, effective_language)
        return session, assistant_message, reply.matched_products

    def _build_reply(self, text: str, language: str, session) -> AssistantReply:
        if is_out_of_scope(text, session):
            return AssistantReply(
                text=build_out_of_scope_reply(language),
                matched_products=[],
                intent="out_of_scope",
                provider="local_guard",
                model=None,
            )

        command = detect_command(text)
        if command is not None:
            return self._handle_command(command, text, language, session)

        store_topic = detect_store_topic(text)
        if store_topic:
            return self._consult(text, language, session, f"store_{store_topic}", f"store:{store_topic}", [])

        lighting_tip = detect_lighting_tip(text)
        if lighting_tip:
            return self._consult(text, language, session, "lighting_advice", f"tip:{lighting_tip}", [])

        if is_greeting_message(text):
            return self._consult(text, language, session, "greeting", "greeting", [])

        small_talk = detect_small_talk(text)
        # "Nie wiem, mam mały salon" already says what the customer needs, so it is a request and not small talk.
        if small_talk and not (small_talk == "unsure" and self._looks_like_store_request(text, session)):
            # After "yes" or "no" the model still needs to know which products the conversation is about.
            products = self._previous_products(session) if small_talk in {"agreement", "negative"} else []
            return self._consult(text, language, session, "small_talk", f"small_talk:{small_talk}", products)

        return self._recommend(text, language, session)

    def _recommend(self, text: str, language: str, session) -> AssistantReply:
        intent = detect_intent(text)
        price = parse_price_request(text)
        previous = self._previous_products(session)
        notes: list[str] = []
        kind = {"product_details": "details", "more_recommendations": "more", "price": "price"}.get(intent, "recommendation")

        if previous and refers_to_previous_products(text):
            if selected_ordinal(text) is not None:
                products = products_from_previous(text, previous)
                kind = "details"
            else:
                products = products_from_previous(text, self._previous_candidates(session) or previous)
            intent = "follow_up"
            notes.append(follow_up_note(language))
        elif previous and price.relative:
            products = self._relative_price_products(text, session, previous, price)
            intent = "follow_up"
        elif intent == "more_recommendations":
            light_preference = light_preference_for_query(text)
            products = get_more_recommendations(session, self._product_repository, self._max_products_for_ai, light_preference)
        elif not self._looks_like_store_request(text, session) and not asks_for_recommendation(text) and not price.order:
            if previous:
                # Mid-conversation the message may continue the topic, so the model decides with the products at hand.
                products = previous
                kind = "clarify"
                notes.append(unclear_note(language))
            else:
                products = []
                kind = "off_topic"
                notes.append(off_topic_note(language))
        else:
            products = self._search(text, session, price)
            if not products:
                kind = "clarify"

        products, price_notes = apply_price_request(products, price, language)
        notes.extend(price_notes)
        return self._consult(text, language, session, intent, kind, products[: self._max_products_for_ai], notes)

    def _search(self, text: str, session, price: PriceRequest) -> list[Product]:
        if price.order and is_generic_product_request(text):
            return self._product_repository.list_products()

        search_text = enrich_with_polish_lemmas(build_contextual_search_text(remove_price_words(text), session))
        light_preference = light_preference_for_query(text) or light_preference_for_query(search_text)
        if price.max_price is not None or price.order:
            # Price filters need every lamp that fits: a good one within budget may rank below the first few.
            candidates = relevant_products(self._product_repository.list_products(), search_text)
        else:
            candidates = self._product_repository.search_products(search_text, limit=self._max_products_for_ai)
        return filter_products_by_light_preference(candidates, light_preference)

    def _relative_price_products(self, text: str, session, previous: list[Product], price: PriceRequest) -> list[Product]:
        search_text = enrich_with_polish_lemmas(get_recent_user_context(session))
        catalog = self._product_repository.list_products()
        candidates = relevant_products(catalog, search_text) if search_text else []
        candidates = candidates or catalog

        if price.relative == "cheaper":
            boundary = min(product.price for product in previous)
            return sorted((product for product in candidates if product.price < boundary), key=lambda product: product.price, reverse=True)

        boundary = max(product.price for product in previous)
        return sorted((product for product in candidates if product.price > boundary), key=lambda product: product.price)

    def _looks_like_store_request(self, text: str, session) -> bool:
        normalized = normalize_for_matching(text)
        return (
            contains_store_topic(normalized)
            or contains_product_attribute_phrase(normalized)
            or contains_light_preference_phrase(normalized)
            or (has_recent_assistant_context(session) and is_short_contextual_reply(normalized))
        )

    def _previous_products(self, session) -> list[Product]:
        return get_previous_matched_products(session, self._product_repository, self._max_products_for_ai)

    def _previous_candidates(self, session) -> list[Product]:
        for message in reversed(session.messages):
            metadata = message.metadata or {}
            if metadata.get("matched_product_ids") and not str(metadata.get("intent", "")).startswith(ACTION_INTENT_PREFIXES):
                return [
                    product
                    for product_id in metadata.get("candidate_product_ids") or []
                    if (product := self._product_repository.get_product(str(product_id))) is not None
                ]
        return []

    def _consult(
        self,
        text: str,
        language: str,
        session,
        intent: str,
        kind: str,
        products: list[Product],
        notes: list[str] | None = None,
    ) -> AssistantReply:
        localized = [localize_product(product, language) for product in products]
        ai_response = self._ai_provider.generate_consultation(
            Consultation(
                user_text=text,
                language=language,
                products=localized,
                history=build_history(session),
                kind=kind,
                notes=notes or [],
                is_first_message=len(session.messages) <= 1,
            )
        )

        shown = select_shown_products(localized, ai_response)

        return AssistantReply(
            text=ai_response.text,
            matched_products=shown,
            intent=intent,
            provider=ai_response.provider,
            model=ai_response.model,
            candidates=localized,
        )

    def _handle_command(self, command: ChatCommand, text: str, language: str, session) -> AssistantReply:
        if command.type.startswith("open_"):
            return local_action_reply(command.type, build_open_reply(language, command.type), [], {"type": command.type})

        if command.type.startswith("remove_"):
            return self._handle_remove(command, text, language, session)

        previous = self._previous_products(session)
        products = previous if previous and (command.wants_all or refers_to_previous_products(text)) else []
        if not products:
            search_text = enrich_with_polish_lemmas(remove_command_words(text))
            products = self._product_repository.search_products(search_text, limit=1) if search_text else []
        products = products or previous

        if not products:
            return local_action_reply(command.type, build_which_product_reply(language), [], None)

        selected = [localize_product(product, language) for product in select_products_for_action(text, products, command.wants_all)]
        return local_action_reply(
            command.type,
            build_action_reply(language, command.type, selected),
            selected,
            build_chat_action(command.type, selected, parse_quantity(text)),
        )

    def _handle_remove(self, command: ChatCommand, text: str, language: str, session) -> AssistantReply:
        if command.wants_all:
            return local_action_reply(
                command.type,
                build_action_reply(language, command.type, []),
                [],
                {"type": command.type, "all": True, "items": [], "product_ids": []},
            )

        if refers_to_previous_products(text) and selected_ordinal(text) is not None:
            candidates = self._previous_products(session)
        else:
            candidates = get_last_action_products(session, self._product_repository) or self._previous_products(session)

        if not candidates:
            return local_action_reply(command.type, build_which_product_reply(language), [], None)

        selected = [localize_product(product, language) for product in select_products_for_action(text, candidates, False)]
        return local_action_reply(
            command.type,
            build_action_reply(language, command.type, selected),
            selected,
            build_chat_action(command.type, selected, 1),
        )


def normalize_message(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_for_matching(value: str) -> str:
    words = value.casefold().split()
    words.extend(polish_lemmas(value))
    normalized = unicodedata.normalize("NFKD", " ".join(words))
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    without_marks = without_marks.replace("ł", "l")
    return " ".join(dict.fromkeys(without_marks.split()))


def detect_intent(text: str) -> str:
    normalized = normalize_for_matching(text)
    words = normalized.split()
    if is_greeting_message(text):
        return "greeting"
    if (
        contains_contextual_choice_phrase(normalized)
        or contains_light_preference_phrase(normalized)
        or contains_product_attribute_phrase(normalized)
    ):
        return "contextual_recommendation"
    if contains_more_recommendation_phrase(normalized):
        return "more_recommendations"
    if has_prefix(words, {"opowiedz", "opis", "szczegol", "details", "describe"}) or "tell me about" in normalized:
        return "product_details"
    if has_prefix(words, {"cena", "cen", "kosztuj", "koszt", "price", "cost"}) or "ile" in words or "how much" in normalized:
        return "price"
    if has_prefix(words, {"find", "need", "recommend", "show", "suggest", "wybierz", "doradz", "polec", "pokaz"}) or "looking for" in normalized:
        return "recommendation"
    return "consultation"


STORE_TOPIC_KEYWORDS = {
    "akcent",
    "ambient",
    "aplik",
    "barwa",
    "bath",
    "bial",
    "biur",
    "bulb",
    "buy",
    "ciepl",
    "ciem",
    "cena",
    "czujnik",
    "czerwon",
    "delivery",
    "dostawa",
    "gwarancja",
    "jasn",
    "kabel",
    "kinkiet",
    "klosz",
    "kolor",
    "koszyk",
    "koszt",
    "krysztal",
    "kuch",
    "lamp",
    "led",
    "light",
    "lighting",
    "loft",
    "lumen",
    "lazien",
    "magicz",
    "moc",
    "neon",
    "niebiesk",
    "noc",
    "order",
    "okrag",
    "opraw",
    "oswietl",
    "platnosc",
    "pokoj",
    "price",
    "product",
    "produkt",
    "przedpokoj",
    "recommend",
    "reklamacja",
    "restroom",
    "return",
    "rgb",
    "room",
    "salon",
    "shop",
    "sklep",
    "store",
    "suggest",
    "sypial",
    "swiatl",
    "smart",
    "taras",
    "tecz",
    "toilet",
    "warranty",
    "washroom",
    "waterproof",
    "wodoodporn",
    "wododporn",
    "zamow",
    "zarow",
    "zewnetrz",
    "zielon",
    "zwrot",
    "zol",
}

CONTEXTUAL_CHOICE_KEYWORDS = {
    "both",
    "either",
    "jedno i drugie",
    "moze byc",
    "oba",
    "obie",
    "obydwa",
    "obydwie",
    "te i te",
    "to i to",
}

PRODUCT_SUBJECT_PREFIXES = {
    "bulb",
    "chandelier",
    "kinkiet",
    "lamp",
    "light",
    "oswietl",
    "plafon",
    "reflektor",
    "zarow",
    "zyrandol",
}

STRONG_NEW_SEARCH_PREFIXES = {
    "inteligent",
    "magicz",
    "rainbow",
    "rgb",
    "smart",
    "tecz",
    "wifi",
    "wodoodporn",
    "wododporn",
    "zewnetrz",
}

PRODUCT_ATTRIBUTE_PREFIXES = {
    "bambus",
    "bezow",
    "bezprzew",
    "boho",
    "braz",
    "czarn",
    "czerwon",
    "deszcz",
    "drewn",
    "fiolet",
    "glamour",
    "green",
    "industrial",
    "klasycz",
    "kolor",
    "krysztal",
    "loft",
    "metal",
    "minimal",
    "niebiesk",
    "nowoczes",
    "outdoor",
    "pomarancz",
    "przenos",
    "red",
    "rattan",
    "rozow",
    "solar",
    "srebr",
    "szklan",
    "waterproof",
    "wodoodporn",
    "wododporn",
    "zewnetrz",
    "zielon",
    "zlot",
}

NEW_SEARCH_PHRASES = {
    "a teraz",
    "now i need",
    "now show",
    "teraz potrzebuje",
    "teraz pokaz",
    "teraz szukam",
}

LIGHT_PREFERENCE_KEYWORDS = {
    "amber": {"cieple", "zolte", "ambient"},
    "bial": {"neutralne", "biale", "jasne"},
    "ciepl": {"cieple", "zolte", "ambient"},
    "cold": {"zimne", "jasne", "biale"},
    "cool": {"zimne", "jasne", "biale"},
    "default": {"neutralne", "biale", "jasne"},
    "domysl": {"neutralne", "biale", "jasne"},
    "jasn": {"jasne", "biale", "neutralne"},
    "klasycz": {"neutralne", "biale", "jasne"},
    "neutral": {"neutralne", "biale", "jasne"},
    "normal": {"neutralne", "biale", "jasne"},
    "standard": {"neutralne", "biale", "jasne"},
    "white": {"neutralne", "biale", "jasne"},
    "yellow": {"cieple", "zolte", "ambient"},
    "zimn": {"zimne", "jasne", "biale"},
    "zolt": {"cieple", "zolte", "ambient"},
    "zwykl": {"neutralne", "biale", "jasne"},
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

MORE_RECOMMENDATION_KEYWORDS = {
    "alternatyw",
    "another",
    "different",
    "else",
    "inne",
    "inny",
    "jeszcze",
    "more",
    "nastepne",
    "next",
    "propozycj",
    "wariant",
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


def is_out_of_scope(text: str, session=None) -> bool:
    """Stops only clearly forbidden topics. Anything else reaches the model, which can decline by itself."""
    normalized = normalize_for_matching(text)
    return contains_blocked_topic(normalized) and not contains_store_topic(normalized)


def is_greeting_message(text: str) -> bool:
    normalized = normalize_for_matching(text)
    words = words_of(text)
    if len(words) > 5 or contains_store_topic(normalized) or detect_store_topic(text):
        return False
    joined = f" {' '.join(words)} "
    return any(f" {keyword} " in joined for keyword in GREETING_KEYWORDS)


def contains_more_recommendation_phrase(normalized: str) -> bool:
    return has_prefix(normalized.split(), MORE_RECOMMENDATION_KEYWORDS)


def contains_contextual_choice_phrase(normalized: str) -> bool:
    return any(keyword in normalized for keyword in CONTEXTUAL_CHOICE_KEYWORDS)


def contains_light_preference_phrase(normalized: str) -> bool:
    return any(keyword in normalized for keyword in LIGHT_PREFERENCE_KEYWORDS)


def contains_product_attribute_phrase(normalized: str) -> bool:
    return any(
        word.startswith(prefix)
        for word in normalized.split()
        for prefix in PRODUCT_ATTRIBUTE_PREFIXES
    )


def is_short_contextual_reply(normalized: str) -> bool:
    words = normalized.split()
    if not words or len(words) > 8:
        return False
    return (
        contains_contextual_choice_phrase(normalized)
        or contains_light_preference_phrase(normalized)
        or contains_product_attribute_phrase(normalized)
        or any(word in {"tak", "nie", "ok", "okej", "moze", "prosze"} for word in words)
    )


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
    """The last list the customer saw. Replies to cart commands are skipped, so "the second one" keeps its meaning."""
    for message in reversed(session.messages):
        metadata = message.metadata or {}
        product_ids = metadata.get("matched_product_ids")
        if not product_ids or str(metadata.get("intent", "")).startswith(ACTION_INTENT_PREFIXES):
            continue

        products = [
            product
            for product_id in product_ids[:limit]
            if (product := product_repository.get_product(str(product_id))) is not None
        ]
        if products:
            return products

    return []


def get_previous_matched_product_ids(session) -> set[str]:
    product_ids: set[str] = set()
    for message in session.messages:
        values = message.metadata.get("matched_product_ids") if message.metadata else None
        if not values:
            continue
        product_ids.update(str(product_id) for product_id in values)
    return product_ids


def get_more_recommendations(
    session,
    product_repository: ProductRepository,
    limit: int,
    light_preference: str | None = None,
) -> list[Product]:
    previous_ids = get_previous_matched_product_ids(session)
    products = [
        product
        for product in product_repository.list_products()
        if product.id not in previous_ids and is_product_allowed_for_light_preference(product, light_preference)
    ]

    if not products:
        products = filter_products_by_light_preference(product_repository.list_products(), light_preference)

    return products[:limit]


def get_last_action_products(session, product_repository: ProductRepository) -> list[Product]:
    for message in reversed(session.messages):
        metadata = message.metadata or {}
        if str(metadata.get("intent", "")).startswith(("add_to_", "remove_from_")) and metadata.get("matched_product_ids"):
            return [
                product
                for product_id in metadata["matched_product_ids"]
                if (product := product_repository.get_product(str(product_id))) is not None
            ]
    return []


def products_from_previous(text: str, previous: list[Product]) -> list[Product]:
    ordinal = selected_ordinal(text)
    if ordinal is not None and ordinal < len(previous):
        return [previous[ordinal]]

    # Moves the products that fit the question to the front and keeps the rest for comparison.
    best = rank_products(previous, enrich_with_polish_lemmas(text), len(previous))
    return best + [product for product in previous if product not in best]


def apply_price_request(products: list[Product], price: PriceRequest, language: str) -> tuple[list[Product], list[str]]:
    notes: list[str] = []
    result = products

    if price.max_price is not None:
        result = [product for product in products if product.price <= price.max_price]
        if result:
            notes.append(budget_note(language, price.max_price))
        elif products:
            result = sorted(products, key=lambda product: product.price)[:3]
            notes.append(over_budget_note(language, price.max_price))

    if price.order:
        result = sorted(result, key=lambda product: product.price, reverse=price.order == "desc")
        notes.append(price_order_note(language, price.order))

    return result, notes


def budget_note(language: str, max_price: float) -> str:
    if language == "en":
        return f"The customer's budget is up to {max_price:.0f} PLN, and all listed products fit it."
    return f"Budżet klienta to do {max_price:.0f} PLN i wszystkie podane produkty się w nim mieszczą."


def over_budget_note(language: str, max_price: float) -> str:
    if language == "en":
        return f"Nothing matching costs {max_price:.0f} PLN or less. Say so honestly and offer the closest cheapest products listed."
    return f"Nic pasującego nie kosztuje {max_price:.0f} PLN lub mniej. Powiedz o tym szczerze i zaproponuj podane najtańsze, najbliższe produkty."


def price_order_note(language: str, order: str) -> str:
    if language == "en":
        return "The products are sorted from the cheapest." if order == "asc" else "The products are sorted from the most expensive."
    return "Produkty są posortowane od najtańszego." if order == "asc" else "Produkty są posortowane od najdroższego."


def select_shown_products(products: list[Product], ai_response: AiResponse) -> list[Product]:
    """Cards must match the text: the customer sees only the products the reply is about."""
    if ai_response.product_ids is not None:
        by_id = {product.id: product for product in products}
        return [by_id[product_id] for product_id in ai_response.product_ids if product_id in by_id]

    if ai_response.provider == "none":
        return products

    # The model forgot its tag, so a refusal or a question must not get a row of unrelated cards.
    reply = fold(ai_response.text)
    return [product for product in products if fold(product.name) in reply]


def off_topic_note(language: str) -> str:
    if language == "en":
        return "This message looks unrelated to the store. Do not answer its question; decline in one friendly sentence and return to lighting."
    return "Ta wiadomość wygląda na niezwiązaną ze sklepem. Nie odpowiadaj na jej pytanie; odmów jednym życzliwym zdaniem i wróć do oświetlenia."


def unclear_note(language: str) -> str:
    if language == "en":
        return "If this continues the conversation about lamps, answer using the history. If it is unrelated to the store, do not answer it; decline in one friendly sentence."
    return "Jeśli to ciąg rozmowy o lampach, odpowiedz na podstawie historii. Jeśli to temat niezwiązany ze sklepem, nie odpowiadaj na niego; odmów jednym życzliwym zdaniem."


def follow_up_note(language: str) -> str:
    if language == "en":
        return "The customer is asking about the products from the previous reply. Answer about them."
    return "Klient pyta o produkty z poprzedniej odpowiedzi. Odpowiedz właśnie o nich."


def build_history(session) -> list[dict[str, str]]:
    """Earlier messages for the model; the newest user message is sent separately with its product data."""
    history: list[dict[str, str]] = []
    for message in session.messages[:-1][-HISTORY_MESSAGES:]:
        content = message.text[:HISTORY_MESSAGE_LENGTH]
        names = (message.metadata or {}).get("matched_product_names")
        if message.role == MessageRole.ASSISTANT and names:
            content = f"{content}\n(Produkty pokazane klientowi: {', '.join(names)})"
        history.append({"role": message.role.value, "content": content})
    return history


def localize_product(product: Product, language: str) -> Product:
    if language != "en":
        return product
    return replace(
        product,
        name=product.attributes.get("english_name") or product.name,
        description=product.attributes.get("english_description") or product.description,
    )


def local_action_reply(intent: str, text: str, products: list[Product], action: dict[str, object] | None) -> AssistantReply:
    return AssistantReply(
        text=text,
        matched_products=products,
        intent=intent,
        provider="local_action",
        model=None,
        action=action,
    )


def remove_command_words(text: str) -> str:
    ignored = {
        "dodaj", "dodac", "dodam", "wrzuc", "wloz", "dorzuc", "add", "put", "zapisz", "save", "zachowaj",
        "do", "to", "my", "the", "a", "moj", "mojego", "mojej", "koszyka", "koszyk", "koszyku", "cart", "basket",
        "biblioteki", "biblioteka", "bibliotece", "library", "prosze", "please", "mi",
    }
    return " ".join(word for word in words_of(text) if word not in ignored)


def filter_products_by_light_preference(products: list[Product], light_preference: str | None) -> list[Product]:
    return [
        product
        for product in products
        if is_product_allowed_for_light_preference(product, light_preference)
    ]


def has_recent_assistant_context(session) -> bool:
    for message in reversed(session.messages[-6:]):
        if message.role.value == "assistant":
            return True
    return False


def get_recent_user_context(session) -> str:
    texts: list[str] = []
    for message in reversed(session.messages[:-1]):
        if message.role.value != "user":
            continue
        normalized = normalize_for_matching(message.text)
        if contains_store_topic(normalized) or contains_light_preference_phrase(normalized):
            texts.append(message.text)
        if len(texts) >= 2:
            break
    return " ".join(reversed(texts))


def build_contextual_search_text(text: str, session) -> str:
    normalized = normalize_for_matching(text)
    recent_context = "" if starts_new_product_search(normalized) else get_recent_user_context(session)
    parts = [recent_context, text, expand_user_light_preferences(normalized)]

    if contains_contextual_choice_phrase(normalized):
        parts.append("cieple neutralne biale zolte jasne")

    return " ".join(part for part in parts if part).strip() or text


def starts_new_product_search(normalized: str) -> bool:
    prefixes = PRODUCT_SUBJECT_PREFIXES | STRONG_NEW_SEARCH_PREFIXES
    return any(phrase in normalized for phrase in NEW_SEARCH_PHRASES) or any(
        word.startswith(prefix)
        for word in normalized.split()
        for prefix in prefixes
    )


def expand_user_light_preferences(normalized: str) -> str:
    expanded: set[str] = set()
    for keyword, synonyms in LIGHT_PREFERENCE_KEYWORDS.items():
        if keyword in normalized:
            expanded.update(synonyms)
    return " ".join(sorted(expanded))


def select_products_for_action(text: str, products: list[Product], wants_all: bool = False) -> list[Product]:
    if wants_all:
        return products

    ordinal = selected_ordinal(text)
    if ordinal is not None and ordinal < len(products):
        return [products[ordinal]]

    for word in words_of(text):
        count = ACTION_NUMBER_WORDS.get(word)
        if count and word not in {"1", "2", "3", "4", "5", "one"}:
            return products[: min(count, len(products))]

    return products[:1]


def build_chat_action(action_type: str, products: list[Product], quantity: int = 1) -> dict[str, object]:
    return {
        "type": action_type,
        "items": [{"product_id": product.id, "quantity": quantity} for product in products],
        "product_ids": [product.id for product in products],
    }


def build_action_reply(language: str, action_type: str, products: list[Product]) -> str:
    names = ", ".join(product.name for product in products)

    if language == "en":
        target = "library" if action_type.endswith("library") else "cart"
        if action_type.startswith("remove_"):
            if not products:
                return choose_response_variant([f"All right, clearing your {target}.", f"Emptying your {target} now."])
            return choose_response_variant([f"Sure, removing it from your {target}: {names}.", f"Done, {names} goes out of your {target}.", f"Okay, I am taking {names} out of your {target}."])
        return choose_response_variant([f"Good choice! Adding to your {target}: {names}.", f"Sure, {names} goes to your {target}.", f"Okay, putting {names} in your {target}.", f"Nice one. Your {target} now gets: {names}."])

    target_to = "biblioteki" if action_type.endswith("library") else "koszyka"
    target_from = "biblioteki" if action_type.endswith("library") else "koszyka"
    if action_type.startswith("remove_"):
        if not products:
            return choose_response_variant([f"W porządku, opróżniam zawartość {target_from}.", f"Dobrze, czyszczę zawartość {target_from}."])
        return choose_response_variant([f"Jasne, usuwam z {target_from}: {names}.", f"Gotowe, {names} znika z {target_from}.", f"Dobrze, wyjmuję z {target_from}: {names}."])
    return choose_response_variant([f"Dobry wybór! Dodaję do {target_to}: {names}.", f"Jasne, {names} już leci do {target_to}.", f"Dobrze, przekazuję do {target_to}: {names}.", f"Świetnie, dorzucam do {target_to}: {names}."])


def build_open_reply(language: str, action_type: str) -> str:
    is_cart = action_type == "open_cart"
    if language == "en":
        target = "cart" if is_cart else "library"
        return choose_response_variant([f"Here is your {target}.", f"Opening your {target}.", f"Sure, take a look at your {target}."])
    target = "koszyk" if is_cart else "bibliotekę"
    return choose_response_variant([f"Już otwieram {target}.", f"Proszę, oto Twój {'koszyk' if is_cart else 'zbiór w bibliotece'}.", f"Jasne, pokazuję {target}."])


def build_which_product_reply(language: str) -> str:
    if language == "en":
        return choose_response_variant(["Which lamp do you mean? Tell me its name, or let me show you a few first.", "I am not sure which product you mean. Could you give me its name?"])
    return choose_response_variant(["O którą lampę chodzi? Podaj nazwę albo najpierw pokażę Ci kilka propozycji.", "Nie jestem pewien, o który produkt chodzi. Podasz jego nazwę?"])


def detect_response_language(text: str, fallback: str) -> str:
    # Lemmas are not used here, because the English "lamp" is also a form of the Polish "lampa".
    words = set(words_of(text))
    has_polish_letters = any(character in "ąćęłńóśźż" for character in text.casefold())

    english_hints = {
        "about", "add", "and", "any", "bathroom", "bedroom", "cart", "cheap", "cheapest", "desk", "delivery", "for", "from", "hello",
        "help", "hi", "how", "lamp", "lamps", "library", "light", "lighting", "looking", "me", "much", "my", "need", "please", "products",
        "reading", "remove", "restroom", "room", "show", "suggest", "tell", "thanks", "the", "want", "warm", "what", "which", "with", "you",
    }
    polish_hints = {
        "biblioteki", "bo", "ciepla", "co", "cos", "czesc", "czerwona", "czerwone", "czy", "dla", "do", "dobry", "dodaj", "dzien", "ile", "jak", "jaka",
        "jakas", "koszyk", "koszyka", "lampa", "lampe", "lampki", "lampy", "mam", "mi", "na", "nie", "niebieska", "niebieskie", "opowiedz", "po", "pokaz",
        "potrzebuje", "prosze", "siema", "siemka", "swiatlo", "szukam", "tak", "wodoodporna", "wodoodporne", "zielona", "zielone",
    }

    english_score = len(words & english_hints)
    polish_score = len(words & polish_hints) + (2 if has_polish_letters else 0)

    if english_score > polish_score:
        return "en"
    if polish_score > english_score:
        return "pl"
    return "en" if fallback == "en" else "pl"


def build_out_of_scope_reply(language: str) -> str:
    if language == "en":
        return choose_response_variant(
            [
                "That is not my area, I am much better with light than with big topics. Is there a room that needs a good lamp?",
                "I will leave that one to the experts. I can help you choose a lamp, though. What are you looking for?",
                "I cannot help with that here, as lamps are my whole world. Shall we find one for you?",
                "Let us stay with lighting, that is where I am actually useful. What room are we working with?",
            ]
        )

    return choose_response_variant(
        [
            "To nie moja działka, lepiej znam się na świetle niż na takich tematach. Masz pomieszczenie, któremu przydałaby się dobra lampa?",
            "Ten temat zostawię specjalistom. Za to w wyborze lampy pomogę chętnie. Czego szukasz?",
            "Tu nie pomogę, bo lampy to cały mój świat. Poszukamy czegoś dla Ciebie?",
            "Zostańmy przy oświetleniu, tu naprawdę się przydam. O jakim pomieszczeniu myślisz?",
        ]
    )


def choose_response_variant(variants: list[str]) -> str:
    return _random.choice(variants)
