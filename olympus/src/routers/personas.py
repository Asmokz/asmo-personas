"""Personas router — GET /api/personas."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/personas", tags=["personas"])


@router.get("")
async def list_personas(request: Request):
    """Return metadata for all available personas."""
    personas = request.app.state.personas
    return [p.get_info() for p in personas.values()]
