"""Voice router — POST /api/voice for speech-to-text transcription."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from typing import Optional

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("")
async def transcribe_audio(
    request: Request,
    audio: UploadFile = File(...),
    language: Optional[str] = None,
):
    """Transcribe uploaded audio (WebM/Opus) using faster-whisper.

    Returns:
        {"text": "transcribed text"}
    """
    stt = request.app.state.stt
    if stt is None:
        raise HTTPException(status_code=503, detail="STT service unavailable")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    try:
        text = await stt.transcribe(audio_bytes, language=language)
        return {"text": text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
