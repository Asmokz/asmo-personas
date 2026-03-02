"""Conversations router — CRUD for conversation sessions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    persona_id: str


@router.get("")
async def list_conversations(persona_id: str, request: Request):
    """List conversations for a persona."""
    db = request.app.state.db
    return await db.get_conversations(persona_id)


@router.post("")
async def create_conversation(body: CreateConversationRequest, request: Request):
    """Create a new conversation and return its metadata."""
    personas = request.app.state.personas
    if body.persona_id not in personas:
        raise HTTPException(status_code=400, detail=f"Unknown persona: {body.persona_id}")

    db = request.app.state.db
    conv_id = await db.create_conversation(body.persona_id)
    conv = await db.get_conversation(conv_id)
    return conv


@router.get("/{conv_id}")
async def get_conversation(conv_id: str, request: Request):
    """Get conversation metadata + full history."""
    db = request.app.state.db
    conv = await db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    history = await db.get_history(conv_id, limit=100)
    return {**conv, "history": history}


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, request: Request):
    """Delete a conversation and all its history."""
    db = request.app.state.db
    deleted = await db.delete_conversation(conv_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}
