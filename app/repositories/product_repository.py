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
    return "".join(character for character in normalized if not unicodedata.combining(character))


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
    "lazienki": {"lazienka", "bathroom", "jasne", "led"},
    "lazienka": {"bathroom", "jasne", "led"},
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
