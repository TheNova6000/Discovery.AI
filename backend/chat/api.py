"""HTTP routes for the chat model (`/tunin/chat/...`), separate from the
Discovery.AI demo's `/chat` route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.auth import get_current_user_id

from .engine import chat_turn, start_session
from .models import ChatReply, ChatSession
from .store import SessionStore

router = APIRouter(prefix="/tunin/chat", tags=["tunin-chat"])


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)


@router.post("/sessions", response_model=ChatSession, status_code=201)
async def create_session(user_id: str = Depends(get_current_user_id)) -> ChatSession:
    session = await start_session(user_id)
    await SessionStore().save(session)
    return session


@router.get("/sessions/{session_id}", response_model=ChatSession)
async def read_session(session_id: str, user_id: str = Depends(get_current_user_id)) -> ChatSession:
    session = await SessionStore().get(session_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    return session


@router.post("/sessions/{session_id}/messages", response_model=ChatReply)
async def post_message(session_id: str, body: MessageIn, user_id: str = Depends(get_current_user_id)) -> ChatReply:
    store = SessionStore()
    session = await store.get(session_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    reply = await chat_turn(session, body.text)
    await store.save(reply.session)
    return reply
