from app.data.sample_products import SAMPLE_PRODUCTS
from app.repositories.product_repository import InMemoryProductRepository
from app.repositories.session_repository import InMemorySessionRepository
from app.services.ai_provider import NoAiProvider
from app.services.chat_service import ChatService


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
