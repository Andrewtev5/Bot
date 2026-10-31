from uuid import uuid4

from app.core.database import SqlServerConnectionPool
from app.data.sample_products import SAMPLE_PRODUCTS
from app.domain.models import ChatMessage, MessageRole
from app.repositories.product_repository import InMemoryProductRepository
from app.repositories.session_repository import InMemorySessionRepository, SqlServerSessionRepository
from app.services.ai_provider import NoAiProvider
from app.services.chat_service import ChatService


def build_service(repository) -> ChatService:
    return ChatService(
        session_repository=repository,
        product_repository=InMemoryProductRepository(SAMPLE_PRODUCTS),
        ai_provider=NoAiProvider(),
    )


def test_in_memory_repository_keeps_messages_on_the_session_object():
    repository = InMemorySessionRepository()
    session = repository.create_session(language="pl")

    repository.add_message(session, ChatMessage(role=MessageRole.USER, text="hej"))
    repository.update_language(session, "en")

    assert repository.get_session(session.id).messages[0].text == "hej"
    assert repository.get_session(session.id).language == "en"


def test_conversation_survives_bot_restart(sql_pool):
    first_run = build_service(SqlServerSessionRepository(sql_pool))
    session, reply, _ = first_run.process_message("doradź lampę do sypialni")

    restarted_pool = SqlServerConnectionPool(sql_pool._resolved_connection_string or sql_pool._connection_string)
    second_run = build_service(SqlServerSessionRepository(restarted_pool))
    restored = second_run.get_session(session.id)
    restarted_pool.close_all()

    assert [message.role for message in restored.messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert restored.messages[0].text == "doradź lampę do sypialni"
    assert restored.messages[1].text == reply.text
    assert restored.messages[1].metadata["matched_product_ids"] == reply.metadata["matched_product_ids"]


def test_restored_session_keeps_context_for_the_next_message(sql_pool):
    first_run = build_service(SqlServerSessionRepository(sql_pool))
    session, _, _ = first_run.process_message("pokaż lampę smart")

    second_run = build_service(SqlServerSessionRepository(sql_pool))
    restored, reply, products = second_run.process_message("zielone", session_id=session.id)

    assert len(restored.messages) == 4
    assert reply.metadata["intent"] == "contextual_recommendation"
    assert products[0].id == "smart-wifi-lamp"


def test_language_change_is_saved(sql_pool):
    repository = SqlServerSessionRepository(sql_pool)
    session = repository.create_session(language="pl")

    repository.update_language(session, "en")

    assert repository.get_session(session.id).language == "en"


def test_unknown_session_returns_none(sql_pool):
    assert SqlServerSessionRepository(sql_pool).get_session(uuid4().hex) is None


def test_unknown_or_malformed_user_becomes_anonymous(sql_pool):
    repository = SqlServerSessionRepository(sql_pool)

    assert repository.create_session("pl", user_id="not-a-uuid").user_id is None
    assert repository.create_session("pl", user_id=str(uuid4())).user_id is None
    assert repository.create_session("pl").user_id is None


def test_known_user_is_linked_to_session(sql_pool):
    user_id = str(uuid4())
    with sql_pool.cursor() as cursor:
        cursor.execute(
            "INSERT INTO dbo.users (id, name, email, password_hash, salt) VALUES (?, 'Test', ?, 'x', 'x');",
            user_id,
            f"{user_id}@example.com",
        )

    repository = SqlServerSessionRepository(sql_pool)
    session = repository.create_session("pl", user_id=user_id)

    assert session.user_id.lower() == user_id
    assert repository.get_session(session.id).user_id.lower() == user_id
