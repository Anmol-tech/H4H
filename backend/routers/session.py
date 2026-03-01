"""Session router — all core form-filling endpoints."""

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import Response

from models.schemas import (
    StartSessionRequest,
    StartSessionResponse,
    SessionStatusResponse,
    AnswerAudioResponse,
    ConfirmRequest,
    ConfirmResponse,
    FinalizeResponse,
    FieldMeta,
)
from services import session_manager
from services.asr import transcribe
from services.pdf_filler import generate_pdf
from data.fema_template import get_field, get_total_fields

router = APIRouter(prefix="/session", tags=["session"])


def _field_to_meta(field: dict | None) -> FieldMeta | None:
    """Convert a raw template field dict into a FieldMeta response model."""
    if not field:
        return None
    return FieldMeta(
        id=field["id"],
        field_name=field["field_name"],
        prompt=field["prompt"],
        type=field["type"],
        sensitive=field["sensitive"],
        audio_url=field.get("audio_file"),
    )


# ── POST /session/start ─────────────────────────────────
@router.post("/start", response_model=StartSessionResponse)
async def start_session(body: StartSessionRequest):
    """Create a new form-filling session and return the first question."""
    session = session_manager.create_session(body.template_id)
    first_field = get_field(session.template_id, 0)

    return StartSessionResponse(
        session_id=session.session_id,
        template_title="FEMA Disaster Aid Form",
        total_fields=get_total_fields(session.template_id),
        current_field=_field_to_meta(first_field),
    )


# ── GET /session/{id} ───────────────────────────────────
@router.get("/{session_id}", response_model=SessionStatusResponse)
async def get_session(session_id: str):
    """Get current question, progress, and answers so far."""
    session = session_manager.get_session(session_id)
    total = get_total_fields(session.template_id)
    current_field = get_field(session.template_id, session.current_index)

    return SessionStatusResponse(
        session_id=session.session_id,
        status=session.status.value,
        current_index=session.current_index,
        total_fields=total,
        current_field=_field_to_meta(current_field),
        pending_value=session.pending_value,
        answers=session.answers,
        progress_pct=round(len(session.answers) / total * 100, 1) if total else 0,
    )


# ── POST /session/{id}/answer_audio ─────────────────────
@router.post("/{session_id}/answer_audio", response_model=AnswerAudioResponse)
async def answer_audio(session_id: str, audio: UploadFile = File(...)):
    """
    Accept an audio file, run ASR (stubbed), and return the transcript.
    Moves session to CONFIRMING state.
    """
    session = session_manager.get_session(session_id)
    audio_bytes = await audio.read()

    # Real Whisper ASR
    result = await transcribe(audio_bytes, filename=audio.filename or "recording.wav")

    transcript = result["transcript"]

    # Move session to confirming
    session_manager.submit_answer(
        session_id,
        transcript=transcript,
        parsed_value=transcript,
    )

    return AnswerAudioResponse(
        transcript=transcript,
        parsed_value=transcript,
        confidence=1.0,
        field_name="",
    )


# ── POST /session/{id}/confirm ──────────────────────────
@router.post("/{session_id}/confirm", response_model=ConfirmResponse)
async def confirm_answer(session_id: str, body: ConfirmRequest):
    """Confirm or reject the pending answer. Advances to the next field if confirmed."""
    session = session_manager.confirm_answer(session_id, body.confirmed)
    current_field = get_field(session.template_id, session.current_index)

    if session.status.value == "complete":
        message = "All fields confirmed. Call /finalize to generate PDF."
    elif body.confirmed:
        message = f"Confirmed. Moving to question {session.current_index + 1}."
    else:
        message = "Answer rejected. Please try again."

    return ConfirmResponse(
        status=session.status.value,
        current_field=_field_to_meta(current_field) if session.status.value != "complete" else None,
        current_index=session.current_index,
        message=message,
    )


# ── POST /session/{id}/finalize ─────────────────────────
@router.post("/{session_id}/finalize", response_model=FinalizeResponse)
async def finalize_session(session_id: str):
    """Generate the filled PDF once all fields are confirmed."""
    session = session_manager.finalize_session(session_id)
    pdf_bytes = await generate_pdf(session)
    session.pdf_bytes = pdf_bytes

    return FinalizeResponse(
        status="complete",
        pdf_url=f"/session/{session_id}/pdf",
        message="PDF generated successfully. Download at the pdf_url.",
    )


# ── GET /session/{id}/pdf ───────────────────────────────
@router.get("/{session_id}/pdf")
async def download_pdf(session_id: str):
    """Download the filled PDF file."""
    session = session_manager.get_session(session_id)

    if session.pdf_bytes is None:
        # Generate on-the-fly if not already cached
        session.pdf_bytes = await generate_pdf(session)

    return Response(
        content=session.pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=formwhisper_{session_id}.pdf"},
    )
