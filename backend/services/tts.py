"""
ElevenLabs Text-to-Speech helper.
Transforms text into speech and returns a data URL for easy playback in the UI.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException, status

log = logging.getLogger(__name__)

# Prefer standard name; fall back to legacy key in .env for convenience.
ELEVEN_API_KEY = os.getenv("ELEVENLABS_API_KEY") or os.getenv("apiKey")

# A sensible default voice; users can override via request.voice_id.
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (English)

# ElevenLabs free/starter tier allows at most 2 concurrent requests.
# This semaphore ensures we never exceed that, preventing 429 errors.
_ELEVEN_CONCURRENCY = int(os.getenv("ELEVENLABS_CONCURRENCY", "2"))
_eleven_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Return (and lazily create) the per-event-loop semaphore."""
    global _eleven_semaphore
    # Re-create if the event loop has changed (e.g. during tests)
    try:
        loop = asyncio.get_running_loop()
        if _eleven_semaphore is None or _eleven_semaphore._loop is not loop:  # type: ignore[attr-defined]
            _eleven_semaphore = asyncio.Semaphore(_ELEVEN_CONCURRENCY)
    except RuntimeError:
        _eleven_semaphore = asyncio.Semaphore(_ELEVEN_CONCURRENCY)
    return _eleven_semaphore


async def synthesize(text: str, voice_id: str | None = None) -> str:
    """
    Call ElevenLabs TTS and return an audio data URL (MP3).

    Concurrent calls are throttled to ELEVENLABS_CONCURRENCY (default 2) to
    avoid hitting ElevenLabs' concurrent-request limit.  Retries up to 3 times
    with exponential back-off on 429 responses before raising.

    Raises HTTPException on permanent failure.
    """
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text is required",
        )

    if not ELEVEN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing ELEVENLABS_API_KEY",
        )

    vid = DEFAULT_VOICE_ID if voice_id in (None, "", "default") else voice_id
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream"

    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    payload: dict[str, Any] = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    max_retries = 3
    last_err: Any = None

    async with _get_semaphore():
        for attempt in range(max_retries):
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code == 429:
                wait = 2**attempt  # 1s, 2s, 4s
                log.warning(
                    "ElevenLabs 429 (concurrent limit) on attempt %d/%d — "
                    "retrying in %ds",
                    attempt + 1,
                    max_retries,
                    wait,
                )
                try:
                    last_err = resp.json()
                except Exception:
                    last_err = resp.text
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait)
                continue

            if resp.status_code >= 400:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={"message": "ElevenLabs TTS failed", "upstream": err},
                )

            audio_b64 = base64.b64encode(resp.content).decode("ascii")
            return f"data:audio/mpeg;base64,{audio_b64}"

    # All retries exhausted on 429
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "message": "ElevenLabs rate limit exceeded after retries",
            "upstream": last_err,
        },
    )
