"""
Utility helpers for generating audio from text using ElevenLabs.

Primary entry point: `generate_audio_bytes(text, voice_id, model_id, output_format)`
which returns raw MP3 bytes that you can save to disk or stream to clients.
"""

from __future__ import annotations

import os
from typing import Iterable

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

# Load environment variables from backend/.env when running locally
load_dotenv()

# Default voice/model/format can be overridden per call
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # friendly female English voice
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_FORMAT = "mp3_44100_128"


def _get_client() -> ElevenLabs:
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    return ElevenLabs(api_key=api_key)


def _stream_to_bytes(stream: Iterable[bytes]) -> bytes:
    """Combine streaming chunks into a single bytes object."""
    return b"".join(stream)


def generate_audio_bytes(
    text: str,
    *,
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
    output_format: str = DEFAULT_FORMAT,
) -> bytes:
    """
    Convert text to speech via ElevenLabs and return raw audio bytes.

    Args:
        text: Text to synthesize (required).
        voice_id: ElevenLabs voice ID.
        model_id: ElevenLabs TTS model.
        output_format: ElevenLabs output format (e.g., mp3_44100_128).

    Raises:
        RuntimeError: if ELEVENLABS_API_KEY is missing.
        ValueError: if text is empty.
        elevenlabs.api.error.ApiError: for upstream API errors.
    """
    if not text or not text.strip():
        raise ValueError("text is required")

    client = _get_client()
    audio_stream = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id=model_id,
        output_format=output_format,
    )
    return _stream_to_bytes(audio_stream)


def generate_audio_file(
    text: str,
    filepath: str,
    **kwargs,
) -> str:
    """
    Generate audio bytes and save to `filepath`. Returns the filepath.
    """
    audio_bytes = generate_audio_bytes(text, **kwargs)
    with open(filepath, "wb") as f:
        f.write(audio_bytes)
    return filepath
