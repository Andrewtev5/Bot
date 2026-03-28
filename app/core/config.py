from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "Lamp Store Bot"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    product_db_mode: str = "memory"
    sqlite_db_path: str = "database/products.db"
    default_language: str = "ru"
    allowed_origins: tuple[str, ...] = ("*",)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ("*",)
    items = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
    return items or ("*",)


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Lamp Store Bot"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        debug=_parse_bool(os.getenv("DEBUG"), False),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        product_db_mode=os.getenv("PRODUCT_DB_MODE", "memory").strip().lower(),
        sqlite_db_path=os.getenv("SQLITE_DB_PATH", "database/products.db"),
        default_language=os.getenv("DEFAULT_LANGUAGE", "ru").strip().lower(),
        allowed_origins=_parse_origins(os.getenv("ALLOWED_ORIGINS")),
    )
