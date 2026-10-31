from __future__ import annotations

from pathlib import Path

import pytest

from app.core.database import SqlServerConnectionPool, localdb_pipe_connection_string, replace_connection_value

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATHS = (
    PROJECT_ROOT / "DataBace" / "02_init_schema.sql",
    PROJECT_ROOT / "DataBace" / "03_seed_products.sql",
)
TEST_DATABASE = "DiplomaStoreBotTest"
TEST_CONNECTION_STRING = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=(localdb)\\MSSQLLocalDB;"
    f"DATABASE={TEST_DATABASE};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


def sql_batches(path: Path):
    batch: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip().upper() == "GO":
            yield "\n".join(batch).strip()
            batch = []
        else:
            batch.append(line)


def drop_database(cursor) -> None:
    cursor.execute(
        f"""
        IF DB_ID(N'{TEST_DATABASE}') IS NOT NULL
        BEGIN
            ALTER DATABASE [{TEST_DATABASE}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
            DROP DATABASE [{TEST_DATABASE}];
        END
        """
    )


@pytest.fixture(scope="session")
def sql_pool():
    """A throwaway database built from the project's own SQL scripts. Skipped when SQL Server is unavailable."""
    pyodbc = pytest.importorskip("pyodbc")
    connection_string = localdb_pipe_connection_string(TEST_CONNECTION_STRING) or TEST_CONNECTION_STRING
    master_connection_string = replace_connection_value(connection_string, "DATABASE", "master")

    try:
        master = pyodbc.connect(master_connection_string, timeout=5, autocommit=True)
    except pyodbc.Error as error:
        pytest.skip(f"SQL Server is unavailable: {error}")

    cursor = master.cursor()
    drop_database(cursor)
    cursor.execute(f"CREATE DATABASE [{TEST_DATABASE}];")

    connection = pyodbc.connect(connection_string, timeout=5)
    schema_cursor = connection.cursor()
    for path in SCHEMA_PATHS:
        for statement in sql_batches(path):
            if statement and not statement.upper().startswith("USE "):
                schema_cursor.execute(statement)
    connection.commit()
    connection.close()

    pool = SqlServerConnectionPool(connection_string)
    yield pool

    pool.close_all()
    drop_database(cursor)
    master.close()
