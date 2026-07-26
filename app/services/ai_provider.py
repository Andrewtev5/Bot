from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings
from app.domain.models import Product


@dataclass(slots=True)
class AiResponse:
    text: str
    provider: str
    model: str | None = None


class AiProvider(Protocol):
    def generate_consultation(self, user_text: str, products: list[Product], language: str) -> AiResponse:
        ...


class NoAiProvider:
    def generate_consultation(self, user_text: str, products: list[Product], language: str) -> AiResponse:
        text = build_fallback_reply(user_text=user_text, products=products, language=language)
        return AiResponse(text=text, provider="none", model=None)


class GrokAiProvider:
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.grok_api_key
        self._model = settings.grok_model
        self._base_url = settings.grok_base_url
        self._timeout = settings.grok_timeout_seconds

    def generate_consultation(self, user_text: str, products: list[Product], language: str) -> AiResponse:
        if not self._api_key:
            return NoAiProvider().generate_consultation(user_text, products, language)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": build_system_prompt(language)},
                {"role": "user", "content": build_user_prompt(user_text, products, language)},
            ],
            "temperature": 0.55,
        }

        response = httpx.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"].strip()
        return AiResponse(text=text, provider="grok", model=self._model)


def build_ai_provider(settings: Settings) -> AiProvider:
    if settings.ai_provider == "grok":
        return GrokAiProvider(settings)
    return NoAiProvider()


def build_system_prompt(language: str) -> str:
    if language == "en":
        return (
            "You are a warm, natural and professional consultant for a Polish online lighting store. "
            "Sound like a real helpful person, not like a template. Vary your wording, do not start every answer "
            "the same way, and keep the tone polite, calm and practical. "
            "If the customer only greets you, greet them back naturally and ask how you can help with lighting. "
            "Help only with lamps, bulbs, lighting, product choice, product comparison, cart, library, orders, "
            "delivery, returns, warranty, and normal store-service topics. "
            "Do not discuss politics, war, violence, religion, medicine, law, finance, programming, school assignments, "
            "or any topic unrelated to the store. If the customer asks about an unrelated topic, politely refuse and "
            "bring the conversation back to choosing lighting. "
            "Use only the products passed by the backend. Do not invent product names, prices, availability, discounts, "
            "delivery rules, technical parameters, or guarantees. "
            "When products are available, recommend the best matches briefly and mention why they fit. "
            "If no products are passed and the message is not just a greeting, ask one short clarifying question about "
            "the room, preferred light color, style, budget, or lamp type. "
            "Reply in English."
        )

    return (
        "Jesteś życzliwym, naturalnym i profesjonalnym konsultantem polskiego sklepu internetowego z oświetleniem. "
        "Pisz jak pomocny człowiek, a nie jak szablon. Używaj różnych sformułowań, nie zaczynaj każdej odpowiedzi "
        "tak samo, zachowuj uprzejmy, spokojny i praktyczny ton. "
        "Jeśli klient tylko się wita, odpowiedz naturalnym powitaniem i zapytaj, w czym możesz pomóc przy wyborze "
        "oświetlenia. "
        "Pomagasz wyłącznie w sprawach związanych z lampami, żarówkami, oświetleniem, doborem produktu, "
        "porównaniem produktów, koszykiem, biblioteką, zamówieniami, dostawą, zwrotami, gwarancją i standardową "
        "obsługą sklepu. "
        "Nie rozmawiasz o polityce, wojnie, przemocy, religii, medycynie, prawie, finansach, programowaniu, "
        "pracach szkolnych ani żadnych tematach niezwiązanych ze sklepem. Jeśli klient pyta o temat spoza sklepu, "
        "grzecznie odmów i wróć do pomocy w wyborze oświetlenia. "
        "Korzystaj wyłącznie z produktów przekazanych przez backend. Nie wymyślaj nazw produktów, cen, dostępności, "
        "rabatów, warunków dostawy, parametrów technicznych ani gwarancji. "
        "Gdy produkty są dostępne, krótko poleć najlepsze dopasowania i wyjaśnij, dlaczego pasują. "
        "Jeśli lista produktów jest pusta, a wiadomość nie jest samym powitaniem, zadaj jedno krótkie pytanie "
        "doprecyzowujące o pomieszczenie, barwę światła, styl, budżet albo typ lampy. "
        "Odpowiadaj po polsku."
    )


def build_user_prompt(user_text: str, products: list[Product], language: str) -> str:
    product_lines = "\n".join(format_product_for_ai(product) for product in products) or "Brak dopasowanych produktów."
    return (
        f"Język odpowiedzi: {language}\n"
        f"Wiadomość klienta:\n{user_text}\n\n"
        f"Dopasowane produkty z bazy:\n{product_lines}"
    )


def format_product_for_ai(product: Product) -> str:
    attributes = ", ".join(f"{key}: {value}" for key, value in product.attributes.items()) or "brak atrybutów"
    tags = ", ".join(product.tags) or "brak tagów"
    return (
        f"- id: {product.id}; name: {product.name}; price: {product.price:.0f} {product.currency}; "
        f"kategoria: {product.category}; stan: {product.stock_status}; tags: {tags}; "
        f"atrybuty: {attributes}; opis: {product.description}"
    )


def build_fallback_reply(user_text: str, products: list[Product], language: str) -> str:
    if is_greeting_like(user_text):
        return localized(
            language,
            en="Hi, I am your AI assistant for the lighting store. Tell me what kind of lamp or light you are looking for, and I will help you choose.",
            pl="Cześć, jestem Twoim asystentem AI w sklepie z oświetleniem. Napisz, jakiej lampy albo jakiego światła szukasz, a pomogę Ci wybrać.",
        )

    if not products:
        return localized(
            language,
            en="I can help with choosing lighting. Tell me the room, preferred light color and budget.",
            pl="Mogę pomóc w wyborze oświetlenia. Napisz, do jakiego pomieszczenia, w jakiej barwie światła i w jakim budżecie szukasz lampy.",
        )

    intro = localized(
        language,
        en="I found matching products in the database:",
        pl="Znalazłem pasujące produkty w bazie:",
    )
    lines = [intro]
    lines.extend(f"- {product.name}: {product.price:.0f} {product.currency}. {product.description}" for product in products)
    return "\n".join(lines)


def localized(language: str, en: str, pl: str) -> str:
    if language == "en":
        return en
    return pl


def is_greeting_like(text: str) -> bool:
    normalized = text.strip().casefold()
    return len(normalized.split()) <= 5 and any(
        greeting in normalized
        for greeting in {
            "cześć",
            "czesc",
            "dzień dobry",
            "dzien dobry",
            "hej",
            "hello",
            "hi",
            "siema",
            "siemka",
            "witam",
        }
    )
