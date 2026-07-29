from __future__ import annotations

from dataclasses import dataclass
from random import SystemRandom
from typing import Protocol

import httpx

from app.core.config import Settings
from app.domain.models import Product

_random = SystemRandom()


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
            "temperature": 0.72,
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
            "Reply only in English. Never use Russian or any Russian wording. "
            "Speak like a helpful human consultant, not like a fixed template. Vary every allowed type of answer: "
            "greetings, clarifying questions, product recommendations, product explanations, comparisons, follow-up answers, "
            "cart/library guidance, delivery, returns, warranty, price questions, lack of matches and polite refusals. "
            "Do not start every answer the same way. Keep answers short, useful and conversational. "
            "If the customer greets you, greet them naturally and ask how you can help with lighting. "
            "If the customer is unsure, offer one simple question or two clear directions, for example warm vs neutral light. "
            "If products are available, recommend the best matches briefly and explain why they fit. "
            "If the customer asks about a specific product from the provided list, explain only that product using its provided data. "
            "If they ask for more options, suggest alternatives from the provided products without repeating the same wording. "
            "Help only with lamps, bulbs, lighting, product choice, product comparison, cart, library, orders, delivery, returns, "
            "warranty, and normal store-service topics. "
            "Do not discuss politics, war, violence, religion, medicine, law, finance, programming, school assignments, meals, "
            "personal life, or anything unrelated to the store. If the customer asks about an unrelated topic, politely refuse "
            "and return to lighting. "
            "Use only products passed by the backend. Do not invent names, prices, availability, discounts, delivery rules, "
            "technical parameters or guarantees."
        )

    return (
        "Jesteś życzliwym, naturalnym i profesjonalnym konsultantem polskiego sklepu internetowego z oświetleniem. "
        "Odpowiadaj wyłącznie po polsku. Nigdy nie używaj języka rosyjskiego ani rosyjskich sformułowań. "
        "Pisz jak pomocny człowiek, a nie jak stały szablon. Różnicuj każdy dozwolony typ odpowiedzi: powitania, "
        "pytania doprecyzowujące, rekomendacje produktów, opisy produktów, porównania, odpowiedzi kontynuujące rozmowę, "
        "pomoc z koszykiem i biblioteką, dostawę, zwroty, gwarancję, pytania o cenę, brak wyników i grzeczne odmowy. "
        "Nie zaczynaj każdej odpowiedzi tak samo. Odpowiadaj krótko, użytecznie i naturalnie. "
        "Jeśli klient się wita, przywitaj się naturalnie i zapytaj, jak możesz pomóc w wyborze oświetlenia. "
        "Jeśli klient nie jest pewien, zadaj jedno proste pytanie albo zaproponuj dwa jasne kierunki, na przykład światło ciepłe lub neutralne. "
        "Gdy produkty są dostępne, krótko poleć najlepsze dopasowania i wyjaśnij, dlaczego pasują. "
        "Jeśli klient pyta o konkretny produkt z przekazanej listy, opisz tylko ten produkt i tylko na podstawie danych z backendu. "
        "Jeśli prosi o kolejne opcje, zaproponuj alternatywy z przekazanych produktów bez powtarzania tej samej formułki. "
        "Pomagasz tylko w sprawach związanych z lampami, żarówkami, oświetleniem, doborem produktu, porównaniem produktów, "
        "koszykiem, biblioteką, zamówieniami, dostawą, zwrotami, gwarancją i standardową obsługą sklepu. "
        "Nie rozmawiasz o polityce, wojnie, przemocy, religii, medycynie, prawie, finansach, programowaniu, pracach szkolnych, "
        "jedzeniu, życiu prywatnym ani tematach niezwiązanych ze sklepem. Jeśli klient pyta o temat spoza sklepu, grzecznie odmów "
        "i wróć do pomocy w wyborze oświetlenia. "
        "Korzystaj wyłącznie z produktów przekazanych przez backend. Nie wymyślaj nazw produktów, cen, dostępności, rabatów, "
        "warunków dostawy, parametrów technicznych ani gwarancji."
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
    intent = detect_simple_fallback_intent(user_text)

    if intent == "greeting":
        return choose_variant(
            language,
            en=[
                "Hi, I am your AI assistant for the lighting store. Tell me what room or mood you are planning, and I will help you choose.",
                "Hello. I can help you find the right lamp, bulb or lighting style. What are you looking for today?",
                "Hi there. Tell me whether you need light for a bathroom, bedroom, desk or another place, and I will suggest something suitable.",
                "Good to see you. I can help with warm, neutral or decorative lighting. What should we look for?",
                "Hey. If you describe the room and the kind of light you like, I will narrow the catalog down for you.",
            ],
            pl=[
                "Cześć, jestem Twoim asystentem AI w sklepie z oświetleniem. Napisz, do jakiego pomieszczenia szukasz światła, a pomogę Ci wybrać.",
                "Hej. Mogę pomóc dobrać lampę, żarówkę albo styl oświetlenia. Czego dziś szukasz?",
                "Dzień dobry. Powiedz, czy chodzi o łazienkę, sypialnię, biurko czy inne miejsce, a zaproponuję coś sensownego.",
                "Miło Cię widzieć. Mogę pomóc z ciepłym, neutralnym albo dekoracyjnym światłem. Od czego zaczynamy?",
                "Hej, opisz krótko pomieszczenie i klimat światła, a zawężę katalog do sensownych propozycji.",
            ],
        )

    if products:
        return build_product_fallback_reply(user_text, products, language, intent)

    return build_no_products_fallback_reply(user_text, language, intent)


def build_product_fallback_reply(user_text: str, products: list[Product], language: str, intent: str) -> str:
    if intent == "price":
        intro = choose_variant(
            language,
            en=[
                "Here are the prices for the closest matches:",
                "Price-wise, these options are worth checking:",
                "I found these products with their current catalog prices:",
            ],
            pl=[
                "Cenowo wygląda to tak dla najbliższych dopasowań:",
                "Pod kątem ceny warto sprawdzić te opcje:",
                "Znalazłem takie produkty z cenami z katalogu:",
            ],
        )
    elif intent == "delivery":
        intro = choose_variant(
            language,
            en=[
                "I can help choose the product here; delivery details should be confirmed in the store checkout. Product-wise, these fit:",
                "For delivery, use the store checkout as the source of truth. From the catalog, I would look at:",
                "I do not want to invent delivery rules, but I can point you to suitable products first:",
            ],
            pl=[
                "Mogę pomóc dobrać produkt, a szczegóły dostawy najlepiej sprawdzić przy finalizacji zamówienia. Produktowo pasują:",
                "Warunki dostawy potraktuj jako informację ze sklepu przy zamówieniu. Z katalogu wybrałbym:",
                "Nie chcę wymyślać zasad dostawy, ale mogę najpierw wskazać pasujące produkty:",
            ],
        )
    elif intent == "return":
        intro = choose_variant(
            language,
            en=[
                "Returns should follow the store rules, but I can still help you choose a safer match:",
                "For return details, check the store policy. To reduce the chance of a bad choice, I would consider:",
                "I cannot invent return terms, but these options look like good matches:",
            ],
            pl=[
                "Zwroty powinny iść zgodnie z zasadami sklepu, ale mogę pomóc wybrać trafniejszy produkt:",
                "Szczegóły zwrotu sprawdź w regulaminie sklepu. Żeby zmniejszyć ryzyko nietrafionego wyboru, rozważyłbym:",
                "Nie będę wymyślać warunków zwrotu, ale te opcje wyglądają na dobre dopasowania:",
            ],
        )
    elif intent == "details":
        intro = choose_variant(
            language,
            en=[
                "I can describe these options based on the catalog data:",
                "Here is the practical summary of the matched products:",
                "Based on the product descriptions, this is what stands out:",
            ],
            pl=[
                "Mogę opisać te opcje na podstawie danych z katalogu:",
                "Praktycznie wygląda to tak dla dopasowanych produktów:",
                "Z opisów produktów najbardziej wyróżnia się to:",
            ],
        )
    elif intent == "more":
        intro = choose_variant(
            language,
            en=[
                "Sure, here are a few more options:",
                "Of course, I can show another direction:",
                "Here are additional catalog suggestions:",
            ],
            pl=[
                "Jasne, mam jeszcze kilka innych propozycji:",
                "Oczywiście, mogę pokazać też inny kierunek:",
                "Dorzucam kolejne propozycje z katalogu:",
            ],
        )
    else:
        intro = choose_variant(
            language,
            en=[
                "I found a few options that can fit:",
                "These products look like the closest matches:",
                "Here are some suggestions from the catalog:",
                "I would start with these options:",
                "This set should be a reasonable starting point:",
            ],
            pl=[
                "Znalazłem kilka propozycji, które mogą pasować:",
                "Te produkty wyglądają na najbliższe dopasowania:",
                "Mam dla Ciebie takie propozycje z katalogu:",
                "Na początek wybrałbym te opcje:",
                "Ten zestaw wygląda na dobry punkt startowy:",
            ],
        )

    lines = [intro]
    lines.extend(format_product_line(product, language) for product in products)
    return "\n".join(lines)


def build_no_products_fallback_reply(user_text: str, language: str, intent: str) -> str:
    if intent == "help":
        return choose_variant(
            language,
            en=[
                "I can help you choose a lamp, compare options, explain products, or guide you toward the cart and library. Tell me the room first.",
                "You can ask me for bathroom lighting, bedroom mood light, desk lamps, warm or neutral light, and I will search the catalog.",
                "Describe the room, color of light, style or budget, and I will suggest products from the database.",
            ],
            pl=[
                "Mogę pomóc wybrać lampę, porównać opcje, opisać produkt albo podpowiedzieć przy koszyku i bibliotece. Zacznijmy od pomieszczenia.",
                "Możesz zapytać o światło do łazienki, sypialni, na biurko, ciepłe albo neutralne, a ja przeszukam katalog.",
                "Opisz pomieszczenie, barwę światła, styl albo budżet, a zaproponuję produkty z bazy.",
            ],
        )

    if intent == "delivery":
        return choose_variant(
            language,
            en=[
                "Delivery details are handled by the store, but I can first help you choose the right lamp. What product type do you need?",
                "I do not want to invent delivery rules. Tell me what lamp you are considering, and I will help with the product choice.",
            ],
            pl=[
                "Szczegóły dostawy obsługuje sklep, ale mogę najpierw pomóc dobrać właściwą lampę. Jakiego typu produktu szukasz?",
                "Nie chcę wymyślać zasad dostawy. Napisz, jaką lampę rozważasz, a pomogę w wyborze produktu.",
            ],
        )

    if intent == "return":
        return choose_variant(
            language,
            en=[
                "Return rules should come from the store policy. I can help you choose more accurately so the product fits from the start.",
                "For returns, check the store policy. If you tell me the room and light color, I will help you avoid a poor match.",
            ],
            pl=[
                "Zasady zwrotu powinny wynikać z regulaminu sklepu. Mogę za to pomóc dobrać produkt trafniej już na początku.",
                "W sprawie zwrotu sprawdź regulamin sklepu. Jeśli podasz pomieszczenie i barwę światła, pomogę uniknąć nietrafionego wyboru.",
            ],
        )

    return choose_variant(
        language,
        en=[
            "I can help with that, but I need one detail: which room is this lighting for?",
            "Tell me a little more: do you prefer warm, neutral or brighter white light?",
            "I need a bit more context. What room, style or budget should I use for the search?",
            "Sure. To choose well, tell me whether this should be practical light, cozy mood light or something decorative.",
            "Give me one clue: room, color of light, style or budget. Then I can narrow it down.",
        ],
        pl=[
            "Mogę pomóc, tylko potrzebuję jednego szczegółu: do jakiego pomieszczenia ma być to oświetlenie?",
            "Doprecyzuj proszę: wolisz światło ciepłe, neutralne czy jaśniejsze białe?",
            "Potrzebuję trochę więcej kontekstu. Podaj pomieszczenie, styl albo budżet, a dobiorę lepsze propozycje.",
            "Jasne. Żeby dobrze dobrać produkt, powiedz, czy chodzi o światło praktyczne, przytulne czy bardziej dekoracyjne.",
            "Daj mi jedną wskazówkę: pomieszczenie, barwę światła, styl albo budżet. Wtedy zawężę wybór.",
        ],
    )


def detect_simple_fallback_intent(text: str) -> str:
    normalized = text.strip().casefold()
    if is_greeting_like(text):
        return "greeting"
    if any(token in normalized for token in {"help", "pomoc", "co potrafisz", "jak działasz", "jak dzialasz"}):
        return "help"
    if any(token in normalized for token in {"delivery", "dostawa", "wysyłka", "wysylka"}):
        return "delivery"
    if any(token in normalized for token in {"return", "zwrot", "reklamacja"}):
        return "return"
    if any(token in normalized for token in {"price", "cena", "koszt", "ile"}):
        return "price"
    if any(token in normalized for token in {"opowiedz", "opis", "szczegóły", "szczegoly", "details", "describe"}):
        return "details"
    if any(token in normalized for token in {"jeszcze", "inne", "inny", "more", "another", "next"}):
        return "more"
    return "recommendation"


def format_product_line(product: Product, language: str) -> str:
    if language == "en":
        return f"- {product.name}: {product.price:.0f} {product.currency}. {product.description}"
    return f"- {product.name}: {product.price:.0f} {product.currency}. {product.description}"


def choose_variant(language: str, en: list[str], pl: list[str]) -> str:
    variants = en if language == "en" else pl
    return _random.choice(variants)


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
