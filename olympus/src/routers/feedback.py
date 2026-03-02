"""Feedback router — POST /api/feedback to label training log entries."""
from __future__ import annotations

import aiosqlite
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

_TRAINING_DB_PATH = os.environ.get("ALITA_TRAINING_DB_PATH", "/data/alita_training.db")


class FeedbackRequest(BaseModel):
    entry_id: str
    quality: Literal["good", "bad"]
    correction: Optional[str] = None


@router.post("")
async def submit_feedback(body: FeedbackRequest):
    """Update the quality label (and optional correction) of a training log entry."""
    try:
        async with aiosqlite.connect(_TRAINING_DB_PATH) as db:
            result = await db.execute(
                "UPDATE training_log SET quality = ?, correction = ? WHERE id = ?",
                (body.quality, body.correction, body.entry_id),
            )
            await db.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Entry not found")
        return {"updated": True, "entry_id": body.entry_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
