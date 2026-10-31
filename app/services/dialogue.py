"""Understands what a chat message asks for: budget, store question, small talk or a command."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def fold(value: str) -> str:
    """Lowercase text without Polish marks, so "łóżko" and "lozko" compare equal."""
    normalized = unicodedata.normalize("NFKD", value.casefold().replace("ł", "l"))
    return "".join(character for character in normalized if not unicodedata.combining(character))


def words_of(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", fold(value))


def has_prefix(words: list[str], prefixes: set[str]) -> bool:
    return any(word.startswith(prefix) for word in words for prefix in prefixes)


def has_phrase(text: str, phrases: set[str]) -> bool:
    joined = f" {' '.join(words_of(text))} "
    return any(f" {phrase} " in joined for phrase in phrases)


BUDGET_PATTERN = re.compile(
    r"(?:\bdo\b|\bponizej\b|\bponiżej\b|\bmaks\w*\b|\bmax\b|\bbudzet\w*\b|\bbudżet\w*\b|\bunder\b|\bbelow\b|\bup to\b|\bless than\b)"
    r"\s*(?:to\s*|of\s*|okolo\s*|około\s*)?(\d{1,5})\s*(?:pln|zl|zł|zlotych|złotych)?\b",
    re.IGNORECASE,
)
PRICE_WITH_CURRENCY_PATTERN = re.compile(r"\b(\d{1,5})\s*(?:pln|zl|zł|zlotych|złotych)\b", re.IGNORECASE)
PRICE_PHRASE_PATTERN = re.compile(
    r"(?:\bdo\b|\bponiżej\b|\bponizej\b|\bmaks\w*\b|\bmax\b|\bbudżet\w*\b|\bbudzet\w*\b|\bunder\b|\bbelow\b|\bup to\b|\bless than\b)?"
    r"\s*\d{1,5}\s*(?:pln|zł|zl|złotych|zlotych)?\b",
    re.IGNORECASE,
)
QUANTITY_PATTERN = re.compile(r"\b(\d{1,3})\s*(?:szt\w*|pieces?|pcs)\b", re.IGNORECASE)

CHEAPEST_PREFIXES = {"najtan", "najnizsz", "cheapest", "lowest"}
MOST_EXPENSIVE_PREFIXES = {"najdroz", "najwyzsz", "priciest", "dearest"}
CHEAPER_PREFIXES = {"tansz", "taniej", "cheaper"}
PRICIER_PREFIXES = {"drozsz", "drozej", "pricier"}

GENERIC_PRODUCT_WORDS = {
    "a", "cos", "czegos", "dla", "do", "i", "jakas", "jakies", "jaka", "jakis", "lamp", "lampa", "lampe", "lampka",
    "lampke", "lampki", "lampy", "light", "lights", "macie", "me", "mi", "na", "pokaz", "poprosze", "prosze", "show",
    "szukam", "the", "w", "z",
}

STORE_TOPIC_PREFIXES = {
    "delivery": {"dostaw", "wysylk", "wysyl", "przesylk", "kurier", "paczkomat", "deliver", "shipping"},
    "payment": {"platnos", "platn", "zaplac", "placic", "placi", "blik", "przelew", "payment", "paying"},
    "returns": {"zwrot", "zwroc", "reklamac", "refund"},
    "warranty": {"gwarancj", "warrant", "guarantee"},
    "contact": {"kontakt", "contact", "support", "infolini", "email"},
    "orders": {"zamowien", "zamowil", "order"},
}
STORE_TOPIC_WORDS = {"returns": {"return", "oddac", "oddam"}, "payment": {"pay", "card", "karta", "karte", "karty"}}

SMALL_TALK_PHRASES = {
    "thanks": {"dzieki", "dziekuje", "dziekuje bardzo", "wielkie dzieki", "thanks", "thank you", "thx"},
    "goodbye": {"do widzenia", "do zobaczenia", "na razie", "pa", "pa pa", "bye", "goodbye", "see you"},
    "how_are_you": {"jak sie masz", "co slychac", "co tam", "jak leci", "how are you", "whats up"},
    "identity": {"kim jestes", "kto ty", "czy jestes botem", "jestes botem", "jestes czlowiekiem", "who are you", "are you a bot", "are you human"},
    "capabilities": {"co potrafisz", "w czym mozesz pomoc", "jak dzialasz", "jak mozesz pomoc", "pomoc", "pomocy", "help", "what can you do"},
    "unsure": {"nie wiem", "nie wiem co wybrac", "sam nie wiem", "sama nie wiem", "trudno powiedziec", "nie jestem pewien", "nie jestem pewna", "i dont know", "not sure", "im not sure"},
    "frustration": {"nie rozumiesz", "bez sensu", "to nie to", "glupi bot", "nie dziala", "you dont understand", "that is wrong", "useless", "not what i asked"},
    "compliment": {"super", "swietnie", "fajnie", "fajne", "dobra robota", "great", "nice", "cool", "awesome", "perfect"},
    "agreement": {"ok", "okej", "okay", "dobra", "dobrze", "spoko", "tak", "jasne", "yes", "sure", "yep"},
    "negative": {"nie", "no", "nope", "raczej nie", "nie chce"},
}

LIGHTING_TIP_PREFIXES = {
    "brightness": {"lumen", "brightness"},
    "color_temperature": {"kelwin", "kelvin"},
    "flicker": {"miga", "migoc", "mruga", "flicker"},
}
COLOR_TEMPERATURE_PHRASES = {"co to jest barwa swiatla", "barwa swiatla", "temperatura barwowa", "what is color temperature", "color temperature", "colour temperature"}

ADD_VERB_PREFIXES = {"dodaj", "dodac", "dodam", "wrzuc", "wloz", "dorzuc", "add", "put"}
REMOVE_VERB_PREFIXES = {"usun", "wyrzuc", "skasuj", "zabierz", "remove", "delete", "take"}
OPEN_VERB_PREFIXES = {"pokaz", "otworz", "sprawdz", "show", "open", "view"}
CART_PREFIXES = {"koszyk", "cart", "basket"}
LIBRARY_PREFIXES = {"bibliotek", "library", "ulubion", "favourite", "favorite"}
SAVE_PREFIXES = {"zapisz", "save", "zachowaj"}
CART_CONTENT_PHRASES = {"co mam w koszyku", "co jest w koszyku", "whats in my cart", "what is in my cart"}
LIBRARY_CONTENT_PHRASES = {"co mam w bibliotece", "co jest w bibliotece", "whats in my library", "what is in my library"}

# Compared without folding, because "ją" means the product while "ja" means "I".
PRONOUN_WORDS = {"ją", "nią", "tą", "tę", "tej", "te", "tych", "nich", "niej", "tamta", "tamtą", "tamte", "tego", "them", "it", "one", "those", "these"}
WHICH_PREFIXES = {"ktora", "ktore", "ktory", "ktorej", "ktorego", "ktorych", "which"}
ORDINAL_PREFIXES = {
    "pierwsz": 0, "first": 0,
    "drug": 1, "second": 1,
    "trzec": 2, "third": 2,
    "czwart": 3, "fourth": 3,
    "piat": 4, "fifth": 4,
}
ALL_WORDS = {"all", "everything", "wszystkie", "wszystko", "wszystkich", "calosc"}
RECOMMENDATION_PREFIXES = {
    "polec", "doradz", "wybierz", "wybrac", "zaproponuj", "szukam", "potrzebuj", "chce", "chcialbym", "chcialabym", "macie", "masz",
    "prezent", "upomin", "mieszkan", "dom", "wnetrz", "czytan", "gabinet", "biuro", "gift", "home", "recommend", "suggest", "advise", "looking", "need", "want",
}


@dataclass(frozen=True, slots=True)
class PriceRequest:
    max_price: float | None = None
    order: str | None = None
    relative: str | None = None


@dataclass(frozen=True, slots=True)
class ChatCommand:
    type: str
    wants_all: bool = False


def parse_price_request(text: str) -> PriceRequest:
    match = BUDGET_PATTERN.search(text) or PRICE_WITH_CURRENCY_PATTERN.search(text)
    max_price = float(match.group(1)) if match else None

    words = words_of(text)
    order = None
    if has_prefix(words, CHEAPEST_PREFIXES):
        order = "asc"
    elif has_prefix(words, MOST_EXPENSIVE_PREFIXES):
        order = "desc"

    relative = None
    if has_prefix(words, CHEAPER_PREFIXES):
        relative = "cheaper"
    elif has_prefix(words, PRICIER_PREFIXES):
        relative = "pricier"

    return PriceRequest(max_price=max_price, order=order, relative=relative)


def remove_price_words(text: str) -> str:
    return " ".join(PRICE_PHRASE_PATTERN.sub(" ", text).split())


def is_generic_product_request(text: str) -> bool:
    """True for "najtańsza lampa": the whole catalog qualifies, because nothing narrows the type."""
    words = {
        word
        for word in words_of(remove_price_words(text))
        if not has_prefix([word], CHEAPEST_PREFIXES | MOST_EXPENSIVE_PREFIXES | CHEAPER_PREFIXES | PRICIER_PREFIXES)
    }
    return words <= GENERIC_PRODUCT_WORDS


def detect_store_topic(text: str) -> str | None:
    words = words_of(text)
    for topic, prefixes in STORE_TOPIC_PREFIXES.items():
        if has_prefix(words, prefixes):
            return topic
    for topic, exact_words in STORE_TOPIC_WORDS.items():
        if set(words) & exact_words:
            return topic
    return None


def detect_small_talk(text: str) -> str | None:
    normalized = " ".join(words_of(text))
    if len(normalized.split()) > 6:
        return None

    exact = next((kind for kind, phrases in SMALL_TALK_PHRASES.items() if normalized in phrases), None)
    if exact:
        return exact

    for kind in ("thanks", "goodbye", "how_are_you", "identity", "capabilities", "unsure", "frustration"):
        if has_phrase(text, SMALL_TALK_PHRASES[kind]):
            return kind
    return None


def detect_lighting_tip(text: str) -> str | None:
    words = words_of(text)
    for tip, prefixes in LIGHTING_TIP_PREFIXES.items():
        if has_prefix(words, prefixes):
            return tip
    return "color_temperature" if has_phrase(text, COLOR_TEMPERATURE_PHRASES) else None


def detect_command(text: str) -> ChatCommand | None:
    words = words_of(text)
    wants_all = bool(set(words) & ALL_WORDS)
    mentions_cart = has_prefix(words, CART_PREFIXES)
    mentions_library = has_prefix(words, LIBRARY_PREFIXES)
    target = "cart" if mentions_cart else "library" if mentions_library else None

    if has_phrase(text, {"nie dodawaj", "nie usuwaj", "dont add", "dont remove", "do not add", "do not remove"}):
        return None

    if has_prefix(words, REMOVE_VERB_PREFIXES) and target:
        return ChatCommand(f"remove_from_{target}", wants_all)
    if has_phrase(text, CART_CONTENT_PHRASES):
        return ChatCommand("open_cart")
    if has_phrase(text, LIBRARY_CONTENT_PHRASES):
        return ChatCommand("open_library")
    if target and has_prefix(words, ADD_VERB_PREFIXES):
        return ChatCommand(f"add_to_{target}", wants_all)
    if target and has_prefix(words, OPEN_VERB_PREFIXES) and len(words) <= 5:
        return ChatCommand(f"open_{target}")
    if mentions_library or has_prefix(words, SAVE_PREFIXES):
        return ChatCommand("add_to_library", wants_all)
    if mentions_cart and (has_phrase(text, {"do koszyka", "to cart", "to my cart", "to the cart", "to basket"})):
        return ChatCommand("add_to_cart", wants_all)
    if mentions_cart and len(words) <= 2:
        return ChatCommand("open_cart")
    return None


def selected_ordinal(text: str) -> int | None:
    for word in words_of(text):
        for prefix, index in ORDINAL_PREFIXES.items():
            if word.startswith(prefix):
                return index
    return None


def parse_quantity(text: str) -> int:
    match = QUANTITY_PATTERN.search(text)
    return min(max(int(match.group(1)), 1), 999) if match else 1


def refers_to_previous_products(text: str) -> bool:
    raw_words = re.findall(r"[^\W_]+", text.casefold())
    words = words_of(text)
    if set(raw_words) & PRONOUN_WORDS or selected_ordinal(text) is not None:
        return True

    # "lampa, która świeci" is a new request, while "a która jest najlepsza" asks about the shown products.
    return bool(words) and (
        has_prefix(words[:1], WHICH_PREFIXES)
        or (words[0] in {"a", "i", "to", "and", "so"} and has_prefix(words[1:2], WHICH_PREFIXES))
    )


def asks_for_recommendation(text: str) -> bool:
    return has_prefix(words_of(text), RECOMMENDATION_PREFIXES)
