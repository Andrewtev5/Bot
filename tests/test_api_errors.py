from fastapi.testclient import TestClient

from app.api import routes
from app.main import app


class BrokenRepository:
    def list_products(self):
        raise RuntimeError("SERVER=secret-host;PWD=secret")


def test_unexpected_error_does_not_reveal_details(monkeypatch):
    monkeypatch.setattr(routes.products, "get_product_repository", BrokenRepository)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/products")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    assert "secret" not in response.text


class MissingSessionService:
    def get_session(self, session_id):
        from app.services.chat_service import SessionNotFoundError

        raise SessionNotFoundError(session_id)


def test_missing_session_is_a_404_without_internal_text(monkeypatch):
    monkeypatch.setattr(routes.chat, "get_chat_service", MissingSessionService)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/chat/sessions/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found."}
