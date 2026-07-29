from __future__ import annotations

import re
import unicodedata
from typing import Any, Protocol

from app.core.config import Settings
from app.data.sample_products import SAMPLE_PRODUCTS
from app.domain.models import Product


class ProductRepository(Protocol):
    def list_products(self) -> list[Product]:
        ...

    def get_product(self, product_id: str) -> Product | None:
        ...

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        ...


class InMemoryProductRepository:
    def __init__(self, products: list[Product] | None = None) -> None:
        self._products = {product.id: product for product in (products or SAMPLE_PRODUCTS)}

    def list_products(self) -> list[Product]:
        return list(self._products.values())

    def get_product(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        normalized = normalize_text(query)
        if not normalized:
            return self.list_products()[:limit]

        scored: list[tuple[int, Product]] = []
        for product in self._products.values():
            score = score_product(product, normalized)
            if score > 0:
                scored.append((score, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [product for _, product in scored[:limit]]


class SqlServerProductRepository:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._columns: set[str] | None = None

    def list_products(self) -> list[Product]:
        rows = self._fetch_all(f"SELECT TOP (500) {self._select_clause()} FROM products ORDER BY name")
        return [map_sql_server_product(row) for row in rows]

    def get_product(self, product_id: str) -> Product | None:
        rows = self._fetch_all(f"SELECT TOP (1) {self._select_clause()} FROM products WHERE id = ?", (product_id,))
        return map_sql_server_product(rows[0]) if rows else None

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        normalized = normalize_text(query)
        if not normalized:
            return self.list_products()[:limit]

        products = self.list_products()
        scored: list[tuple[int, Product]] = []
        for product in products:
            score = score_product(product, normalized)
            if score > 0:
                scored.append((score, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            return [product for _, product in scored[:limit]]

        if is_lamp_query(normalized):
            light_preference = light_preference_for_query(normalized)
            if light_preference:
                products = [
                    product
                    for product in products
                    if is_product_allowed_for_light_preference(product, light_preference)
                ]
            return products[:limit]

        return []

    def _select_clause(self) -> str:
        columns = self._get_columns()
        if {"name_pl", "name_en", "tag_pl", "tag_en", "description_pl", "description_en", "image"}.issubset(columns):
            return """
                id,
                COALESCE(NULLIF(name_pl, ''), NULLIF(name_en, ''), id) AS name,
                price,
                COALESCE(NULLIF(currency, ''), 'PLN') AS currency,
                COALESCE(NULLIF(tag_pl, ''), NULLIF(tag_en, ''), 'lampa') AS category,
                COALESCE(NULLIF(description_pl, ''), NULLIF(description_en, ''), '') AS description,
                CAST('in_stock' AS NVARCHAR(50)) AS stock_status,
                image AS image_url
            """

        return """
            id,
            name,
            price,
            COALESCE(NULLIF(currency, ''), 'PLN') AS currency,
            COALESCE(NULLIF(category, ''), 'lampa') AS category,
            COALESCE(description, '') AS description,
            COALESCE(NULLIF(stock_status, ''), 'unknown') AS stock_status,
            image_url
        """

    def _search_columns(self) -> list[str]:
        columns = self._get_columns()
        if {"name_pl", "name_en", "tag_pl", "tag_en", "description_pl", "description_en"}.issubset(columns):
            return [
                "id",
                "name_pl",
                "name_en",
                "description_pl",
                "description_en",
                "tag_pl",
                "tag_en",
            ]

        return ["id", "name", "description", "category"]

    def _get_columns(self) -> set[str]:
        if self._columns is None:
            rows = self._fetch_all(
                """
                SELECT LOWER(COLUMN_NAME) AS column_name
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = 'dbo'
                  AND TABLE_NAME = 'products'
                """
            )
            self._columns = {str(row.column_name).lower() for row in rows}
        return self._columns

    def _fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        try:
            import pyodbc
        except ImportError as error:
            raise RuntimeError(
                "pyodbc is required for PRODUCT_DB_MODE=mssql. "
                "Install it and Microsoft ODBC Driver for SQL Server."
            ) from error

        if not self._connection_string:
            raise RuntimeError("SQL_SERVER_CONNECTION_STRING is empty.")

        connection = pyodbc.connect(self._connection_string)
        try:
            cursor = connection.cursor()
            cursor.execute(query, params)
            return list(cursor.fetchall())
        finally:
            connection.close()


def build_product_repository(settings: Settings) -> ProductRepository:
    if settings.product_db_mode == "mssql":
        return SqlServerProductRepository(settings.sql_server_connection_string)

    return InMemoryProductRepository()


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", " ", value.lower()).strip().split())


def comparable_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", normalize_text(value))
    without_marks = "".join(character for character in normalized if not unicodedata.combining(character))
    return without_marks.replace("ł", "l")


STOP_WORDS = {
    "a",
    "albo",
    "and",
    "czy",
    "do",
    "dla",
    "i",
    "in",
    "na",
    "or",
    "oraz",
    "the",
    "w",
    "with",
    "z",
}

QUERY_SYNONYMS = {
    "lampka": {"lampa", "lamp", "light"},
    "lampki": {"lampa", "lamp", "light"},
    "lampke": {"lampa", "lamp", "light"},
    "lampy": {"lampa", "lamp", "light"},
    "zarowka": {"lampa", "led", "light"},
    "zarowke": {"lampa", "led", "light"},
    "zarowki": {"lampa", "led", "light"},
    "swiatlo": {"lighting", "light", "lampa"},
    "swiatla": {"lighting", "light", "lampa"},
    "biale": {"jasne", "white", "clear", "led"},
    "biala": {"jasne", "white", "clear", "led"},
    "bialy": {"jasne", "white", "clear", "led"},
    "bialym": {"jasne", "white", "clear", "neutralne", "led"},
    "neutralna": {"biale", "jasne", "white", "clear", "led"},
    "neutralne": {"biale", "jasne", "white", "clear", "led"},
    "neutralny": {"biale", "jasne", "white", "clear", "led"},
    "jasna": {"biale", "neutralne", "white", "clear", "led"},
    "jasne": {"biale", "neutralne", "white", "clear", "led"},
    "jasny": {"biale", "neutralne", "white", "clear", "led"},
    "default": {"biale", "neutralne", "jasne", "led"},
    "domyslna": {"biale", "neutralne", "jasne", "led"},
    "domyslne": {"biale", "neutralne", "jasne", "led"},
    "klasyczna": {"biale", "neutralne", "jasne", "led"},
    "klasyczne": {"biale", "neutralne", "jasne", "led"},
    "normalna": {"biale", "neutralne", "jasne", "led"},
    "normalne": {"biale", "neutralne", "jasne", "led"},
    "standardowa": {"biale", "neutralne", "jasne", "led"},
    "standardowe": {"biale", "neutralne", "jasne", "led"},
    "zwykla": {"biale", "neutralne", "jasne", "led"},
    "zwykle": {"biale", "neutralne", "jasne", "led"},
    "ciepla": {"zolte", "warm", "ambient", "cozy"},
    "cieple": {"zolte", "warm", "ambient", "cozy"},
    "cieply": {"zolte", "warm", "ambient", "cozy"},
    "zolta": {"cieple", "warm", "ambient", "cozy"},
    "zolte": {"cieple", "warm", "ambient", "cozy"},
    "zolty": {"cieple", "warm", "ambient", "cozy"},
    "lazienki": {"lazienka", "bathroom", "jasne", "led"},
    "lazienka": {"bathroom", "jasne", "led"},
}


WHITE_LIGHT_QUERY_TERMS = {
    "biala",
    "biale",
    "bialy",
    "bialym",
    "clear",
    "cold",
    "cool",
    "default",
    "domyslna",
    "domyslne",
    "jasna",
    "jasne",
    "jasny",
    "klasyczna",
    "klasyczne",
    "neutral",
    "neutralna",
    "neutralne",
    "neutralny",
    "normalna",
    "normalne",
    "standardowa",
    "standardowe",
    "white",
    "zimna",
    "zimne",
    "zwykla",
    "zwykle",
}

WARM_LIGHT_QUERY_TERMS = {
    "amber",
    "ambient",
    "ciepla",
    "cieple",
    "cieply",
    "cozy",
    "golden",
    "nastrojowa",
    "nastrojowe",
    "przytulna",
    "przytulne",
    "warm",
    "yellow",
    "zolta",
    "zolte",
    "zolty",
}

WHITE_PRODUCT_MARKERS = {
    "bial",
    "bathroom",
    "clear",
    "daylight",
    "lazien",
    "neutral",
    "plafon",
    "white",
    "zimn",
}

SOFT_DECORATIVE_PRODUCT_MARKERS = {
    "accent",
    "akcent",
    "ambient",
    "ambientow",
    "amber",
    "bedside",
    "brass",
    "cage",
    "ceramic",
    "ciepl",
    "cloud",
    "comfort",
    "cozy",
    "crystal",
    "decor",
    "decorative",
    "dziecie",
    "edison",
    "elegan",
    "evening",
    "filament",
    "globe",
    "golden",
    "industrial",
    "kids",
    "klatk",
    "krysztal",
    "lantern",
    "loft",
    "lukow",
    "miek",
    "mood",
    "mosiez",
    "nastroj",
    "night",
    "nocn",
    "premium",
    "przytul",
    "rattan",
    "relaxed",
    "reflektor",
    "soft warm",
    "sofa",
    "spotlight",
    "szyn",
    "warm",
    "wieczor",
    "yellow",
    "zolt",
}


def query_terms(query: str) -> set[str]:
    terms = {
        term
        for term in comparable_text(query).split()
        if len(term) > 2 and term not in STOP_WORDS
    }

    expanded = set(terms)
    for term in terms:
        expanded.update(QUERY_SYNONYMS.get(term, set()))

    return expanded


def light_preference_for_query(query: str) -> str | None:
    terms = {
        term
        for term in comparable_text(query).split()
        if len(term) > 2 and term not in STOP_WORDS
    }
    wants_white = bool(terms & WHITE_LIGHT_QUERY_TERMS)
    wants_warm = bool(terms & WARM_LIGHT_QUERY_TERMS)

    if wants_white and not wants_warm:
        return "white"
    if wants_warm and not wants_white:
        return "warm"
    return None


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


def contains_any_marker(text: str, markers: set[str]) -> bool:
    return any(marker in text for marker in markers)


def is_product_allowed_for_light_preference(product: Product, preference: str | None) -> bool:
    if preference not in {"white", "warm"}:
        return True

    haystack = product_text(product)
    has_white_profile = contains_any_marker(haystack, WHITE_PRODUCT_MARKERS)
    has_soft_decorative_profile = contains_any_marker(haystack, SOFT_DECORATIVE_PRODUCT_MARKERS)

    if preference == "white":
        return not has_soft_decorative_profile or has_white_profile

    return has_soft_decorative_profile or not has_white_profile


def is_lamp_query(query: str) -> bool:
    terms = query_terms(query)
    return bool(terms & {"lamp", "lampa", "led", "light", "lighting", "swiatlo"})


def score_product(product: Product, query: str) -> int:
    product_id = comparable_text(product.id)
    name = comparable_text(product.name)
    category = comparable_text(product.category)
    description = comparable_text(product.description)
    tags = comparable_text(" ".join(product.tags))
    keywords = comparable_text(" ".join(product.keywords))
    attributes = comparable_text(" ".join(f"{key} {value}" for key, value in product.attributes.items()))
    haystack = " ".join([product_id, name, category, description, tags, keywords, attributes])
    comparable_query = comparable_text(query)
    light_preference = light_preference_for_query(query)

    if not is_product_allowed_for_light_preference(product, light_preference):
        return 0

    if comparable_query in product_id:
        return 100
    if comparable_query in name:
        return 90
    if comparable_query in haystack:
        return 60

    score = 0
    for term in query_terms(query):
        if term in product_id:
            score += 35
        if term in name:
            score += 30
        if term in category or term in tags:
            score += 22
        if term in keywords:
            score += 16
        if term in description or term in attributes:
            score += 10

    if light_preference == "white" and contains_any_marker(haystack, WHITE_PRODUCT_MARKERS):
        score += 18
    if light_preference == "warm" and contains_any_marker(haystack, SOFT_DECORATIVE_PRODUCT_MARKERS):
        score += 18

    return score


def map_sql_server_product(row: Any) -> Product:
    return Product(
        id=str(row.id),
        name=str(row.name),
        price=float(row.price),
        currency=str(row.currency or "PLN"),
        category=str(row.category or "lamp"),
        description=str(row.description or ""),
        tags=[str(row.category or "lamp")],
        keywords=normalize_text(f"{row.name} {row.category} {row.description}").split(),
        stock_status=str(row.stock_status or "unknown"),
        image_url=str(row.image_url) if row.image_url else None,
        attributes={"category": str(row.category or "lamp")},
    )
