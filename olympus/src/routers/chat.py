"""Chat router — POST /api/chat (blocking) + WS /api/chat/stream (streaming)."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    conv_id: str
    persona_id: str
    content: str
    images: Optional[list[str]] = None  # base64-encoded images


@router.post("")
async def chat(body: ChatRequest, request: Request):
    """Non-streaming chat endpoint."""
    personas = request.app.state.personas
    persona = personas.get(body.persona_id)
    if persona is None:
        raise HTTPException(status_code=400, detail=f"Unknown persona: {body.persona_id}")

    db = request.app.state.db
    conv = await db.get_conversation(body.conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    history = await db.get_history(body.conv_id)
    history_before_len = len(history)

    reply_text = ""
    entry_id = ""
    tools_called: list[str] = []

    async for event in await persona.process(
        conv_id=body.conv_id,
        history=history,
        user_content=body.content,
        images=body.images,
    ):
        evt_type = event.get("type")
        if evt_type == "token":
            reply_text += event.get("content", "")
        elif evt_type == "tool_start":
            tools_called.append(event.get("name", ""))
        elif evt_type == "done":
            entry_id = event.get("entry_id", "")
        elif evt_type == "error":
            raise HTTPException(status_code=500, detail=event.get("message", "LLM error"))

    # Persist new messages
    new_messages = history[history_before_len:]
    if new_messages:
        await db.append_messages(body.conv_id, new_messages)

    # Auto-generate title from first user message
    if not conv.get("title") and body.content:
        await db.update_title(body.conv_id, body.content[:60].strip())

    # Fire-and-forget LTM embedding for Alita
    if body.persona_id == "alita" and reply_text and hasattr(persona, "embed_exchange"):
        asyncio.create_task(
            persona.embed_exchange(body.conv_id, body.content, reply_text)
        )

    return {"reply": reply_text, "entry_id": entry_id, "tools_called": tools_called}


@router.websocket("/stream")
async def chat_stream(websocket: WebSocket):
    """Streaming chat via WebSocket.

    Client sends one JSON message:
        {"conv_id": "...", "persona_id": "alita", "content": "...", "images": [...]}

    Server yields events:
        {"type": "token",      "content": "..."}
        {"type": "tool_start", "name": "...", "args": {...}}
        {"type": "tool_done",  "name": "...", "result": "..."}
        {"type": "done",       "entry_id": "..."}
        {"type": "error",      "message": "..."}
    """
    await websocket.accept()
    try:
        raw = await websocket.receive_text()
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
            await websocket.close()
            return

        conv_id = payload.get("conv_id", "")
        persona_id = payload.get("persona_id", "")
        content = payload.get("content", "")
        images = payload.get("images")

        personas = websocket.app.state.personas
        persona = personas.get(persona_id)
        if persona is None:
            await websocket.send_text(json.dumps({"type": "error", "message": f"Unknown persona: {persona_id}"}))
            await websocket.close()
            return

        db = websocket.app.state.db
        conv = await db.get_conversation(conv_id)
        if not conv:
            await websocket.send_text(json.dumps({"type": "error", "message": "Conversation not found"}))
            await websocket.close()
            return

        history = await db.get_history(conv_id)
        history_before_len = len(history)

        reply_text = ""
        entry_id = ""

        async for event in await persona.process(
            conv_id=conv_id,
            history=history,
            user_content=content,
            images=images,
        ):
            await websocket.send_text(json.dumps(event, ensure_ascii=False))
            evt_type = event.get("type")
            if evt_type == "token":
                reply_text += event.get("content", "")
            elif evt_type == "done":
                entry_id = event.get("entry_id", "")
                break
            elif evt_type == "error":
                break

        # Persist new messages
        new_messages = history[history_before_len:]
        if new_messages:
            await db.append_messages(conv_id, new_messages)

        # Auto title
        if not conv.get("title") and content:
            await db.update_title(conv_id, content[:60].strip())

        # Fire-and-forget LTM embedding for Alita
        if persona_id == "alita" and reply_text and hasattr(persona, "embed_exchange"):
            asyncio.create_task(
                persona.embed_exchange(conv_id, content, reply_text)
            )

    except WebSocketDisconnect:
        logger.info("ws_client_disconnected")
    except Exception as exc:
        logger.error("ws_error", error=str(exc))
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
