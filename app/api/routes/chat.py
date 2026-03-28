from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.api.dependencies import get_chat_service
from app.api.schemas import (
    ChatMessageResponse,
    ChatSessionResponse,
    CreateSessionRequest,
    ProductResponse,
    SendMessageRequest,
    SendMessageResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])


def _serialize_session(session) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        language=session.language,
        user_id=session.user_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            ChatMessageResponse(
                id=message.id,
                role=message.role.value,
                text=message.text,
                created_at=message.created_at,
                metadata=message.metadata,
            )
            for message in session.messages
        ],
    )


@router.post("/sessions", response_model=ChatSessionResponse)
def create_session(payload: CreateSessionRequest) -> ChatSessionResponse:
    service = get_chat_service()
    session = service.create_session(language=payload.language, user_id=payload.user_id)
    return _serialize_session(session)


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def get_session(session_id: str) -> ChatSessionResponse:
    service = get_chat_service()
    try:
        session = service.get_session(session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _serialize_session(session)


@router.post("/messages", response_model=SendMessageResponse)
def send_message(payload: SendMessageRequest) -> SendMessageResponse:
    service = get_chat_service()
    try:
        session, reply, matched_products = service.process_message(
            text=payload.text,
            session_id=payload.session_id,
            language=payload.language,
            user_id=payload.user_id,
            metadata=payload.metadata,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return SendMessageResponse(
        session=_serialize_session(session),
        reply=ChatMessageResponse(
            id=reply.id,
            role=reply.role.value,
            text=reply.text,
            created_at=reply.created_at,
            metadata=reply.metadata,
        ),
        matched_products=[ProductResponse.model_validate(asdict(product)) for product in matched_products],
    )
