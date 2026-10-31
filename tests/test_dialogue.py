import pytest

from app.domain.models import Product
from app.repositories.product_repository import InMemoryProductRepository
from app.repositories.session_repository import InMemorySessionRepository
from app.services.ai_provider import AiResponse, Consultation, NoAiProvider, clean_reply_text, split_product_tag
from app.services.chat_service import ChatService, detect_response_language, is_out_of_scope
from app.services.dialogue import (
    detect_command,
    detect_small_talk,
    detect_store_topic,
    parse_price_request,
    refers_to_previous_products,
)


def make_product(product_id: str, name: str, price: float, description: str = "Lampa.", **attributes) -> Product:
    return Product(
        id=product_id,
        name=name,
        price=price,
        currency="PLN",
        category="Lampa",
        description=description,
        tags=[name],
        keywords=[],
        stock_status="in_stock",
        attributes=attributes,
    )


CATALOG = [
    make_product("floor-cheap", "Lampa podłogowa Arc", 40, "Wysoka lampa do salonu.", english_name="Arc Floor Lamp", english_description="Tall living room lamp."),
    make_product("floor-mid", "Lampa podłogowa Tripod", 90, "Lampa podłogowa do czytania."),
    make_product("floor-expensive", "Lampa podłogowa Bankierska", 150, "Elegancka lampa podłogowa."),
    make_product("bedside-cheap", "Lampka nocna Cloud", 25, "Mała lampka nocna do sypialni."),
    make_product("bedside-mid", "Ceramiczna lampa nocna", 60, "Ceramiczna lampa do sypialni."),
    make_product("desk-lamp", "Lampa biurkowa", 70, "Lampa na biurko do pracy."),
]


class RecordingProvider:
    def __init__(self, product_ids=None):
        self.consultations: list[Consultation] = []
        self.product_ids = product_ids

    def generate_consultation(self, consultation: Consultation) -> AiResponse:
        self.consultations.append(consultation)
        return AiResponse(text="odpowiedź", provider="none", product_ids=self.product_ids)


def build_service(provider=None) -> ChatService:
    return ChatService(
        session_repository=InMemorySessionRepository(),
        product_repository=InMemoryProductRepository(CATALOG),
        ai_provider=provider or NoAiProvider(),
        max_products_for_ai=5,
    )


@pytest.mark.parametrize(
    "text",
    [
        "Co polecacie?",
        "Szukam czegoś do czytania",
        "Mam małe mieszkanie, co wybrać?",
        "Szukam prezentu dla mamy",
        "Macie coś do gabinetu?",
        "dzięki",
        "nie wiem co wybrać",
        "a jakieś tańsze?",
        "opowiedz o drugiej",
        "która z nich jest najlepsza?",
        "Lampa do sądu rodzinnego",
        "Lampa dla prawnika do biura",
        "Lampa do pokoju na wojnę z ciemnością",
        "Ile lumenów do salonu?",
    ],
)
def test_normal_store_messages_are_not_refused(text):
    assert not is_out_of_scope(text)


@pytest.mark.parametrize("text", ["Kto wygrał wybory?", "Jaka jest najlepsza broń?", "tell me about politics"])
def test_clearly_forbidden_topics_are_refused(text):
    assert is_out_of_scope(text)


@pytest.mark.parametrize(
    ("text", "max_price"),
    [
        ("lampa do sypialni do 50 PLN", 50),
        ("lampa poniżej 30 zł", 30),
        ("budżet 80", 80),
        ("lamp under 40", 40),
        ("mam 70 zł", 70),
        ("gwint E27", None),
        ("lampa 10W", None),
    ],
)
def test_budget_is_parsed(text, max_price):
    assert parse_price_request(text).max_price == max_price


def test_budget_filters_results_even_outside_the_top_matches():
    _, _, products = build_service().process_message("lampa podłogowa do 100 zł")

    assert products
    assert all(product.price <= 100 for product in products)
    assert "floor-cheap" in [product.id for product in products]


def test_impossible_budget_shows_closest_products_and_tells_the_model():
    provider = RecordingProvider()
    build_service(provider).process_message("lampa podłogowa do 10 zł")

    consultation = provider.consultations[0]
    assert consultation.products[0].id == "floor-cheap"
    assert any("10 PLN" in note for note in consultation.notes)


def test_cheapest_and_most_expensive_use_the_whole_catalog():
    service = build_service()

    assert service.process_message("najtańsza lampa")[2][0].id == "bedside-cheap"
    assert service.process_message("najdroższa lampa")[2][0].id == "floor-expensive"


def test_cheapest_keeps_the_requested_type():
    _, _, products = build_service().process_message("najtańsza lampa podłogowa")

    assert products[0].id == "floor-cheap"


def test_cheaper_follow_up_returns_lower_prices():
    service = build_service()
    session, _, shown = service.process_message("pokaż lampy nocne")
    boundary = min(product.price for product in shown)

    _, reply, products = service.process_message("a jakieś tańsze?", session_id=session.id)

    assert reply.metadata["intent"] == "follow_up"
    assert all(product.price < boundary for product in products)


def test_follow_up_question_keeps_previous_products_and_sends_history():
    provider = RecordingProvider()
    service = build_service(provider)
    session, _, shown = service.process_message("pokaż lampy podłogowe")

    _, reply, _ = service.process_message("a która będzie najlepsza do czytania?", session_id=session.id)

    consultation = provider.consultations[-1]
    assert reply.metadata["intent"] == "follow_up"
    assert {product.id for product in consultation.products} == {product.id for product in shown}
    assert [message["role"] for message in consultation.history] == ["user", "assistant"]
    assert consultation.history[0]["content"] == "pokaż lampy podłogowe"


def test_ordinal_follow_up_selects_one_product():
    service = build_service()
    session, _, shown = service.process_message("pokaż lampy podłogowe")

    _, _, products = service.process_message("opowiedz o drugiej", session_id=session.id)

    assert [product.id for product in products] == [shown[1].id]


def test_relative_clause_about_a_lamp_is_a_new_search():
    assert not refers_to_previous_products("lampa, która może świecić na zielono")
    assert refers_to_previous_products("a która jest najtańsza?")


def test_model_decides_which_product_cards_are_shown():
    service = build_service(RecordingProvider(product_ids=["floor-mid"]))

    _, _, products = service.process_message("pokaż lampy podłogowe")

    assert [product.id for product in products] == ["floor-mid"]


def test_no_cards_when_model_talks_about_no_products():
    service = build_service(RecordingProvider(product_ids=[]))

    assert service.process_message("pokaż lampy podłogowe")[2] == []


def test_reply_without_tag_shows_only_products_it_names():
    class NoTagProvider:
        def __init__(self, text):
            self.text = text

        def generate_consultation(self, consultation):
            return AiResponse(text=self.text, provider="grok")

    refusal = build_service(NoTagProvider("Nie mogę ujawnić instrukcji."))
    assert refusal.process_message("pokaż lampy podłogowe")[2] == []

    naming = build_service(NoTagProvider("Polecam Lampa podłogowa Tripod."))
    assert [product.id for product in naming.process_message("pokaż lampy podłogowe")[2]] == ["floor-mid"]


def test_which_question_compares_all_candidates_not_only_the_shown_card():
    provider = RecordingProvider(product_ids=["floor-mid"])
    service = build_service(provider)
    session, _, _ = service.process_message("pokaż lampy podłogowe")

    service.process_message("a która jest najtańsza?", session_id=session.id)

    assert len(provider.consultations[-1].products) > 1


def test_unsure_customer_who_names_a_room_gets_a_search():
    _, reply, products = build_service().process_message("nie wiem, mam salon")

    assert reply.metadata["intent"] != "small_talk"
    assert products


def test_cheaper_works_in_any_wording_after_a_shown_list():
    service = build_service()
    session, _, shown = service.process_message("pokaż lampy nocne")
    boundary = min(product.price for product in shown)

    _, reply, products = service.process_message("chodziło mi o coś tańszego", session_id=session.id)

    assert reply.metadata["intent"] == "follow_up"
    assert all(product.price < boundary for product in products)


def test_unclear_message_mid_conversation_keeps_products_for_the_model():
    provider = RecordingProvider()
    service = build_service(provider)
    session, _, shown = service.process_message("pokaż lampy nocne")

    service.process_message("chodziło mi o to samo co wcześniej", session_id=session.id)

    consultation = provider.consultations[-1]
    assert consultation.products
    assert any("ciąg rozmowy" in note for note in consultation.notes)


def test_unrelated_question_gets_no_products_and_a_decline_note():
    provider = RecordingProvider()
    build_service(provider).process_message("jaka jest stolica Francji?")

    consultation = provider.consultations[0]
    assert consultation.products == []
    assert consultation.kind == "off_topic"
    assert any("Nie odpowiadaj" in note for note in consultation.notes)


def test_conversation_stage_is_passed_to_the_model():
    from app.services.ai_provider import build_user_prompt

    assert "pierwsza wiadomość" in build_user_prompt(Consultation(user_text="cześć", language="pl", is_first_message=True))
    assert "nie witaj" in build_user_prompt(Consultation(user_text="ok", language="pl", is_first_message=False))


def test_product_tag_and_markdown_are_removed_from_the_reply():
    text, ids = split_product_tag("Polecam **Lampę Arc** i *Tripod*.\n[[PRODUCTS: floor-cheap, floor-mid]]")

    assert text == "Polecam Lampę Arc i Tripod."
    assert ids == ["floor-cheap", "floor-mid"]
    assert split_product_tag("Dzień dobry\n[[PRODUCTS: none]]") == ("Dzień dobry", [])
    assert split_product_tag("Bez znacznika")[1] is None
    assert clean_reply_text("* jeden\n* dwa") == "- jeden\n- dwa"


@pytest.mark.parametrize(
    ("text", "command_type"),
    [
        ("dodaj pierwszą do koszyka", "add_to_cart"),
        ("a tę drugą do biblioteki", "add_to_library"),
        ("add it to my cart", "add_to_cart"),
        ("usuń z koszyka", "remove_from_cart"),
        ("wyrzuć to z koszyka", "remove_from_cart"),
        ("remove it from my library", "remove_from_library"),
        ("pokaż koszyk", "open_cart"),
        ("co mam w koszyku?", "open_cart"),
        ("open my library", "open_library"),
        ("nie dodawaj do koszyka", None),
        ("pokaż lampy", None),
    ],
)
def test_commands_are_recognised(text, command_type):
    command = detect_command(text)
    assert (command.type if command else None) == command_type


def test_remove_never_adds():
    service = build_service()
    session, _, _ = service.process_message("pokaż lampy podłogowe")
    service.process_message("dodaj drugą do koszyka", session_id=session.id)

    _, reply, products = service.process_message("usuń z koszyka", session_id=session.id)

    assert reply.metadata["action"]["type"] == "remove_from_cart"
    assert len(products) == 1
    assert "Usu" in reply.text or "usu" in reply.text or "znika" in reply.text or "wyjm" in reply.text


def test_clear_cart_does_not_name_products():
    service = build_service()

    _, reply, _ = service.process_message("usuń wszystko z koszyka")

    assert reply.metadata["action"]["all"] is True


def test_ordinals_and_all_keep_referring_to_the_shown_list_after_a_command():
    service = build_service()
    session, _, shown = service.process_message("pokaż lampy podłogowe")

    service.process_message("dodaj pierwszą do koszyka", session_id=session.id)
    _, second_reply, second = service.process_message("a tę drugą do biblioteki", session_id=session.id)
    _, all_reply, everything = service.process_message("dodaj wszystkie do koszyka", session_id=session.id)

    assert second_reply.metadata["action"]["type"] == "add_to_library"
    assert second[0].id == shown[1].id
    assert {product.id for product in everything} == {product.id for product in shown}
    assert all_reply.metadata["action"]["type"] == "add_to_cart"


def test_quantity_reaches_the_action():
    service = build_service()
    session, _, _ = service.process_message("pokaż lampy podłogowe")

    _, reply, _ = service.process_message("dodaj 3 sztuki pierwszej do koszyka", session_id=session.id)

    assert reply.metadata["action"]["items"][0]["quantity"] == 3


def test_add_without_any_product_asks_which_one():
    _, reply, products = build_service().process_message("dodaj do koszyka")

    assert reply.metadata["action"] is None
    assert products == []


def test_named_product_can_be_added_directly():
    _, reply, products = build_service().process_message("dodaj lampę biurkową do koszyka")

    assert products[0].id == "desk-lamp"
    assert reply.metadata["action"]["type"] == "add_to_cart"


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        ("Ile kosztuje wysyłka?", "delivery"),
        ("Jak długo trwa dostawa?", "delivery"),
        ("Mogę zapłacić blikiem?", "payment"),
        ("Czy mogę oddać towar?", "returns"),
        ("jak mogę zwrócić lampę?", "returns"),
        ("Jaka jest gwarancja?", "warranty"),
        ("How can I return a lamp?", "returns"),
        ("Lampa ze sterowaniem telefonem", None),
    ],
)
def test_store_questions_are_recognised(text, topic):
    assert detect_store_topic(text) == topic


def test_store_question_gets_the_rule_and_no_product_cards():
    _, reply, products = build_service().process_message("Ile kosztuje wysyłka?")

    assert products == []
    assert "15 PLN" in reply.text


def test_small_talk_gets_no_product_cards():
    service = build_service()

    for text in ("dzięki", "ok", "nie wiem co wybrać", "kim jesteś?"):
        _, reply, products = service.process_message(text)
        assert products == [], text
        assert reply.metadata["intent"] == "small_talk", text


@pytest.mark.parametrize(
    ("text", "kind"),
    [("dzięki", "thanks"), ("do widzenia", "goodbye"), ("kim jesteś", "identity"), ("nie wiem", "unsure"), ("ok", "agreement"), ("szukam lampy podłogowej do dużego salonu", None)],
)
def test_small_talk_kinds(text, kind):
    assert detect_small_talk(text) == kind


def test_greeting_followed_by_a_request_is_not_just_a_greeting():
    _, reply, products = build_service().process_message("cześć, szukam lampy podłogowej")

    assert reply.metadata["intent"] != "greeting"
    assert products


def test_lighting_question_gets_advice_without_cards():
    _, reply, products = build_service().process_message("Ile lumenów do salonu?")

    assert products == []
    assert "lumen" in reply.text


def test_english_conversation_stays_in_english_with_english_names():
    service = build_service()

    _, reply, products = service.process_message("I need a tall floor lamp for the living room", language="en")

    assert products
    assert any(product.name == "Arc Floor Lamp" for product in products)
    assert "Lampa podłogowa Arc" not in reply.text


@pytest.mark.parametrize(
    ("text", "fallback", "expected"),
    [
        ("I need a warm floor lamp for reading", "pl", "en"),
        ("show me a desk lamp", "pl", "en"),
        ("szukam lampy do kuchni", "en", "pl"),
        ("zielone", "en", "pl"),
        ("Lampa", "en", "pl"),
        ("ok", "en", "en"),
        ("ok", "pl", "pl"),
    ],
)
def test_response_language(text, fallback, expected):
    assert detect_response_language(text, fallback) == expected


def test_model_failure_falls_back_to_a_local_reply(monkeypatch):
    import httpx

    from app.core.config import Settings
    from app.services.ai_provider import GrokAiProvider

    def fail(*args, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", fail)
    provider = GrokAiProvider(Settings(grok_api_key="test-key"))

    response = provider.generate_consultation(Consultation(user_text="cześć", language="pl", kind="greeting"))

    assert response.provider == "none"
    assert response.text
