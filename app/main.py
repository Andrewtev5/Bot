from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import get_settings
from app.api.routes import chat, products, system

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    description=(
        "Base backend for the store chatbot. "
        "It already supports sessions, messages, product lookup, "
        "and a clean extension point for future AI integration."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(chat.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
