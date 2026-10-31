from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import get_settings
from app.api.routes import chat, products, system

logger = logging.getLogger("lamp_store.bot")
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
    allow_origin_regex=settings.allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    # Details stay in the server log: the client must not see SQL, paths or API keys.
    logger.error("Request failed: %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


app.include_router(system.router)
app.include_router(chat.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
