"""Portfolio router — CRUD for Alita's stock portfolio."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _get_db(request: Request):
    alita = request.app.state.personas.get("alita")
    if alita is None:
        raise HTTPException(status_code=503, detail="Alita persona not available")
    return alita.db


class PositionBody(BaseModel):
    shares: float
    avg_price: float
    label: Optional[str] = None


@router.get("")
async def list_portfolio(request: Request):
    """List all portfolio positions."""
    return await _get_db(request).get_portfolio()


@router.put("/{symbol}")
async def upsert_position(symbol: str, body: PositionBody, request: Request):
    """Create or update a position (raw set — no PRU recalculation)."""
    db = _get_db(request)
    sym = symbol.upper()
    await db.upsert_position(sym, body.shares, body.avg_price, body.label)
    return await db.get_position(sym)


@router.delete("/{symbol}")
async def delete_position(symbol: str, request: Request):
    """Remove a position from the portfolio."""
    deleted = await _get_db(request).delete_position(symbol.upper())
    if not deleted:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} not found")
    return {"deleted": True}
