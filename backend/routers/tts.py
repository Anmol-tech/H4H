"""TTS router — ElevenLabs integration."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from models.schemas import TTSRequest, TTSResponse
from services import tts as tts_service

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIO_DIR = BASE_DIR / "data" / "uploads" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter(tags=["tts"])


@router.post("/tts", response_model=TTSResponse)
async def text_to_speech(body: TTSRequest):
    """
    Generate speech audio from text via ElevenLabs.
    Returns a data URL (audio/mpeg) so the frontend can play it without storage.
    """
    audio_url = await tts_service.synthesize(body.text, voice_id=body.voice_id)
    return TTSResponse(audio_url=audio_url, message="ok")


@router.get("/tts/file/{filename}")
async def get_tts_audio(filename: str):
    """
    Return a generated audio file by exact filename (e.g., abc123.mp3).
    The frontend supplies the filename previously received from the backend.
    """
    # Prevent path traversal
    safe_name = Path(filename).name
    path = AUDIO_DIR / safe_name

    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found",
        )

    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=path.name,
        headers={"Content-Disposition": f"inline; filename={path.name}"},
    )
