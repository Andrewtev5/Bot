from app.data.sample_products import SAMPLE_PRODUCTS
from app.repositories.product_repository import InMemoryProductRepository
from app.repositories.session_repository import InMemorySessionRepository
from app.services.chat_service import ChatService, RuleBasedAssistantEngine


def build_service() -> ChatService:
    product_repository = InMemoryProductRepository(SAMPLE_PRODUCTS)
    session_repository = InMemorySessionRepository()
    engine = RuleBasedAssistantEngine(product_repository)
    return ChatService(session_repository=session_repository, assistant_engine=engine, default_language="ru")


def test_service_creates_session_and_reply():
    service = build_service()
    session, reply, matched_products = service.process_message("подбери лампу")

    assert session.id
    assert reply.role.value == "assistant"
    assert matched_products
    assert len(session.messages) == 2


def test_service_finds_price_by_product_query():
    service = build_service()
    session, reply, matched_products = service.process_message("цена smart wifi lamp")

    assert session.id
    assert "40 PLN" in reply.text
    assert matched_products[0].id == "smart-wifi-lamp"
