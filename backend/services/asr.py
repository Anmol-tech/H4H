"""
ASR (Automatic Speech Recognition) service — Whisper-based.
Sends audio to a self-hosted vLLM Whisper endpoint for transcription.
Uses ffmpeg to convert any browser audio format to WAV before sending.
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# Whisper model endpoint (same host as LLM, port 8000)
WHISPER_BASE_URL = "http://165.245.130.21:8000"
WHISPER_MODEL = "openai/whisper-large-v3"
WHISPER_TIMEOUT = 300  # seconds — transcription can be slow for long audio

# Locate ffmpeg — try PATH first, fall back to common macOS install locations
_FFMPEG = (
    shutil.which("ffmpeg")
    or (Path("/opt/homebrew/bin/ffmpeg").exists() and "/opt/homebrew/bin/ffmpeg")
    or (Path("/usr/local/bin/ffmpeg").exists() and "/usr/local/bin/ffmpeg")
    or None
)


def _convert_to_wav(audio_bytes: bytes, input_filename: str) -> bytes:
    """Convert any audio format to 16kHz mono WAV using ffmpeg."""
    if not _FFMPEG:
        raise RuntimeError("ffmpeg not found. Install it with: brew install ffmpeg")

    ext = input_filename.rsplit(".", 1)[-1].lower() if "." in input_filename else "webm"

    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / f"input.{ext}"
        out_path = Path(tmp) / "output.wav"

        in_path.write_bytes(audio_bytes)

        cmd = [
            _FFMPEG,
            "-y",
            "-i",
            str(in_path),
            "-ar",
            "16000",  # 16kHz sample rate (Whisper optimal)
            "-ac",
            "1",  # mono
            "-c:a",
            "pcm_s16le",  # 16-bit PCM WAV
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.error("ffmpeg failed: %s", result.stderr[:500])
            raise RuntimeError(f"ffmpeg conversion failed: {result.stderr[:200]}")

        wav_bytes = out_path.read_bytes()
        log.info(
            "Converted %d bytes (%s) → %d bytes WAV",
            len(audio_bytes),
            ext,
            len(wav_bytes),
        )
        return wav_bytes


async def transcribe(audio_bytes: bytes, filename: str = "recording.wav") -> dict:
    # Convert to WAV if not already
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
    if ext != "wav":
        audio_bytes = _convert_to_wav(audio_bytes, filename)
        filename = "recording.wav"

    url = f"{WHISPER_BASE_URL}/v1/audio/transcriptions"
    log.info("Sending %d bytes WAV to Whisper", len(audio_bytes))

    async with httpx.AsyncClient(timeout=WHISPER_TIMEOUT) as client:
        resp = await client.post(
            url,
            headers={"Authorization": "Bearer dummy"},
            files={"file": ("recording.wav", audio_bytes, "audio/wav")},
            data={
                "model": WHISPER_MODEL,
                "language": "en",
                "temperature": "0",
                "response_format": "json",
            },
        )
        if resp.status_code != 200:
            body = resp.text[:500]
            log.error("Whisper error %d: %s", resp.status_code, body)
            raise RuntimeError(f"Whisper returned {resp.status_code}: {body}")
        result = resp.json()
    transcript = result.get("text", "").strip()
    log.info("Whisper transcript (%d chars): %s", len(transcript), transcript[:120])
    return {"transcript": transcript, "language": result.get("language")}
