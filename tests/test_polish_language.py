from app.services.chat_service import normalize_for_matching
from app.services.polish_language import is_morfeusz_available, polish_lemmas


def test_morfeusz_is_available_in_bot_environment():
    assert is_morfeusz_available()


def test_polish_lemmas_cover_inflected_product_request():
    lemmas = set(polish_lemmas("Potrzebuję zielonych lamp na taras."))

    assert {"potrzebować", "zielony", "lampa", "taras"}.issubset(lemmas)


def test_matching_normalization_keeps_original_words_and_adds_lemmas():
    normalized = normalize_for_matching("Szukam wodoodpornych lamp ogrodowych")

    assert "wodoodpornych" in normalized
    assert "wodoodporny" in normalized
    assert "lamp" in normalized
    assert "lampa" in normalized
    assert "ogrodowy" in normalized
