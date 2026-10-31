from __future__ import annotations

import json
import logging
import time
from threading import Lock
from typing import Any, Protocol

from app.core.config import Settings
from app.core.database import SqlServerConnectionPool
from app.data.sample_products import SAMPLE_PRODUCTS
from app.domain.models import Product
from app.search.ranking import derive_product_keywords, rank_products

logger = logging.getLogger(__name__)


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
        return rank_products(self.list_products(), query, limit)


class SqlServerProductRepository:
    """Keeps the catalog in memory: it changes rarely, while a chat message reads it several times."""

    def __init__(self, pool: SqlServerConnectionPool, cache_seconds: float = 300.0) -> None:
        self._pool = pool
        self._cache_seconds = cache_seconds
        self._lock = Lock()
        self._products: dict[str, Product] | None = None
        self._expires_at = 0.0

    def list_products(self) -> list[Product]:
        return list(self._catalog().values())

    def get_product(self, product_id: str) -> Product | None:
        return self._catalog().get(product_id)

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        return rank_products(self.list_products(), query, limit)

    def _catalog(self) -> dict[str, Product]:
        with self._lock:
            if self._products is not None and time.monotonic() < self._expires_at:
                return self._products

            try:
                products = [map_sql_server_product(row) for row in self._fetch_products()]
                self._products = {product.id: product for product in products}
            except Exception:
                if self._products is None:
                    raise
                logger.exception("Catalog refresh failed; serving the previous copy.")

            self._expires_at = time.monotonic() + self._cache_seconds
            return self._products

    def _fetch_products(self) -> list[Any]:
        with self._pool.cursor() as cursor:
            cursor.execute(
                """
                SELECT TOP (500)
                    id,
                    name_pl AS name,
                    price,
                    currency,
                    tag_pl AS category,
                    description_pl AS description,
                    name_en,
                    description_en,
                    meta_pl,
                    meta_en,
                    stock_status,
                    image AS image_url
                FROM dbo.products
                ORDER BY name_pl;
                """
            )
            return list(cursor.fetchall())


def build_product_repository(settings: Settings, pool: SqlServerConnectionPool) -> ProductRepository:
    if settings.product_db_mode == "mssql":
        return SqlServerProductRepository(pool, cache_seconds=settings.catalog_cache_seconds)

    return InMemoryProductRepository()


def map_sql_server_product(row: Any) -> Product:
    tags = parse_product_tags(row.meta_pl) + parse_product_tags(row.meta_en)
    tags = list(dict.fromkeys(tags))
    keywords = derive_product_keywords(
        str(row.id),
        str(row.name),
        str(row.category or "lamp"),
        str(row.description or ""),
        str(row.name_en or ""),
        str(row.description_en or ""),
        " ".join(tags),
    )
    return Product(
        id=str(row.id),
        name=str(row.name),
        price=float(row.price),
        currency=str(row.currency or "PLN"),
        category=str(row.category or "lamp"),
        description=str(row.description or ""),
        tags=tags or [str(row.category or "lamp")],
        keywords=keywords,
        stock_status=str(row.stock_status or "unknown"),
        image_url=str(row.image_url) if row.image_url else None,
        attributes={
            "category": str(row.category or "lamp"),
            "english_name": str(row.name_en or ""),
            "english_description": str(row.description_en or ""),
            "keywords": ", ".join(keywords[:24]),
        },
    )


def parse_product_tags(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(parsed, list):
        return []
    return [str(tag).strip() for tag in parsed if str(tag).strip()]
