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
                {"role": "user", "content": build_user_prompt(user_text, products)},
            ],
            "temperature": 0.3,
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
    return (
        "You are a polite consultant for an online lamp store. "
        "Answer only from the products provided by the backend. "
        "Do not invent product names, prices, availability, discounts, or delivery terms. "
        "If the product list is empty, ask one short clarifying question. "
        f"Reply in this language: {language}."
    )


def build_user_prompt(user_text: str, products: list[Product]) -> str:
    product_lines = "\n".join(format_product_for_ai(product) for product in products) or "No matched products."
    return f"Customer message:\n{user_text}\n\nMatched products from database:\n{product_lines}"


def format_product_for_ai(product: Product) -> str:
    attributes = ", ".join(f"{key}: {value}" for key, value in product.attributes.items()) or "no attributes"
    tags = ", ".join(product.tags) or "no tags"
    return (
        f"- id: {product.id}; name: {product.name}; price: {product.price:.0f} {product.currency}; "
        f"category: {product.category}; stock: {product.stock_status}; tags: {tags}; "
        f"attributes: {attributes}; description: {product.description}"
    )


def build_fallback_reply(user_text: str, products: list[Product], language: str) -> str:
    if not products:
        return localized(
            language,
            ru="Я пока работаю без подключенного AI. Напишите, для какой комнаты нужна лампа и какой бюджет.",
            en="AI is not connected yet. Tell me the room and your budget, and I will use the catalog data.",
            pl="AI nie jest jeszcze podlaczone. Napisz, do jakiego pokoju potrzebujesz lampy i jaki masz budzet.",
        )

    intro = localized(
        language,
        ru="Пока AI-ключ не подключен, я могу показать подходящие товары из базы:",
        en="The AI key is not connected yet, but I can show matching products from the database:",
        pl="Klucz AI nie jest jeszcze podlaczony, ale moge pokazac pasujace produkty z bazy:",
    )
    lines = [intro]
    lines.extend(f"- {product.name}: {product.price:.0f} {product.currency}. {product.description}" for product in products)
    return "\n".join(lines)


def localized(language: str, ru: str, en: str, pl: str) -> str:
    if language == "en":
        return en
    if language == "pl":
        return pl
    return ru
