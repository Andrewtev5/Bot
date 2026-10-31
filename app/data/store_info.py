"""Demonstration store rules: the project is a mock-up, so edit these freely.

Everything the assistant says about delivery, payment, returns and contact comes from here.
"""
from __future__ import annotations

STORE_FACTS = {
    "pl": {
        "delivery": "Kurier: 15 PLN, 2-3 dni robocze. Paczkomat: 12 PLN, 2-3 dni robocze. Dostawa gratis od 200 PLN.",
        "payment": "Można płacić BLIK-iem, kartą albo przelewem. To sklep demonstracyjny, więc zakup jest symulowany i żadne pieniądze nie są pobierane.",
        "returns": "Na zwrot jest 30 dni od zakupu. Lampa powinna być nieuszkodzona. Wniosek można przygotować po zalogowaniu na konto.",
        "warranty": "Każda lampa ma 24 miesiące gwarancji.",
        "contact": "Kontakt: kontakt@sklep-lamp.example, od poniedziałku do piątku w godzinach 9-17.",
        "orders": "Zakupy i ich historię widać po zalogowaniu na stronie Moje zakupy.",
    },
    "en": {
        "delivery": "Courier: 15 PLN, 2-3 working days. Parcel locker: 12 PLN, 2-3 working days. Free delivery from 200 PLN.",
        "payment": "You can pay by BLIK, card or bank transfer. This is a demonstration store, so a purchase is simulated and no money is charged.",
        "returns": "You have 30 days from purchase to return a lamp. It should be undamaged. You can prepare the request after logging in to your account.",
        "warranty": "Every lamp has a 24-month warranty.",
        "contact": "Contact: kontakt@sklep-lamp.example, Monday to Friday, 9:00-17:00.",
        "orders": "After logging in, your purchases and their history are on the My purchases page.",
    },
}

LIGHTING_TIPS = {
    "pl": {
        "brightness": "Na salon zwykle wystarcza około 150-250 lumenów na metr kwadratowy, a na biurko lub do kuchni przyda się około 300-500.",
        "color_temperature": "Barwę światła podaje się w kelwinach: około 2700 K to ciepłe światło do odpoczynku, 4000 K neutralne do pracy, a powyżej 5000 K chłodne i bardzo jasne.",
        "flicker": "Gdy lampa miga, najpierw sprawdź, czy żarówka jest dobrze wkręcona i pasuje do ściemniacza. Jeśli to nie pomoże, spróbuj innej żarówki, a na koniec skontaktuj się z nami w sprawie gwarancji.",
    },
    "en": {
        "brightness": "A living room usually needs about 150-250 lumens per square metre, while a desk or kitchen is better with about 300-500.",
        "color_temperature": "Light colour is given in kelvin: around 2700 K is warm and relaxing, 4000 K is neutral for work, and above 5000 K is cool and very bright.",
        "flicker": "If a lamp flickers, first check that the bulb is screwed in properly and suits the dimmer. If that does not help, try another bulb, and then contact us about the warranty.",
    },
}


def store_facts_text(language: str) -> str:
    facts = STORE_FACTS["en" if language == "en" else "pl"]
    return "\n".join(f"- {fact}" for fact in facts.values())
