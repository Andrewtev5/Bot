from app.domain.models import ChatMessage, ChatSession, MessageRole
from app.data.sample_products import SAMPLE_PRODUCTS
from app.repositories.product_repository import InMemoryProductRepository
from app.repositories.session_repository import InMemorySessionRepository
from app.services.ai_provider import NoAiProvider
from app.services.chat_service import (
    ChatService,
    build_contextual_search_text,
    detect_intent,
    detect_response_language,
    is_out_of_scope,
)


def build_service() -> ChatService:
    return ChatService(
        session_repository=InMemorySessionRepository(),
        product_repository=InMemoryProductRepository(SAMPLE_PRODUCTS),
        ai_provider=NoAiProvider(),
        default_language="pl",
        max_products_for_ai=5,
    )


def test_service_creates_session_and_reply():
    service = build_service()

    session, reply, matched_products = service.process_message("doradź lampę do sypialni")

    assert session.id
    assert reply.role.value == "assistant"
    assert reply.metadata["provider"] == "none"
    assert matched_products
    assert len(session.messages) == 2


def test_service_finds_price_by_product_query():
    service = build_service()

    session, reply, matched_products = service.process_message("cena smart wifi lamp")

    assert session.id
    assert "Smart WiFi Lamp" in reply.text
    assert "40 PLN" in reply.text
    assert matched_products[0].id == "smart-wifi-lamp"


def test_new_smart_request_does_not_reuse_previous_night_light_context():
    service = build_service()

    session, _, first_products = service.process_message("lampka nocna dla dziecka")
    assert first_products[0].id == "kids-cloud-night-lamp"

    _, _, smart_products = service.process_message("smart lampa", session_id=session.id)

    assert smart_products
    assert smart_products[0].id == "smart-wifi-lamp"
    assert all(product.id != "kids-cloud-night-lamp" for product in smart_products)


def test_short_follow_up_keeps_previous_room_context():
    session = ChatSession(
        id="context-check",
        language="pl",
        messages=[
            ChatMessage(role=MessageRole.USER, text="potrzebuję lampy do łazienki"),
            ChatMessage(role=MessageRole.ASSISTANT, text="Jaki kolor światła?"),
            ChatMessage(role=MessageRole.USER, text="biała"),
        ],
    )

    search_text = build_contextual_search_text("biała", session)

    assert "lampy do łazienki" in search_text
    assert "neutralne" in search_text


def test_short_color_follow_up_is_treated_as_lighting_request():
    service = build_service()

    session, _, _ = service.process_message("pokaż lampę smart")
    _, reply, matched_products = service.process_message("zielone", session_id=session.id)

    assert reply.metadata["intent"] == "contextual_recommendation"
    assert matched_products
    assert matched_products[0].id == "smart-wifi-lamp"


def test_short_polish_color_switches_response_language_to_polish():
    assert detect_response_language("zielone", "en") == "pl"


def test_explicit_now_phrase_starts_a_new_short_product_search():
    session = ChatSession(
        id="new-color-search",
        language="pl",
        messages=[
            ChatMessage(role=MessageRole.USER, text="lampka nocna dla dziecka"),
            ChatMessage(role=MessageRole.ASSISTANT, text="Mam kilka nocnych lampek."),
            ChatMessage(role=MessageRole.USER, text="teraz potrzebuję zielone"),
        ],
    )

    search_text = build_contextual_search_text("teraz potrzebuję zielone", session)

    assert "lampka nocna dla dziecka" not in search_text
    assert "zielone" in search_text


def test_misspelled_compound_waterproof_request_reaches_product_search():
    service = build_service()

    _, reply, matched_products = service.process_message("potrzebuję wododpornąmpę")

    assert reply.metadata["intent"] != "out_of_scope"
    assert matched_products
    assert matched_products[0].id == "portable-lantern-lamp"


def test_short_colors_styles_and_materials_stay_in_store_scope():
    for text in ("czerwone", "niebieskie", "fioletowe", "boho", "rattanowe", "czarne"):
        assert not is_out_of_scope(text)
        assert detect_intent(text) == "contextual_recommendation"


def test_inflected_short_color_is_understood_through_its_lemma():
    service = build_service()

    session, _, _ = service.process_message("pokaż lampę smart")
    _, reply, matched_products = service.process_message("zielonych", session_id=session.id)

    assert reply.metadata["intent"] == "contextual_recommendation"
    assert matched_products
    assert matched_products[0].id == "smart-wifi-lamp"
