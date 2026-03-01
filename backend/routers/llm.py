"""LLM router — exposes the Qwen VL chat-completion endpoint to the frontend."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from models.schemas import (
    LLMChatRequest,
    LLMChatResponse,
    AnalyzeFormRequest,
    AnalyzeFormResponse,
    AnalyzePdfRequest,
    AnalyzePdfResponse,
    FormQuestion,
)
from services.llm import chat, extract_content, build_image_message, analyze_pdf_form

# Upload directory (same as routers/upload.py)
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

router = APIRouter(prefix="/llm", tags=["llm"])


@router.post("/chat", response_model=LLMChatResponse)
async def llm_chat(body: LLMChatRequest):
    """
    General-purpose chat completion.

    Supports both plain-text and multimodal (vision) messages.
    For vision, send content as a list of {type, text/image_url} parts.
    """
    messages = [m.model_dump() for m in body.messages]

    response = await chat(
        messages=messages,
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        model=body.model,
    )

    content = extract_content(response)
    usage = response.get("usage", {})

    return LLMChatResponse(
        content=content,
        model=response.get("model", body.model or ""),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
    )


@router.post("/analyze-form", response_model=AnalyzeFormResponse)
async def analyze_form(body: AnalyzeFormRequest):
    """
    Send a base64-encoded image of a form to the Qwen VL model.

    The model visually reads the form and returns a JSON array of fields
    with suggested prompts — ready to feed into ElevenLabs TTS.

    Pipeline (future):
      1. Upload PDF  →  convert to PNG/JPG  →  base64 encode
      2. POST here   →  VL model reads form  →  returns field questions
      3. Frontend feeds questions to TTS and voice-interaction flow
    """
    user_msg = build_image_message(
        image_base64=body.image_base64,
        media_type=body.image_media_type,
        text=body.prompt,
    )

    response = await chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a form-analysis assistant. You will receive an image "
                    "of a paper or digital form. Identify every fillable field and "
                    "return structured JSON only."
                ),
            },
            user_msg,
        ],
        max_tokens=body.max_tokens,
        temperature=0.2,
    )

    content = extract_content(response)
    usage = response.get("usage", {})

    return AnalyzeFormResponse(
        raw_content=content,
        model=response.get("model", ""),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
    )


@router.post("/analyze-pdf", response_model=AnalyzePdfResponse)
async def analyze_pdf(body: AnalyzePdfRequest):
    """
    Full pipeline: uploaded PDF → page images → VLM → structured questions.

    Steps:
      1. Look up the PDF by file_id in the uploads directory.
      2. Convert each page to a PNG image.
      3. Send all page images to the Qwen VL model.
      4. Parse the model output into a structured list of form questions.
    """
    pdf_path = UPLOAD_DIR / f"{body.file_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PDF with file_id '{body.file_id}' not found",
        )

    result = await analyze_pdf_form(
        pdf_path=pdf_path,
        max_tokens=body.max_tokens,
    )

    questions = [FormQuestion(**q) for q in result["questions"]]

    return AnalyzePdfResponse(
        file_id=body.file_id,
        questions=questions,
        raw_content=result["raw_content"],
        pages_analyzed=result["pages_analyzed"],
        model=result["model"],
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        total_tokens=result["total_tokens"],
    )
