from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from app.core.config import Settings
from app.data.sample_products import SAMPLE_PRODUCTS
from app.domain.models import Product


class ProductRepository(Protocol):
    def list_products(self) -> list[Product]:
        ...

    def get_product(self, product_id: str) -> Product | None:
        ...

    def search_products(self, query: str, limit: int = 3) -> list[Product]:
        ...


class InMemoryProductRepository:
    def __init__(self, products: list[Product] | None = None) -> None:
        self._products = {product.id: product for product in (products or SAMPLE_PRODUCTS)}

    def list_products(self) -> list[Product]:
        return list(self._products.values())

    def get_product(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def search_products(self, query: str, limit: int = 3) -> list[Product]:
        normalized = query.strip().lower()
        if not normalized:
            return []

        scored: list[tuple[int, Product]] = []
        for product in self._products.values():
            score = self._score_product(product, normalized)
            if score > 0:
                scored.append((score, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [product for _, product in scored[:limit]]

    @staticmethod
    def _score_product(product: Product, query: str) -> int:
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

        words = [word for word in query.split() if word]
        return sum(10 for word in words if word in haystack)


class SQLiteProductRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)

    def list_products(self) -> list[Product]:
        query = """
        SELECT id, name, price, currency, category, description, stock_status, image_url
        FROM products
        ORDER BY name
        """
        rows = self._fetch_all(query)
        return [self._map_row(row) for row in rows]

    def get_product(self, product_id: str) -> Product | None:
        query = """
        SELECT id, name, price, currency, category, description, stock_status, image_url
        FROM products
        WHERE id = ?
        """
        rows = self._fetch_all(query, (product_id,))
        if not rows:
            return None
        return self._map_row(rows[0])

    def search_products(self, query: str, limit: int = 3) -> list[Product]:
        like = f"%{query.strip().lower()}%"
        sql = """
        SELECT id, name, price, currency, category, description, stock_status, image_url
        FROM products
        WHERE lower(id) LIKE ?
           OR lower(name) LIKE ?
           OR lower(description) LIKE ?
        ORDER BY name
        LIMIT ?
        """
        rows = self._fetch_all(sql, (like, like, like, limit))
        return [self._map_row(row) for row in rows]

    def _fetch_all(self, query: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        if not self._db_path.exists():
            return []
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        try:
            return list(connection.execute(query, params).fetchall())
        finally:
            connection.close()

    @staticmethod
    def _map_row(row: sqlite3.Row) -> Product:
        return Product(
            id=row["id"],
            name=row["name"],
            price=float(row["price"]),
            currency=row["currency"],
            category=row["category"],
            description=row["description"],
            tags=[],
            keywords=[],
            stock_status=row["stock_status"],
            image_url=row["image_url"],
            attributes={},
        )


def build_product_repository(settings: Settings) -> ProductRepository:
    if settings.product_db_mode == "sqlite":
        sqlite_repository = SQLiteProductRepository(settings.sqlite_db_path)
        if sqlite_repository.list_products():
            return sqlite_repository

    return InMemoryProductRepository()
