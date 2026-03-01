"""Pydantic request / response schemas for the FormWhisper API."""

from pydantic import BaseModel


# ── Session ──────────────────────────────────────────────


class FieldMeta(BaseModel):
    """Metadata for a single form field sent to the client."""

    id: int
    field_name: str
    prompt: str
    type: str
    sensitive: bool
    audio_url: str | None = None


class StartSessionRequest(BaseModel):
    template_id: str = "fema_009_0_3"


class StartSessionResponse(BaseModel):
    session_id: str
    template_title: str
    total_fields: int
    current_field: FieldMeta


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str  # active | confirming | complete
    current_index: int
    total_fields: int
    current_field: FieldMeta | None = None
    pending_value: str | None = None
    answers: dict[str, str]
    progress_pct: float


# ── Answer / Confirm ─────────────────────────────────────


class AnswerAudioResponse(BaseModel):
    transcript: str
    parsed_value: str
    confidence: float
    field_name: str


class ConfirmRequest(BaseModel):
    confirmed: bool


class ConfirmResponse(BaseModel):
    status: str  # active | confirming | complete
    current_field: FieldMeta | None = None
    current_index: int
    message: str


# ── Finalize / PDF ───────────────────────────────────────


class FinalizeResponse(BaseModel):
    status: str
    pdf_url: str
    message: str


# ── TTS (optional) ───────────────────────────────────────


class TTSRequest(BaseModel):
    text: str
    voice_id: str = "default"


class TTSResponse(BaseModel):
    audio_url: str | None = None
    message: str


# ── LLM ──────────────────────────────────────────────


class LLMMessage(BaseModel):
    """A chat message. `content` can be a plain string (text-only) or a list
    of content parts for multimodal / vision messages.

    Vision example::

        {"role": "user", "content": [
            {"type": "text", "text": "What fields are in this form?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]}
    """

    role: str  # system | user | assistant
    content: str | list  # str for text-only, list for multimodal content parts


class LLMChatRequest(BaseModel):
    messages: list[LLMMessage]
    max_tokens: int = 256
    temperature: float = 0.3
    model: str | None = None


class LLMChatResponse(BaseModel):
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AnalyzeFormRequest(BaseModel):
    """Send a base64-encoded image of a form page to the VL model."""

    image_base64: str  # base64 string (no data-url prefix needed)
    image_media_type: str = "image/png"  # image/png or image/jpeg
    prompt: str = (
        "You are a form-analysis assistant. Look at this form image and "
        "return a JSON array of objects, one per field. Each object must have: "
        '"field_name" (snake_case), "label" (human-readable), "type" '
        "(text | date | ssn | phone | address | yes_no | number | email), "
        '"prompt" (a natural question to ask the user to fill this field). '
        "Return ONLY valid JSON, no extra text."
    )
    max_tokens: int = 1024


class AnalyzeFormResponse(BaseModel):
    raw_content: str  # raw LLM output (should be JSON)
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ── Analyze PDF (file_id based) ──────────────────────────


class FormQuestion(BaseModel):
    """A single form field extracted by the VLM."""

    id: int
    field_name: str
    label: str
    type: str  # text | date | ssn | phone | address | yes_no | number | email | checkbox | choice
    prompt: str  # natural-language question for the user
    options: list[str] | None = (
        None  # for checkbox/choice types, list of available options
    )


class AnalyzePdfRequest(BaseModel):
    """Kick off form analysis using a previously uploaded PDF."""

    file_id: str
    max_tokens: int = (
        8192  # Comprehensive field extraction while leaving room for input tokens
    )


class AnalyzePdfResponse(BaseModel):
    """Structured result of the VLM form analysis."""

    file_id: str
    questions: list[FormQuestion]
    raw_content: str  # raw LLM output for debugging
    pages_analyzed: int
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ── Security (optional) ─────────────────────────────────


class SecurityCheckRequest(BaseModel):
    device_signal: str = ""
    session_id: str = ""


class SecurityCheckResponse(BaseModel):
    safe: bool
    message: str
