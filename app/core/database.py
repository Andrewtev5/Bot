from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

IDLE_CONNECTION_CHECK_SECONDS = 30
MAX_IDLE_CONNECTIONS = 8


class SqlServerConnectionPool:
    """Reuses open connections and runs sqllocaldb only when the last working connection string fails."""

    def __init__(self, connection_string: str, connect_timeout: int = 5) -> None:
        self._connection_string = connection_string
        self._connect_timeout = connect_timeout
        self._lock = Lock()
        self._idle: list[tuple[Any, float]] = []
        self._resolved_connection_string: str | None = None

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        """Gives a cursor on a pooled connection: commits on success, drops the connection on a failure."""
        connection = self._acquire()
        try:
            yield connection.cursor()
            connection.commit()
        except Exception:
            self._close_quietly(connection)
            raise
        self._release(connection)

    def close_all(self) -> None:
        with self._lock:
            idle, self._idle = self._idle, []
        for connection, _ in idle:
            self._close_quietly(connection)

    def _acquire(self) -> Any:
        while True:
            with self._lock:
                if not self._idle:
                    break
                connection, idle_since = self._idle.pop()

            if time.monotonic() - idle_since < IDLE_CONNECTION_CHECK_SECONDS or self._is_alive(connection):
                return connection
            self._close_quietly(connection)

        return self._connect()

    def _release(self, connection: Any) -> None:
        with self._lock:
            if len(self._idle) < MAX_IDLE_CONNECTIONS:
                self._idle.append((connection, time.monotonic()))
                return
        self._close_quietly(connection)

    def _connect(self) -> Any:
        pyodbc = _import_pyodbc()
        if not self._connection_string:
            raise RuntimeError("SQL_SERVER_CONNECTION_STRING is empty.")

        last_error = None
        if self._resolved_connection_string:
            try:
                return pyodbc.connect(self._resolved_connection_string, timeout=self._connect_timeout)
            except pyodbc.Error as error:
                last_error = error
                self._resolved_connection_string = None

        candidates = [localdb_pipe_connection_string(self._connection_string), self._connection_string]
        for candidate in dict.fromkeys(value for value in candidates if value):
            try:
                connection = pyodbc.connect(candidate, timeout=self._connect_timeout)
                self._resolved_connection_string = candidate
                return connection
            except pyodbc.Error as error:
                last_error = error

        raise last_error

    @staticmethod
    def _is_alive(connection: Any) -> bool:
        try:
            connection.cursor().execute("SELECT 1;").fetchall()
            return True
        except Exception:
            return False

    @staticmethod
    def _close_quietly(connection: Any) -> None:
        try:
            connection.close()
        except Exception:
            pass


def _import_pyodbc() -> Any:
    try:
        import pyodbc
    except ImportError as error:
        raise RuntimeError(
            "pyodbc is required for PRODUCT_DB_MODE=mssql. "
            "Install it and Microsoft ODBC Driver for SQL Server."
        ) from error
    return pyodbc


def localdb_pipe_connection_string(connection_string: str) -> str | None:
    server = connection_string_value(connection_string, "SERVER")
    prefix = "(localdb)\\"
    if not server or not server.lower().startswith(prefix):
        return None

    instance = server[len(prefix) :].strip()
    if not instance:
        return None

    try:
        subprocess.run(["sqllocaldb", "start", instance], check=True, capture_output=True, text=True)
        result = subprocess.run(
            ["sqllocaldb", "info", instance],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    pipe_name = next(
        (
            line.split(":", 1)[1].strip()
            for line in result.stdout.splitlines()
            if line.lower().startswith("instance pipe name:")
        ),
        "",
    )
    if not pipe_name:
        return None

    candidate = replace_connection_value(connection_string, "SERVER", pipe_name)
    return replace_connection_value(candidate, "ENCRYPT", "no")


def connection_string_value(connection_string: str, key: str) -> str | None:
    prefix = f"{key.upper()}="
    for part in connection_string.split(";"):
        if part.strip().upper().startswith(prefix):
            return part.split("=", 1)[1].strip()
    return None


def replace_connection_value(connection_string: str, key: str, value: str) -> str:
    parts: list[str] = []
    replaced = False
    for part in connection_string.split(";"):
        if not part:
            continue
        part_key = part.split("=", 1)[0].strip().upper() if "=" in part else ""
        if part_key == key.upper():
            parts.append(f"{part.split('=', 1)[0]}={value}")
            replaced = True
        else:
            parts.append(part)

    if not replaced:
        parts.append(f"{key}={value}")
    return ";".join(parts) + ";"
