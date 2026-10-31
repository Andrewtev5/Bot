from types import SimpleNamespace

import pytest

from app.core import database
from app.core.database import SqlServerConnectionPool
from app.repositories.product_repository import SqlServerProductRepository


def product_row(product_id: str = "smart-wifi-lamp") -> SimpleNamespace:
    return SimpleNamespace(
        id=product_id,
        name="Lampa Smart WiFi",
        price=40,
        currency="PLN",
        category="Smart home",
        description="Inteligentna lampa.",
        name_en="Smart WiFi Lamp",
        description_en="Smart lamp.",
        meta_pl="[]",
        meta_en="[]",
        stock_status="in_stock",
        image_url="images/lamp2.jpg",
    )


class CountingRepository(SqlServerProductRepository):
    def __init__(self, rows=None, cache_seconds: float = 300.0) -> None:
        super().__init__(pool=None, cache_seconds=cache_seconds)
        self.rows = rows if rows is not None else [product_row()]
        self.fetches = 0

    def _fetch_products(self):
        self.fetches += 1
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows


def test_catalog_is_read_from_database_once():
    repository = CountingRepository()

    for _ in range(5):
        repository.search_products("smart lampa")
    repository.list_products()
    repository.get_product("smart-wifi-lamp")

    assert repository.fetches == 1


def test_catalog_is_refreshed_after_cache_expires():
    repository = CountingRepository(cache_seconds=0)

    repository.list_products()
    repository.list_products()

    assert repository.fetches == 2


def test_previous_catalog_is_served_when_refresh_fails():
    repository = CountingRepository(cache_seconds=0)
    repository.list_products()

    repository.rows = RuntimeError("database is down")

    assert [product.id for product in repository.list_products()] == ["smart-wifi-lamp"]


def test_error_is_raised_when_there_is_no_previous_catalog():
    repository = CountingRepository(rows=RuntimeError("database is down"))

    with pytest.raises(RuntimeError):
        repository.list_products()


def test_pool_reuses_one_connection(sql_pool):
    with sql_pool.cursor() as cursor:
        cursor.execute("SELECT @@SPID AS spid;")
        first = cursor.fetchone().spid

    with sql_pool.cursor() as cursor:
        cursor.execute("SELECT @@SPID AS spid;")
        second = cursor.fetchone().spid

    assert first == second


def test_pool_runs_sqllocaldb_only_for_the_first_connection(sql_pool, monkeypatch):
    calls = []
    original = database.localdb_pipe_connection_string

    def counting(connection_string):
        calls.append(connection_string)
        return original(connection_string)

    monkeypatch.setattr(database, "localdb_pipe_connection_string", counting)
    pool = SqlServerConnectionPool(sql_pool._connection_string)

    for _ in range(3):
        connection = pool._connect()
        connection.close()

    assert len(calls) == 1


def test_failed_transaction_is_rolled_back(sql_pool):
    product_id = "rollback-check"

    with pytest.raises(RuntimeError):
        with sql_pool.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO dbo.chat_sessions (id, language) VALUES (?, 'pl');
                """,
                product_id,
            )
            raise RuntimeError("failure after the insert")

    with sql_pool.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM dbo.chat_sessions WHERE id = ?;", product_id)
        assert cursor.fetchone().total == 0
