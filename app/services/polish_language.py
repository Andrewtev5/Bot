from __future__ import annotations

from functools import lru_cache
from threading import RLock

try:
    import morfeusz2
except ImportError:  # Keep startup functional until optional dependencies are installed.
    morfeusz2 = None


_analyzer_lock = RLock()
_analyzer = morfeusz2.Morfeusz() if morfeusz2 is not None else None


def is_morfeusz_available() -> bool:
    return _analyzer is not None


@lru_cache(maxsize=2048)
def polish_lemmas(text: str) -> tuple[str, ...]:
    """Return stable lemma candidates for Polish search without blocking bot startup."""
    clean_text = " ".join(text.strip().split())
    if not clean_text or _analyzer is None:
        return ()

    try:
        with _analyzer_lock:
            analyses = _analyzer.analyse(clean_text)
    except Exception:
        return ()

    lemmas: list[str] = []
    seen: set[str] = set()
    candidates_per_segment: dict[tuple[int, int], int] = {}

    for start, end, interpretation in analyses:
        if len(interpretation) < 3 or str(interpretation[2]).startswith("interp"):
            continue

        segment = (int(start), int(end))
        if candidates_per_segment.get(segment, 0) >= 4:
            continue

        lemma = str(interpretation[1]).split(":", 1)[0].casefold().strip()
        if not lemma or not any(character.isalpha() for character in lemma) or lemma in seen:
            continue

        seen.add(lemma)
        lemmas.append(lemma)
        candidates_per_segment[segment] = candidates_per_segment.get(segment, 0) + 1

    return tuple(lemmas)


def enrich_with_polish_lemmas(text: str) -> str:
    lemmas = polish_lemmas(text)
    if not lemmas:
        return text
    return f"{text} {' '.join(lemmas)}"
