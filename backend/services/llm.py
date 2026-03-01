"""
LLM service — Qwen2.5-VL-3B via AMD-hosted vLLM endpoint.

Provides a general-purpose chat completion interface and
a high-level PDF→VLM form-analysis pipeline.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, status
from PIL import Image as PILImage

from services.utils.pdf_to_images import pdf_to_images

logger = logging.getLogger(__name__)

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://165.245.130.21:30000")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "3000"))


async def chat(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 256,
    temperature: float = 0.3,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Send a chat-completion request to the Qwen VL endpoint and return the
    full response payload (OpenAI-compatible format).

    Messages can contain plain text or multimodal content parts (images).
    """
    payload = {
        "model": model or LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=payload,
        )

    if resp.status_code >= 400:
        try:
            err = resp.json()
        except Exception:
            err = resp.text
        logger.error(f"Upstream LLM error {resp.status_code}: {err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "LLM request failed",
                "upstream_status": resp.status_code,
                "upstream": err,
            },
        )

    return resp.json()


def extract_content(response: dict[str, Any]) -> str:
    """Pull the assistant message text out of a chat-completion response."""
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return ""


def build_image_message(
    image_base64: str, media_type: str, text: str
) -> dict[str, Any]:
    """Build an OpenAI-compatible multimodal user message with an image.

    Args:
        image_base64: raw base64 string of the image.
        media_type:   e.g. "image/png" or "image/jpeg".
        text:         the text prompt to accompany the image.
    """
    data_url = f"data:{media_type};base64,{image_base64}"
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }


def build_multi_image_message(
    images_base64: list[tuple[str, str]],
    text: str,
) -> dict[str, Any]:
    """Build a multimodal user message with multiple images.

    Args:
        images_base64: list of (base64_string, media_type) tuples.
        text:          the text prompt to accompany the images.
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for b64, media_type in images_base64:
        data_url = f"data:{media_type};base64,{b64}"
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    return {"role": "user", "content": content}


# ── High-level PDF analysis pipeline ────────────────────

# ── Patterns that indicate a non-fillable statement (used for post-filtering) ──
_NON_FIELD_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"\bI\s+(authorize|certify|agree|acknowledge|understand|consent|attest|swear|affirm|declare|verify)\b",
        re.I,
    ),
    re.compile(r"\b(penalty|penalties)\s+of\s+(perjury|law)\b", re.I),
    re.compile(r"\bprivacy\s+act\b", re.I),
    re.compile(r"\bpaperwork\s+(reduction|burden)\b", re.I),
    re.compile(r"\bOMB\s+(control|no|number|#)", re.I),
    re.compile(r"\bfor\s+official\s+use\s+only\b", re.I),
    re.compile(r"\bfor\s+office\s+use\s+only\b", re.I),
    re.compile(r"\brelease\s+information\s+to\b", re.I),
    re.compile(r"\bhereby\s+(authorize|certify|consent|affirm|declare)\b", re.I),
    re.compile(r"\bknowingly\s+(false|fraudulent)\b", re.I),
    re.compile(r"\bsubject\s+to\s+(criminal|civil)\b", re.I),
    re.compile(r"\bin\s+accordance\s+with\b", re.I),
    re.compile(r"\bpursuant\s+to\b", re.I),
    re.compile(r"\bsignature\b", re.I),
    re.compile(r"\bdate\s*signed\b", re.I),
    # Declaration / release sections
    re.compile(r"\bdeclaration\s+and\s+release\b", re.I),
    re.compile(r"\bby\s+my\s+signature\b", re.I),
    re.compile(r"\bread\s+the\s+form\s+carefully\b", re.I),
    re.compile(r"\bconsult\s+with\s+an\s+attorney\b", re.I),
    # For-office-use fields (inspector/FEMA staff fill these, not the applicant)
    re.compile(r"\binspector\s*(id|#|number)\b", re.I),
    re.compile(r"\bfema\s+application\s*(#|number)\b", re.I),
    re.compile(r"\bdisaster\s*(#|number)\b", re.I),
    re.compile(r"\bapplication\s*(#|number|no)\b", re.I),
]


def _is_non_fillable(field: dict) -> bool:
    """Return True if a parsed field looks like a legal statement, not a real input."""
    text = f"{field.get('label', '')} {field.get('prompt', '')} {field.get('field_name', '')}"
    for pat in _NON_FIELD_PATTERNS:
        if pat.search(text):
            return True
    return False


FORM_ANALYSIS_PROMPT = (
    "You are a warm, friendly form-filling assistant helping everyday people complete government forms by voice. "
    "You will receive one or more images of pages from a PDF form.\n\n"
    "⚠️  MOST IMPORTANT RULE — READ THIS FIRST:\n"
    "A FILLABLE FIELD is ONLY something with a BLANK space, line, box, or checkbox where the applicant must write/type/select.\n"
    "A STATEMENT the applicant merely reads or agrees to is NOT a field.\n"
    "Examples of things that are NOT fields (NEVER include these):\n"
    '  × "I authorize FEMA to verify all information..."\n'
    '  × "I authorize all custodians of records of my insurance..."\n'
    '  × "I certify that the above information is true..."\n'
    '  × "Penalty for false statements..."\n'
    '  × "Privacy Act Statement..."\n'
    '  × Any sentence that starts with "I authorize", "I certify", "I agree", "I understand", "I acknowledge"\n'
    'If you are unsure whether something is a fillable field, ask yourself: "Is there a blank for the person to write in?"\n'
    "If the answer is no, DO NOT include it.\n\n"
    "CRITICAL INSTRUCTIONS - READ CAREFULLY:\n"
    "1. SCAN EVERY SINGLE PAGE COMPLETELY:\n"
    "   - Read from top to bottom, left to right\n"
    "   - Check all sections, headers, footers, tables, columns\n"
    "   - Look in margins, boxes, and nested sections\n"
    "   - Do NOT skip any pages\n"
    "   - Do NOT stop early - continue until the last field on the last page\n"
    "2. IDENTIFY ONLY ACTUAL FILLABLE FIELDS — fields where a person must write, type, or select something:\n"
    "   - Text inputs (blank lines or boxes): names, titles, descriptions, addresses, cities, states, zip codes\n"
    "   - Date fields: birth dates, event dates, application dates\n"
    "   - Number fields: phone numbers, SSN, amounts, quantities, percentages\n"
    "   - Email addresses\n"
    "   - Yes/No questions that have a blank checkbox or radio button to mark\n"
    "   - Checkboxes (convert to yes/no or multiple choice)\n"
    "   - Radio buttons (convert to single-choice questions with all options)\n"
    "   - Dropdown/selection fields (list all available options)\n"
    "   - Text areas and comment boxes with blank space to write in\n"
    "   KEY TEST: If there is no blank line, box, checkbox, or input area next to/under the text, it is NOT a fillable field.\n"
    "3. EXCLUDE all of the following — these are NOT fillable fields:\n"
    "   - Authorization / consent / certification statements (e.g., 'I authorize FEMA to verify...', 'I certify that...')\n"
    "   - Legal disclaimers, penalty warnings, and privacy act notices\n"
    "   - Instructions, directions, and informational paragraphs\n"
    "   - Section titles, headers, sub-headers, and labels that are just describing a section\n"
    "   - Pre-printed text that the applicant does NOT fill in\n"
    "   - Paragraphs the applicant only reads and acknowledges by signing (the signature itself is excluded too)\n"
    "   - Physical signature lines and date-of-signature lines\n"
    "   - Drawing/sketch areas\n"
    "   - Barcodes or QR codes\n"
    "   - Pre-filled form numbers, OMB numbers, or 'For Office Use Only' fields\n"
    "   - File upload buttons\n"
    "   REMEMBER: If the form text is a statement the applicant is agreeing to (not filling in), SKIP IT.\n"
    "4. For checkboxes and selection fields:\n"
    "   - Single checkbox (yes/no): use type 'yes_no'\n"
    "   - Multiple independent checkboxes (select all that apply): use type 'checkbox' with all options listed\n"
    "   - Radio buttons (select exactly one): use type 'choice' with all options listed\n"
    "   - Always include ALL available options in the 'options' array\n"
    "5. CONVERSATIONAL QUESTION STYLE - This is critical:\n"
    "   - Write prompts as a warm, friendly human assistant would say them out loud\n"
    "   - Use natural, spoken language — NOT bureaucratic form labels\n"
    '   - Use contractions where natural (e.g., "What\'s", "Can you", "Could you")\n'
    '   - Add brief context or empathy where helpful (e.g., "No worries if this changes —")\n'
    '   - For sensitive fields (SSN, income), add a reassuring note (e.g., "This is kept private and secure.")\n'
    "   - For choice/checkbox fields, phrase as a natural spoken question then list options\n"
    "   - Avoid words like 'please provide', 'enter', 'input', 'specify' — use 'tell me', 'what is', 'can you share'\n"
    "   - Keep questions SHORT and clear — one sentence ideally\n"
    "6. COMPLETENESS CHECK:\n"
    "   - Count fields as you go\n"
    "   - Only count genuine fillable fields — do NOT pad with non-fillable content\n"
    "   - If a piece of text has no blank to fill, no checkbox to check, no option to select — it is NOT a field\n"
    "   - Quality over quantity: 15 real fields is better than 40 fields with junk\n"
    "   - Continue until you've processed every visible FILLABLE field on every page\n\n"
    "OUTPUT FORMAT - Return ONLY a valid JSON array. Each element must have:\n"
    '   - "field_name": descriptive snake_case identifier (e.g., "applicant_first_name", "mailing_street_address")\n'
    '   - "label": exact label text from the form (e.g., "First Name", "Street Address")\n'
    '   - "type": one of: text, date, ssn, phone, address, yes_no, number, email, checkbox, choice\n'
    '   - "prompt": conversational question as a friendly assistant would say it out loud\n'
    '   - "options": (REQUIRED for checkbox/choice types) array of all available options\n\n'
    "OUTPUT FORMAT EXAMPLES (structure only — DO NOT include these in your output):\n"
    "[\n"
    '  {"field_name":"<snake_case>","label":"<exact form label>","type":"text","prompt":"<friendly spoken question>"},\n'
    '  {"field_name":"<snake_case>","label":"<exact form label>","type":"choice","prompt":"<question>","options":["Option A","Option B","Option C"]}\n'
    "]\n"
    "WARNING: The placeholders above show structure only. Every field you output MUST come from the actual form images.\n\n"
    "IMPORTANT: Return ONLY the complete JSON array with ALL voice-fillable fields from ALL pages.\n"
    "Do NOT stop prematurely. Do NOT add markdown fences. Do NOT add explanations.\n"
    "The JSON array should contain EVERY fillable field you found.\n"
)


async def analyze_pdf_form(
    pdf_path: str | Path,
    *,
    max_tokens: int = 2048,
    model: str | None = None,
) -> dict[str, Any]:
    """End-to-end pipeline: PDF → page images → VLM → structured questions.

    Returns a dict with keys: questions, raw_content, pages_analyzed, model,
    prompt_tokens, completion_tokens, total_tokens.
    """
    # 1. Convert PDF pages to images.
    #    Qwen2.5-VL-3B tokenises images as 28×28px patches — large images consume
    #    thousands of tokens quickly.  96 DPI + max-1024px-wide keeps each page
    #    under ~1 200 patch tokens, leaving room for text + answer tokens.
    MAX_PAGES = 5
    MAX_IMG_WIDTH = 1024
    pages = pdf_to_images(pdf_path, dpi=96, fmt="jpeg")
    if not pages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF produced no pages — is the file valid?",
        )

    if len(pages) > MAX_PAGES:
        logger.warning(
            f"PDF has {len(pages)} pages — sending only first {MAX_PAGES} to stay within context limits."
        )
        pages = pages[:MAX_PAGES]

    # 2. Resize + JPEG-encode each page in-memory (avoids re-reading from disk)
    images_b64: list[tuple[str, str]] = []
    for page in pages:
        img: PILImage.Image = page["image"]
        if img.width > MAX_IMG_WIDTH:
            ratio = MAX_IMG_WIDTH / img.width
            img = img.resize((MAX_IMG_WIDTH, int(img.height * ratio)), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        images_b64.append((b64, "image/jpeg"))

    # 3. Build multi-image VLM request
    user_msg = build_multi_image_message(images_b64, text=FORM_ANALYSIS_PROMPT)

    response = await chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a warm, friendly voice assistant helping people fill out government forms. "
                    "Your job is to extract EVERY fillable field from the form images and turn each one into "
                    "a natural, conversational question — the kind a helpful human would ask out loud. "
                    "ONLY include fields that have a blank space, line, box, or checkbox for the person to fill in. "
                    "NEVER include authorization statements, legal disclaimers, consent paragraphs, or any "
                    "text that starts with 'I authorize', 'I certify', 'I agree', etc. — those are NOT fields. "
                    "Also exclude signature lines and date-signed lines. "
                    "Use contractions, empathetic phrasing, and plain language. Avoid bureaucratic wording. "
                    "Return ONLY a complete JSON array with ALL genuinely fillable fields found."
                ),
            },
            user_msg,
        ],
        max_tokens=max_tokens,
        temperature=0.2,
        model=model,
    )

    raw_content = extract_content(response)
    usage = response.get("usage", {})

    # Check if response might have been truncated
    completion_tokens = usage.get("completion_tokens", 0)
    if completion_tokens >= max_tokens * 0.95:
        logger.warning(
            f"Response used {completion_tokens}/{max_tokens} tokens - may have been truncated. "
            "Consider increasing max_tokens for this PDF."
        )

    logger.info(
        f"PDF form analysis complete: {len(pages)} pages analyzed, "
        f"{usage.get('total_tokens', 0)} tokens used"
    )
    logger.info(f"Raw VLM output (FULL):\n{raw_content}")

    # 4. Parse the JSON from the LLM output
    questions = _parse_questions_json(raw_content)

    logger.info(f"Successfully parsed {len(questions)} questions from VLM output")
    if len(questions) == 0:
        logger.warning("No questions were extracted! Check raw_content for issues.")

    return {
        "questions": questions,
        "raw_content": raw_content,
        "pages_analyzed": len(pages),
        "model": response.get("model", model or LLM_MODEL),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def _parse_questions_json(raw: str) -> list[dict[str, Any]]:
    """Best-effort parse of the LLM's JSON output into a questions list."""
    if not raw or not raw.strip():
        logger.warning("Empty raw output from VLM")
        return []

    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Also try to strip any leading/trailing text before/after the JSON
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"Initial JSON parse failed: {e}")
        # Try to find a JSON array in the output
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                logger.info("Successfully extracted JSON array from surrounding text")
            except json.JSONDecodeError as e2:
                logger.error(f"Failed to parse extracted JSON array: {e2}")
                logger.error(f"Extracted content: {match.group()[:200]}...")
                return []
        else:
            logger.error("No JSON array found in output")
            logger.error(f"Raw output (first 300 chars): {cleaned[:300]}")
            return []

    if not isinstance(data, list):
        logger.warning(f"Parsed data is not a list, got: {type(data)}")
        return []

    # Normalise, filter, and assign sequential IDs
    questions: list[dict[str, Any]] = []
    filtered_count = 0
    seq = 0
    for raw_idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            logger.warning(f"Item {raw_idx} is not a dict, skipping")
            continue

        # Validate required fields
        if not item.get("field_name") or not item.get("prompt"):
            logger.warning(f"Item {raw_idx} missing required fields, using defaults")

        # Post-processing filter: drop authorization / legal / consent statements
        if _is_non_fillable(item):
            logger.info(
                f"Filtered out non-fillable field: {item.get('field_name', '?')} "
                f"(label: {item.get('label', '?')!r})"
            )
            filtered_count += 1
            continue

        seq += 1
        question = {
            "id": seq,
            "field_name": item.get("field_name", f"field_{seq}"),
            "label": item.get("label", ""),
            "type": item.get("type", "text"),
            "prompt": item.get("prompt", item.get("label", "")),
        }

        # Add options if present (for checkbox/choice types)
        if "options" in item and isinstance(item["options"], list):
            question["options"] = item["options"]

        questions.append(question)

    if filtered_count:
        logger.info(
            f"Post-filter removed {filtered_count} non-fillable items from LLM output"
        )

    # Deduplicate by field_name — if two entries share a field_name but have
    # different labels, keep both and suffix the later one to make it unique.
    seen_fields: dict[str, int] = {}  # field_name -> count seen so far
    deduped: list[dict[str, Any]] = []
    for q in questions:
        fn = q["field_name"]
        if fn in seen_fields:
            prev = next((x for x in deduped if x["field_name"] == fn), None)
            if prev and prev.get("label") == q.get("label"):
                # Exact duplicate — drop silently
                logger.info(f"Deduped exact duplicate field_name: {fn!r}")
                continue
            # Different label — make the field_name unique by appending a counter
            seen_fields[fn] += 1
            q = dict(q)  # don't mutate the original
            q["field_name"] = f"{fn}_{seen_fields[fn]}"
            logger.info(f"Renamed duplicate field_name {fn!r} -> {q['field_name']!r}")
        else:
            seen_fields[fn] = 1
        deduped.append(q)

    # Re-number sequentially after filtering + dedup
    for i, q in enumerate(deduped, start=1):
        q["id"] = i

    return deduped


async def verify_answer(
    question: str,
    field_type: str,
    answer: str,
    options: list[str] | None = None,
) -> dict:
    """
    Ask the LLM to validate and format a user's spoken answer.

    Returns a dict with:
        valid (bool)            — True if the answer is appropriate for the question
        formatted_answer (str)  — answer cleaned up for the field type
        feedback (str)          — friendly re-ask message when invalid, else ""
    """
    # Free-text fields (names, addresses, general text) accept any non-empty
    # answer — use the LLM only to clean up spoken artifacts, never to reject.
    FREE_TEXT_TYPES = {"text", "address", "email"}
    is_free_text = field_type in FREE_TEXT_TYPES or not field_type

    options_hint = f"\nValid options: {', '.join(options)}" if options else ""

    if is_free_text:
        system_msg = (
            "You are a speech-to-text cleanup assistant for form filling. "
            "The user spoke their answer out loud and it was transcribed. "
            "Your job is to clean it up — remove filler words (um, uh, like, you know, so), "
            "fix capitalisation (names → Title Case, sentences → Sentence case), "
            "remove trailing punctuation artifacts, and strip any repeated words from transcription errors. "
            "Return ONLY a JSON object with exactly these keys (no extra text):\n"
            '  "valid": true  (always true for this field type)\n'
            '  "formatted_answer": the cleaned-up answer\n'
            '  "feedback": ""\n\n'
            "Examples:\n"
            '  "um john smith" → "John Smith"\n'
            '  "uh fourteen ninety five uh broadway" → "1495 Broadway"\n'
            '  "yes yes" → "Yes"\n'
            '  "new york new york" → "New York"'
        )
        user_content = f"Field type: {field_type}\nUser answered: {answer}"
    else:
        system_msg = (
            "You are a form assistant. A user spoke an answer to a form field. "
            "Clean up any speech artifacts (filler words, repetitions) and normalise the format. "
            "Return ONLY a JSON object with exactly these keys (no extra text):\n"
            '  "valid": true unless the answer is clearly the wrong format '
            "(e.g. saying 'hello' for a phone number, or 'yes' for a date)\n"
            '  "formatted_answer": the answer normalised for the field type '
            "(dates → MM/DD/YYYY, phones → (XXX) XXX-XXXX, SSN → XXX-XX-XXXX, "
            "yes_no → Yes or No, numbers → digits only, choice → closest matching option, "
            "names → Title Case, remove filler words like um/uh)\n"
            '  "feedback": if invalid, ONE short friendly sentence saying what format is needed; '
            "if valid, empty string\n\n"
            "IMPORTANT: be very lenient. When in doubt mark valid=true. "
            "Never reject an answer just because it sounds informal or spoken."
        )
        user_content = (
            f"Field type: {field_type}{options_hint}\n" f"User answered: {answer}"
        )

    response = await chat(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_content},
        ],
        max_tokens=200,
        temperature=0.1,
    )

    raw = extract_content(response)
    if isinstance(raw, list):
        raw = " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in raw
        )

    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        # extract first JSON object if surrounded by prose
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            cleaned = m.group()
        data = json.loads(cleaned)
        return {
            "valid": bool(data.get("valid", True)),
            "formatted_answer": str(data.get("formatted_answer", answer)),
            "feedback": str(data.get("feedback", "")),
        }
    except Exception as exc:
        logger.warning(f"verify_answer parse failed ({exc}) — treating as valid")
        return {"valid": True, "formatted_answer": answer, "feedback": ""}

    return questions
