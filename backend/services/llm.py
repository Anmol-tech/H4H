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
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct")
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

FORM_ANALYSIS_PROMPT = (
    "You are a warm, friendly form-filling assistant helping everyday people complete government forms by voice. "
    "You will receive one or more images of pages from a PDF form.\n\n"
    "CRITICAL INSTRUCTIONS - READ CAREFULLY:\n"
    "1. SCAN EVERY SINGLE PAGE COMPLETELY:\n"
    "   - Read from top to bottom, left to right\n"
    "   - Check all sections, headers, footers, tables, columns\n"
    "   - Look in margins, boxes, and nested sections\n"
    "   - Do NOT skip any pages\n"
    "   - Do NOT stop early - continue until the last field on the last page\n"
    "2. IDENTIFY ALL VOICE-FILLABLE FIELDS (typically 20-50+ fields per form):\n"
    "   - Text inputs: names, titles, descriptions, addresses, cities, states, zip codes\n"
    "   - Date fields: birth dates, event dates, application dates\n"
    "   - Number fields: phone numbers, SSN, amounts, quantities, percentages\n"
    "   - Email addresses\n"
    "   - Yes/No questions and boolean fields\n"
    "   - Checkboxes (all checkboxes - convert to yes/no or multiple choice)\n"
    "   - Radio buttons (convert to single-choice questions with all options)\n"
    "   - Dropdown/selection fields (list all available options)\n"
    "   - Text areas and comment boxes\n"
    "3. EXCLUDE ONLY these non-voice fields:\n"
    "   - Physical signature lines\n"
    "   - Drawing/sketch areas\n"
    "   - Barcodes or QR codes\n"
    "   - Pre-filled form numbers or office use only fields\n"
    "   - File upload buttons\n"
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
    "   - Most government/medical forms have 25-60+ fillable fields\n"
    "   - If you find fewer than 15 fields, you probably missed some - scan again\n"
    "   - Continue until you've processed every visible field on every page\n\n"
    "OUTPUT FORMAT - Return ONLY a valid JSON array. Each element must have:\n"
    '   - "field_name": descriptive snake_case identifier (e.g., "applicant_first_name", "mailing_street_address")\n'
    '   - "label": exact label text from the form (e.g., "First Name", "Street Address")\n'
    '   - "type": one of: text, date, ssn, phone, address, yes_no, number, email, checkbox, choice\n'
    '   - "prompt": conversational question as a friendly assistant would say it out loud\n'
    '   - "options": (REQUIRED for checkbox/choice types) array of all available options\n\n'
    "CONVERSATIONAL PROMPT EXAMPLES — use this tone:\n"
    "[\n"
    '  {"field_name":"applicant_first_name","label":"First Name","type":"text","prompt":"What\'s your first name?"},\n'
    '  {"field_name":"applicant_last_name","label":"Last Name","type":"text","prompt":"And your last name?"},\n'
    '  {"field_name":"date_of_birth","label":"Date of Birth","type":"date","prompt":"What\'s your date of birth?"},\n'
    '  {"field_name":"mailing_street","label":"Street Address","type":"text","prompt":"What\'s your current street address?"},\n'
    '  {"field_name":"mailing_city","label":"City","type":"text","prompt":"What city do you live in?"},\n'
    '  {"field_name":"mailing_state","label":"State","type":"text","prompt":"What state is that in?"},\n'
    '  {"field_name":"mailing_zip","label":"ZIP Code","type":"number","prompt":"What\'s your ZIP code?"},\n'
    '  {"field_name":"phone_number","label":"Phone Number","type":"phone","prompt":"What\'s the best phone number to reach you?"},\n'
    '  {"field_name":"ssn","label":"Social Security Number","type":"ssn","prompt":"Can you share your Social Security Number? Don\'t worry — it\'s kept completely private."},\n'
    '  {"field_name":"has_insurance","label":"Do you have insurance?","type":"yes_no","prompt":"Do you have any insurance coverage for the damaged property?"},\n'
    '  {"field_name":"disaster_type","label":"Type of Disaster","type":"choice","prompt":"What type of disaster affected you?","options":["Hurricane","Flood","Fire","Earthquake","Tornado","Other"]},\n'
    '  {"field_name":"assistance_needed","label":"Type of assistance needed","type":"checkbox","prompt":"What kinds of help are you looking for? You can mention as many as apply.","options":["Housing","Food","Medical","Transportation","Childcare"]}\n'
    "]\n\n"
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
                    "Be thorough: scan every page completely, do not skip fields, do not stop early. "
                    "Use contractions, empathetic phrasing, and plain language. Avoid bureaucratic wording. "
                    "Return ONLY a complete JSON array with ALL fields found."
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
    logger.debug(f"Raw VLM output (first 500 chars): {str(raw_content)[:500]}")

    # 4. Parse the JSON from the LLM output
    questions = _parse_questions_json(raw_content)

    logger.info(f"Successfully parsed {len(questions)} questions from VLM output")
    if len(questions) == 0:
        logger.warning("No questions were extracted! Check raw_content for issues.")
    elif len(questions) < 10:
        logger.warning(
            f"Only {len(questions)} fields extracted - this seems low for a {len(pages)}-page form. "
            "The model may have missed fields or stopped early."
        )
    elif len(questions) < 15 and len(pages) > 1:
        logger.warning(
            f"Only {len(questions)} fields for {len(pages)} pages - may be incomplete. "
            "Review raw_content to verify all fields were captured."
        )

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

    # Normalise and assign sequential IDs
    questions: list[dict[str, Any]] = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            logger.warning(f"Item {idx} is not a dict, skipping")
            continue

        # Validate required fields
        if not item.get("field_name") or not item.get("prompt"):
            logger.warning(f"Item {idx} missing required fields, using defaults")

        question = {
            "id": idx,
            "field_name": item.get("field_name", f"field_{idx}"),
            "label": item.get("label", ""),
            "type": item.get("type", "text"),
            "prompt": item.get("prompt", item.get("label", "")),
        }

        # Add options if present (for checkbox/choice types)
        if "options" in item and isinstance(item["options"], list):
            question["options"] = item["options"]

        questions.append(question)

    return questions
