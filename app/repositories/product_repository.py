from __future__ import annotations

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
        rows = self._fetch_all(f"SELECT TOP (100) {self._select_clause()} FROM products ORDER BY name")
        return [map_sql_server_product(row) for row in rows]

    def get_product(self, product_id: str) -> Product | None:
        rows = self._fetch_all(f"SELECT TOP (1) {self._select_clause()} FROM products WHERE id = ?", (product_id,))
        return map_sql_server_product(rows[0]) if rows else None

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        normalized = normalize_text(query)
        if not normalized:
            return self.list_products()[:limit]

        like = f"%{normalized}%"
        search_columns = self._search_columns()
        rows = self._fetch_all(
            f"""
            SELECT TOP ({int(limit)}) {self._select_clause()}
            FROM products
            WHERE {" OR ".join(f"LOWER(COALESCE(CAST({column} AS NVARCHAR(MAX)), '')) LIKE ?" for column in search_columns)}
            ORDER BY name
            """,
            tuple(like for _ in search_columns),
        )
        return [map_sql_server_product(row) for row in rows]

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
    return " ".join(value.lower().strip().split())


def score_product(product: Product, query: str) -> int:
    haystack = " ".join(
        [
            product.id,
            product.name,
            product.description,
            " ".join(product.tags),
            " ".join(product.keywords),
            " ".join(f"{key} {value}" for key, value in product.attributes.items()),
        ]
    ).lower()

    if query in product.id.lower():
        return 100
    if query in product.name.lower():
        return 90
    if query in haystack:
        return 60

    return sum(10 for word in query.split() if word and word in haystack)


def map_sql_server_product(row: Any) -> Product:
    return Product(
        id=str(row.id),
        name=str(row.name),
        price=float(row.price),
        currency=str(row.currency or "PLN"),
        category=str(row.category or "lamp"),
        description=str(row.description or ""),
        tags=[],
        keywords=[],
        stock_status=str(row.stock_status or "unknown"),
        image_url=str(row.image_url) if row.image_url else None,
        attributes={},
    )
