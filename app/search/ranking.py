"""Scores catalog products against a chat query.

The score is a sum of signals. Every value comes from RankingWeights, and docs/ranking.md explains the scale
and how app/search/evaluate.py checks it against a labelled set of queries.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from app.domain.models import Product
from app.search.vocabulary import (
    BATHROOM_MISMATCH_MARKERS,
    BATHROOM_PRIMARY_MARKERS,
    BATHROOM_PRODUCT_MARKERS,
    BATHROOM_QUERY_TERMS,
    BATHROOM_STRONG_PRODUCT_MARKERS,
    BATHROOM_WARM_DECORATIVE_MARKERS,
    BATHROOM_WHITE_PRIMARY_MARKERS,
    BED_READING_PRODUCT_MARKERS,
    COLOR_CAPABILITY_QUERY_MARKERS,
    COLOR_CHANGING_PRODUCT_MARKERS,
    COLOR_QUERY_VARIANTS,
    DESK_ONLY_PRODUCT_MARKERS,
    NON_BATHROOM_TASK_MARKERS,
    OVER_TABLE_PRODUCT_MARKERS,
    OVER_TABLE_QUERY_TERMS,
    PRIMARY_PROFILE,
    PRODUCT_KEYWORD_PROFILES,
    QUERY_PREFIX_SYNONYMS,
    QUERY_SYNONYMS,
    SEMANTIC_PRODUCT_PROFILES,
    SMART_PRODUCT_MARKERS,
    SMART_QUERY_TERMS,
    SOFT_DECORATIVE_PRODUCT_MARKERS,
    STOP_WORDS,
    TABLE_LAMP_PRODUCT_MARKERS,
    WARM_LIGHT_QUERY_TERMS,
    WHITE_LIGHT_QUERY_TERMS,
    WHITE_PRODUCT_MARKERS,
)

# The scale of signal strength: each level is worth two matches of the level below.
HINT = 10
WEAK = 20
MODERATE = 40
STRONG = 80
VERY_STRONG = 160
DECISIVE = 320


@dataclass(frozen=True, slots=True)
class RankingWeights:
    """Each value is one level of the scale above, so comparing two signals needs no calibration."""

    # The whole query is found in one field. The most specific evidence there is.
    phrase_equals_id: int = DECISIVE
    phrase_in_tags: int = VERY_STRONG
    phrase_in_id: int = VERY_STRONG
    phrase_in_name: int = VERY_STRONG
    phrase_in_other_text: int = STRONG

    # A word the user actually typed: reliable, so one level above the same match of a synonym.
    typed_word_in_name: int = STRONG
    typed_word_in_tags: int = STRONG
    typed_word_in_description: int = MODERATE

    # Any query word including synonyms. A synonym may be only loosely related, so these stay low.
    any_word_in_identity: int = MODERATE
    any_word_in_category: int = WEAK
    any_word_in_keywords: int = WEAK
    any_word_in_description: int = HINT

    # Colour: a plain "green lamp" means a green product, "can glow green" means an RGB one.
    color_capability_and_tag: int = DECISIVE
    color_capability_tag_only: int = MODERATE
    color_physical: int = VERY_STRONG
    color_rgb_alternative: int = STRONG
    color_rgb_with_tag: int = STRONG

    # Semantic profile: the query names a purpose and the product text confirms it.
    profile_primary: int = STRONG
    profile_secondary: int = MODERATE
    profile_per_marker: int = HINT
    profile_max_markers: int = 5

    # Context rules for requests where a word match alone picks the wrong lamp type.
    light_preference: int = WEAK
    context_fit: int = STRONG
    context_strong_fit: int = VERY_STRONG
    context_mismatch: int = -STRONG
    context_type_mismatch: int = -VERY_STRONG


DEFAULT_WEIGHTS = RankingWeights()


@dataclass(frozen=True, slots=True)
class QueryFeatures:
    comparable: str
    terms: frozenset[str]
    typed_terms: frozenset[str]
    colors: frozenset[str]
    light_preference: str | None
    wants_color_capability: bool
    wants_smart_product: bool
    wants_bathroom: bool
    wants_over_table: bool
    wants_bed_reading: bool


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", " ", value.lower()).strip().split())


@lru_cache(maxsize=8192)
def comparable_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", normalize_text(value))
    without_marks = "".join(character for character in normalized if not unicodedata.combining(character))
    return without_marks.replace("ł", "l")


def literal_query_terms(query: str) -> set[str]:
    return {
        term
        for term in comparable_text(query).split()
        if len(term) > 2 and term not in STOP_WORDS
    }


def query_terms(query: str) -> set[str]:
    terms = literal_query_terms(query)

    expanded = set(terms)
    for term in terms:
        expanded.update(QUERY_SYNONYMS.get(term, set()))
        for prefix, synonyms in QUERY_PREFIX_SYNONYMS.items():
            if term.startswith(prefix):
                expanded.update(synonyms)

    return expanded


def requested_colors(query: str) -> set[str]:
    literal_terms = literal_query_terms(query)
    return {
        color
        for color, variants in COLOR_QUERY_VARIANTS.items()
        if literal_terms & variants
    }


def contains_any_marker(text: str, markers: set[str]) -> bool:
    return any(marker in text for marker in markers)


def light_preference_for_query(query: str) -> str | None:
    terms = literal_query_terms(query)
    wants_white = bool(terms & WHITE_LIGHT_QUERY_TERMS)
    wants_warm = bool(terms & WARM_LIGHT_QUERY_TERMS)

    if wants_white and not wants_warm:
        return "white"
    if wants_warm and not wants_white:
        return "warm"
    return None


def derive_product_keywords(*values: str) -> list[str]:
    raw_text = " ".join(value for value in values if value)
    haystack = comparable_text(raw_text)
    keywords = {
        term
        for term in normalize_text(raw_text).split()
        if len(term) > 2 and comparable_text(term) not in STOP_WORDS
    }

    for product_markers, extra_keywords in PRODUCT_KEYWORD_PROFILES:
        if contains_any_marker(haystack, product_markers):
            keywords.update(extra_keywords)

    return sorted(keywords)


def product_text(product: Product) -> str:
    return " ".join(
        [
            comparable_text(product.id),
            comparable_text(product.name),
            comparable_text(product.category),
            comparable_text(product.description),
            comparable_text(" ".join(product.tags)),
            comparable_text(" ".join(product.keywords)),
            comparable_text(" ".join(f"{key} {value}" for key, value in product.attributes.items())),
        ]
    )


def is_product_allowed_for_light_preference(product: Product, preference: str | None) -> bool:
    if preference not in {"white", "warm"}:
        return True

    haystack = product_text(product)
    has_white_profile = contains_any_marker(haystack, WHITE_PRODUCT_MARKERS)
    has_bathroom_profile = contains_any_marker(haystack, BATHROOM_PRODUCT_MARKERS)
    has_soft_decorative_profile = contains_any_marker(haystack, SOFT_DECORATIVE_PRODUCT_MARKERS)

    if preference == "white":
        return has_bathroom_profile or not has_soft_decorative_profile or has_white_profile

    return has_soft_decorative_profile or not has_white_profile


def is_lamp_query(query: str) -> bool:
    return bool(query_terms(query) & {"lamp", "lampa", "led", "light", "lighting", "swiatlo"})


@lru_cache(maxsize=1024)
def query_features(query: str) -> QueryFeatures:
    comparable = comparable_text(query)
    terms = query_terms(query)
    return QueryFeatures(
        comparable=comparable,
        terms=frozenset(terms),
        typed_terms=frozenset(literal_query_terms(query)),
        colors=frozenset(requested_colors(query)),
        light_preference=light_preference_for_query(query),
        wants_color_capability=contains_any_marker(comparable, COLOR_CAPABILITY_QUERY_MARKERS),
        wants_smart_product=bool(literal_query_terms(query) & SMART_QUERY_TERMS),
        wants_bathroom=bool(terms & BATHROOM_QUERY_TERMS),
        wants_over_table="nad" in terms
        or "over" in terms
        or (bool(terms & {"wyspa", "island", "stolem"}) and bool(terms & OVER_TABLE_QUERY_TERMS)),
        wants_bed_reading=bool(terms & {"bed", "bedside", "lozko", "lozka", "lozku"})
        and bool(terms & {"book", "czytanie", "czytania", "focused", "ksiazka", "ksiazki", "reading"}),
    )


def is_excluded(features: QueryFeatures, product: Product, haystack: str, explicit_text: str) -> bool:
    """Hard filters: a product that cannot satisfy the request must not appear whatever its score."""
    if features.wants_bathroom and not contains_any_marker(haystack, BATHROOM_STRONG_PRODUCT_MARKERS):
        return True
    if features.wants_smart_product and not contains_any_marker(explicit_text, SMART_PRODUCT_MARKERS):
        return True
    return not is_product_allowed_for_light_preference(product, features.light_preference)


def phrase_score(comparable: str, product_id: str, name: str, tags: str, haystack: str, weights: RankingWeights) -> int:
    score = 0
    if comparable == product_id:
        score += weights.phrase_equals_id
    elif comparable in product_id:
        score += weights.phrase_in_id
    if comparable in name:
        score += weights.phrase_in_name
    if comparable in tags:
        score += weights.phrase_in_tags
    elif comparable in haystack:
        score += weights.phrase_in_other_text
    return score


def term_score(
    features: QueryFeatures,
    product_id: str,
    name: str,
    category: str,
    description: str,
    tags: str,
    keywords: str,
    attributes: str,
    weights: RankingWeights,
) -> int:
    score = 0
    for term in features.terms:
        if term in product_id:
            score += weights.any_word_in_identity
        if term in name:
            score += weights.any_word_in_identity
        if term in tags:
            score += weights.any_word_in_identity
        if term in category:
            score += weights.any_word_in_category
        if term in keywords:
            score += weights.any_word_in_keywords
        if term in description or term in attributes:
            score += weights.any_word_in_description

    for term in features.typed_terms:
        if term in product_id or term in name:
            score += weights.typed_word_in_name
        if term in tags:
            score += weights.typed_word_in_tags
        elif term in description or term in attributes:
            score += weights.typed_word_in_description
    return score


def color_score(features: QueryFeatures, tags: str, haystack: str, weights: RankingWeights) -> int:
    if not features.colors:
        return 0

    supports_color_change = contains_any_marker(haystack, COLOR_CHANGING_PRODUCT_MARKERS)
    color_in_tags = any(contains_any_marker(tags, COLOR_QUERY_VARIANTS[color]) for color in features.colors)

    if not color_in_tags:
        return weights.color_rgb_alternative if supports_color_change else 0
    if features.wants_color_capability:
        return weights.color_capability_and_tag if supports_color_change else weights.color_capability_tag_only
    return weights.color_rgb_with_tag if supports_color_change else weights.color_physical


def semantic_profile_score(terms: frozenset[str] | set[str], haystack: str, weights: RankingWeights) -> int:
    score = 0
    for query_markers, product_markers, strength in SEMANTIC_PRODUCT_PROFILES:
        if not terms & query_markers:
            continue

        marker_matches = sum(1 for marker in product_markers if marker in haystack)
        if marker_matches:
            base = weights.profile_primary if strength == PRIMARY_PROFILE else weights.profile_secondary
            score += base + min(marker_matches, weights.profile_max_markers) * weights.profile_per_marker

    return score


def context_score(features: QueryFeatures, haystack: str, weights: RankingWeights) -> int:
    score = 0
    wants_white = features.light_preference == "white"

    if wants_white and contains_any_marker(haystack, WHITE_PRODUCT_MARKERS):
        score += weights.light_preference
    if features.light_preference == "warm" and contains_any_marker(haystack, SOFT_DECORATIVE_PRODUCT_MARKERS):
        score += weights.light_preference

    if features.wants_bathroom:
        if contains_any_marker(haystack, BATHROOM_PRODUCT_MARKERS):
            score += weights.context_fit
        else:
            score += weights.context_mismatch
        if contains_any_marker(haystack, BATHROOM_PRIMARY_MARKERS):
            score += weights.context_fit
        if wants_white and contains_any_marker(haystack, BATHROOM_WHITE_PRIMARY_MARKERS):
            score += weights.context_strong_fit
        if wants_white and contains_any_marker(haystack, BATHROOM_WARM_DECORATIVE_MARKERS):
            score += weights.context_mismatch
        if contains_any_marker(haystack, BATHROOM_MISMATCH_MARKERS):
            score += weights.context_mismatch
        if contains_any_marker(haystack, NON_BATHROOM_TASK_MARKERS):
            score += weights.context_mismatch

    if features.wants_over_table:
        fits_over_table = contains_any_marker(haystack, OVER_TABLE_PRODUCT_MARKERS)
        if fits_over_table:
            score += weights.context_strong_fit
        elif contains_any_marker(haystack, TABLE_LAMP_PRODUCT_MARKERS):
            score += weights.context_type_mismatch

    if features.wants_bed_reading:
        fits_bed = contains_any_marker(haystack, BED_READING_PRODUCT_MARKERS)
        if fits_bed:
            score += weights.context_strong_fit
        elif contains_any_marker(haystack, DESK_ONLY_PRODUCT_MARKERS):
            score += weights.context_type_mismatch

    return score


def score_product(product: Product, query: str, weights: RankingWeights = DEFAULT_WEIGHTS) -> int:
    features = query_features(query)
    product_id = comparable_text(product.id)
    name = comparable_text(product.name)
    category = comparable_text(product.category)
    description = comparable_text(product.description)
    tags = comparable_text(" ".join(product.tags))
    keywords = comparable_text(" ".join(product.keywords))
    attributes = comparable_text(" ".join(f"{key} {value}" for key, value in product.attributes.items()))
    haystack = " ".join([product_id, name, category, description, tags, keywords, attributes])
    explicit_text = " ".join([product_id, name, category, description, tags])

    if is_excluded(features, product, haystack, explicit_text):
        return 0

    return (
        phrase_score(features.comparable, product_id, name, tags, haystack, weights)
        + term_score(features, product_id, name, category, description, tags, keywords, attributes, weights)
        + color_score(features, tags, haystack, weights)
        + semantic_profile_score(features.terms, haystack, weights)
        + context_score(features, haystack, weights)
    )


def rank_products(
    products: list[Product],
    query: str,
    limit: int = 5,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list[Product]:
    normalized = normalize_text(query)
    if not normalized:
        return products[:limit]

    scored = [(score_product(product, normalized, weights), product) for product in products]
    ranked = sorted((item for item in scored if item[0] > 0), key=lambda item: item[0], reverse=True)
    if ranked:
        return [product for _, product in ranked[:limit]]

    if is_lamp_query(normalized):
        preference = light_preference_for_query(normalized)
        return [
            product
            for product in products
            if is_product_allowed_for_light_preference(product, preference)
        ][:limit]

    return []
