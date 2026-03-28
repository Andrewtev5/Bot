from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }
