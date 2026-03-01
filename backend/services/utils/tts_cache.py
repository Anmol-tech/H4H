"""
TTS audio caching utility.

Generates an MP3 for a given text prompt and saves it to disk using a
content-hash filename so the same question text is never synthesized twice.

Usage::

    from services.utils.tts_cache import ensure_question_audio

    filename = await ensure_question_audio("What's your first name?")
    # Returns e.g. "q_3a9f1bc2.mp3"
    # Frontend can then fetch: GET /tts/file/q_3a9f1bc2.mp3
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from dotenv import load_dotenv

# Load .env so ELEVENLABS_API_KEY is available before any service is imported
load_dotenv()

from services.tts_service import generate_audio_bytes  # noqa: E402

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
AUDIO_DIR = BASE_DIR / "assets" / "texttoaudio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _prompt_hash(text: str) -> str:
    """SHA-256 of the normalised text → first 8 hex chars as filename stem."""
    normalised = text.strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _audio_path(text: str) -> Path:
    return AUDIO_DIR / f"q_{_prompt_hash(text)}.mp3"


def audio_filename(text: str) -> str:
    """Return just the filename (not the full path)."""
    return _audio_path(text).name


def audio_exists(text: str) -> bool:
    return _audio_path(text).exists()


async def _synthesize_to_file(text: str, dest: Path) -> None:
    """Call ElevenLabs via tts_service and write MP3 bytes to *dest*."""
    # generate_audio_bytes is synchronous (ElevenLabs SDK); run in thread pool
    audio_bytes = await asyncio.to_thread(generate_audio_bytes, text)
    dest.write_bytes(audio_bytes)
    logger.info(f"TTS audio saved: {dest.name} ({len(audio_bytes)} bytes)")


async def ensure_question_audio(text: str) -> str | None:
    """
    Return the MP3 filename for *text*, generating it if it doesn't exist yet.

    Returns:
        filename (str)  e.g. "q_3a9f1bc2deadbeef.mp3"  — serves via /tts/file/{filename}
        None            — if TTS is unavailable (no API key) or synthesis fails
    """
    if not text or not text.strip():
        return None

    dest = _audio_path(text)

    if dest.exists():
        logger.debug(f"TTS cache hit: {dest.name}")
        return dest.name

    logger.debug(f"TTS cache miss — generating audio for: {text[:60]}...")
    try:
        await _synthesize_to_file(text, dest)
        return dest.name
    except Exception as exc:
        logger.warning(f"TTS generation skipped: {exc}")
        return None


async def ensure_all_audio(
    prompts: list[str], batch_size: int = 3, delay: float = 0.5
) -> list[str | None]:
    """
    Generate audio for a list of prompts in small sequential batches to avoid
    hitting ElevenLabs rate limits.  Each batch runs concurrently; batches are
    separated by a short delay.

    Returns a list of filenames (or None for any that failed) in the same order.
    """
    results: list[str | None] = []
    for i in range(0, len(prompts), batch_size):
        batch = prompts[i : i + batch_size]
        batch_results = await asyncio.gather(
            *[ensure_question_audio(p) for p in batch], return_exceptions=False
        )
        results.extend(batch_results)
        if i + batch_size < len(prompts):
            await asyncio.sleep(delay)
    return results
