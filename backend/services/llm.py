"""
LLM service — Qwen2.5-VL-3B via AMD-hosted vLLM endpoint.

Provides a general-purpose chat completion interface and
a high-level PDF→VLM form-analysis pipeline.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, status

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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "LLM request failed", "upstream": err},
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
    "You are a comprehensive form-analysis assistant. You will receive one or more images "
    "of pages from a PDF form.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "1. CAREFULLY scan EVERY page and identify ALL voice-fillable fields - do not skip any fields.\n"
    "2. INCLUDE these field types:\n"
    "   - Text inputs (names, addresses, descriptions)\n"
    "   - Date fields\n"
    "   - Number fields (phone, SSN, amount, quantity)\n"
    "   - Email addresses\n"
    "   - Yes/No questions\n"
    "   - Checkboxes (convert to yes/no or multiple choice questions)\n"
    "   - Radio buttons (convert to single-choice questions)\n"
    "   - Dropdown selections (convert to questions with options)\n"
    "3. EXCLUDE these field types that cannot be filled by voice:\n"
    "   - Signature fields (physical signatures)\n"
    "   - Drawing/sketch areas\n"
    "   - Barcodes or QR codes\n"
    "   - Pre-filled administrative fields (form numbers, office use only)\n"
    "   - File upload fields\n"
    "4. For checkboxes and multi-select fields:\n"
    "   - If it's a single checkbox (yes/no), use type 'yes_no'\n"
    "   - If it's multiple checkboxes (select all that apply), use type 'checkbox' and list options in prompt\n"
    "   - If it's radio buttons (select one), use type 'choice' and list options in prompt\n"
    "5. For EACH field, create a simple, friendly question in plain language (avoid jargon).\n"
    "6. Be THOROUGH - forms typically have 15-40+ voice-fillable fields.\n\n"
    "Return ONLY a valid JSON array. Each element must have:\n"
    '   - "field_name": a short snake_case identifier (e.g., "applicant_first_name")\n'
    '   - "label": the exact label/text from the form (e.g., "First Name")\n'
    '   - "type": one of: text, date, ssn, phone, address, yes_no, number, email, checkbox, choice\n'
    '   - "prompt": a friendly question in easy language\n'
    '   - "options": (optional) for checkbox/choice types, array of available options\n\n'
    "EXAMPLE OUTPUT:\n"
    "[\n"
    '  {"field_name":"applicant_first_name","label":"First Name","type":"text","prompt":"What is your first name?"},\n'
    '  {"field_name":"has_insurance","label":"Do you have insurance?","type":"yes_no","prompt":"Do you have insurance coverage?"},\n'
    '  {"field_name":"disaster_type","label":"Type of Disaster","type":"choice","prompt":"What type of disaster affected you?","options":["Hurricane","Flood","Fire","Earthquake","Other"]},\n'
    '  {"field_name":"assistance_needed","label":"Type of assistance needed","type":"checkbox","prompt":"What types of assistance do you need? You can select multiple.","options":["Housing","Food","Medical","Transportation"]}\n'
    "]\n\n"
    "Return ONLY the complete JSON array with ALL voice-fillable fields — no markdown fences, no explanation, no truncation.\n"
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
    # 1. Convert PDF pages to images (higher DPI for better field detection)
    pages = pdf_to_images(pdf_path, dpi=200, fmt="png")
    if not pages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF produced no pages — is the file valid?",
        )

    # 2. Base64-encode each page image
    images_b64: list[tuple[str, str]] = []
    for page in pages:
        img_bytes = page["path"].read_bytes()
        b64 = base64.b64encode(img_bytes).decode("ascii")
        images_b64.append((b64, "image/png"))

    # 3. Build multi-image VLM request
    user_msg = build_multi_image_message(images_b64, text=FORM_ANALYSIS_PROMPT)

    response = await chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert form-analysis assistant. Your task is to meticulously "
                    "identify EVERY SINGLE fillable field across all pages of the form. "
                    "Be comprehensive and thorough - do not skip any fields. "
                    "Return structured JSON only with all fields found."
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

    logger.info(
        f"PDF form analysis complete: {len(pages)} pages analyzed, "
        f"{usage.get('total_tokens', 0)} tokens used"
    )
    logger.debug(f"Raw VLM output (first 500 chars): {raw_content[:500]}")

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
