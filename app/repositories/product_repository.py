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

    def list_products(self) -> list[Product]:
        rows = self._fetch_all(
            """
            SELECT TOP (100)
                id, name, price, currency, category, description, stock_status, image_url
            FROM products
            ORDER BY name
            """
        )
        return [map_sql_server_product(row) for row in rows]

    def get_product(self, product_id: str) -> Product | None:
        rows = self._fetch_all(
            """
            SELECT TOP (1)
                id, name, price, currency, category, description, stock_status, image_url
            FROM products
            WHERE id = ?
            """,
            (product_id,),
        )
        return map_sql_server_product(rows[0]) if rows else None

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        normalized = normalize_text(query)
        if not normalized:
            return self.list_products()[:limit]

        like = f"%{normalized}%"
        rows = self._fetch_all(
            f"""
            SELECT TOP ({int(limit)})
                id, name, price, currency, category, description, stock_status, image_url
            FROM products
            WHERE LOWER(id) LIKE ?
               OR LOWER(name) LIKE ?
               OR LOWER(description) LIKE ?
               OR LOWER(category) LIKE ?
            ORDER BY name
            """,
            (like, like, like, like),
        )
        return [map_sql_server_product(row) for row in rows]

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
