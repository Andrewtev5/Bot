from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "Lamp Store Bot"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    product_db_mode: str = "memory"
    sql_server_connection_string: str = ""
    default_language: str = "pl"
    allowed_origins: tuple[str, ...] = ("*",)
    allowed_origin_regex: str | None = None
    ai_provider: str = "none"
    grok_api_key: str = ""
    grok_model: str = "grok-4-1-fast"
    grok_base_url: str = "https://api.x.ai/v1"
    grok_timeout_seconds: float = 20.0
    max_products_for_ai: int = 5


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ("*",)
    items = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
    return items or ("*",)


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        app_name=os.getenv("APP_NAME", "Lamp Store Bot"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        debug=_parse_bool(os.getenv("DEBUG"), False),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        product_db_mode=os.getenv("PRODUCT_DB_MODE", "memory").strip().lower(),
        sql_server_connection_string=os.getenv("SQL_SERVER_CONNECTION_STRING", "").strip(),
        default_language=os.getenv("DEFAULT_LANGUAGE", "pl").strip().lower(),
        allowed_origins=_parse_origins(os.getenv("ALLOWED_ORIGINS")),
        allowed_origin_regex=os.getenv("ALLOWED_ORIGIN_REGEX", "").strip() or None,
        ai_provider=os.getenv("AI_PROVIDER", "none").strip().lower(),
        grok_api_key=os.getenv("GROK_API_KEY", "").strip(),
        grok_model=os.getenv("GROK_MODEL", "grok-4-1-fast").strip(),
        grok_base_url=os.getenv("GROK_BASE_URL", "https://api.x.ai/v1").rstrip("/"),
        grok_timeout_seconds=float(os.getenv("GROK_TIMEOUT_SECONDS", "20")),
        max_products_for_ai=max(1, int(os.getenv("MAX_PRODUCTS_FOR_AI", "5"))),
    )
