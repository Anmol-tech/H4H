"""PDF upload endpoints for receiving forms from the frontend."""

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR = UPLOAD_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """Accept a PDF file, store it, and return a handle + download URL."""
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted",
        )

    file_id = uuid4().hex
    save_path = UPLOAD_DIR / f"{file_id}.pdf"

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    save_path.write_bytes(data)

    return {
        "file_id": file_id,
        "original_filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": save_path.stat().st_size,
        "url": f"/upload/pdf/{file_id}",
    }


@router.get("/pdf/{file_id}")
async def get_pdf(file_id: str):
    """Return a previously uploaded PDF by its id."""
    path = UPLOAD_DIR / f"{file_id}.pdf"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF not found",
        )

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        headers={"Content-Disposition": f"inline; filename={path.name}"},
    )


@router.post("/audio")
async def upload_audio(file: UploadFile = File(...)):
    """Accept an audio file (mp3/webm/ogg) and store it."""
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only audio files are accepted",
        )

    file_id = uuid4().hex
    suffix = Path(file.filename or "").suffix or ".mp3"
    save_path = AUDIO_DIR / f"{file_id}{suffix}"

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    save_path.write_bytes(data)

    return {
        "file_id": file_id,
        "original_filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": save_path.stat().st_size,
        "url": f"/upload/audio/{file_id}",
    }


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Accept an audio file, send it to the Whisper model, and return the transcript."""
    from services.asr import transcribe

    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only audio files are accepted",
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    try:
        result = await transcribe(data, filename=file.filename or "recording.wav")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Transcription failed: {exc}",
        )

    return {
        "transcript": result["transcript"],
        "language": result.get("language"),
    }


@router.get("/audio/{file_id}")
async def get_audio(file_id: str):
    """Return a previously uploaded audio file by its id."""
    # try common suffixes
    for suffix in (".mp3", ".webm", ".ogg", ".wav", ".m4a"):
        path = AUDIO_DIR / f"{file_id}{suffix}"
        if path.exists():
            return FileResponse(
                path,
                media_type="audio/mpeg",
                filename=path.name,
                headers={"Content-Disposition": f"inline; filename={path.name}"},
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Audio not found",
    )
