"""Whisper STT — faster-whisper (CPU, int8) speech-to-text."""
from __future__ import annotations

import asyncio
import io
import tempfile
import os
from typing import Optional

import structlog

logger = structlog.get_logger()


class WhisperSTT:
    """Async wrapper around faster-whisper for speech-to-text transcription."""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "fr",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._default_language = language
        self._model = None

    def _load_model(self):
        """Lazy-load the Whisper model (imported here to avoid startup cost)."""
        if self._model is None:
            from faster_whisper import WhisperModel
            logger.info("whisper_loading", model=self._model_size, device=self._device)
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            logger.info("whisper_ready", model=self._model_size)
        return self._model

    def _sync_transcribe(self, audio_bytes: bytes, language: Optional[str]) -> str:
        """Synchronous transcription — runs in executor to avoid blocking the event loop."""
        model = self._load_model()
        lang = language or self._default_language

        # Write bytes to a temp file (faster-whisper expects a file path or file-like)
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            segments, info = model.transcribe(
                tmp_path,
                language=lang,
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info("whisper_transcribed", lang=info.language, chars=len(text))
            return text
        finally:
            os.unlink(tmp_path)

    async def transcribe(self, audio_bytes: bytes, language: Optional[str] = None) -> str:
        """Transcribe audio bytes and return the text.

        Runs faster-whisper in the default executor to avoid blocking the loop.
        """
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, self._sync_transcribe, audio_bytes, language
            )
        except Exception as exc:
            logger.error("whisper_transcription_failed", error=str(exc))
            raise
