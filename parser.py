"""LLM-based natural language transaction parser.

Supports two backends selected via config.LLM_PROVIDER:
  • "google"  — Gemini API (Google AI Studio)     ← default
  • "openai"  — OpenAI API (gpt-4o-mini)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config import LLM_PROVIDER, OPENAI_API_KEY, GOOGLE_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a financial transaction parser. Extract the intent from the user's \
message and return ONLY a valid JSON object with these keys:
- "type": one of ["personal", "lend", "borrow", "settle", "query", "budget", "unknown"]
- "amount": number (or null)
- "friend": string name (or null)
- "category": string (or null)
- "description": string (or null)
- "budget_amount": number (or null) — only for "budget" type

Rules:
- "spent/paid/bought" with no person = "personal"
- "gave [name]" or "[name] owes me" = "lend"
- "[name] gave me" or "I owe [name]" = "borrow"
- "[name] paid me back" or "settle with [name]" = "settle"
- "how much does [name] owe" or "show balance" or "owed" or "owes" = "query"
- "set budget" = "budget"
- If unclear, use "unknown".

Return ONLY the JSON object, no extra text.
"""

UNKNOWN_RESULT: dict[str, Any] = {
    "type": "unknown", "amount": None, "friend": None,
    "category": None, "description": None, "budget_amount": None,
}


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Strip markdown fences and parse JSON from an LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    try:
        parsed: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return None
    for key in ("type", "amount", "friend", "category", "description"):
        parsed.setdefault(key, None)
    parsed.setdefault("budget_amount", None)
    return parsed


# ===================================================================
# Google Gemini backend
# ===================================================================

async def _parse_with_gemini(user_input: str) -> dict[str, Any]:
    from google import genai

    client = genai.Client(api_key=GOOGLE_API_KEY)
    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_input,
        config=genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.0,
            max_output_tokens=256,
        ),
    )
    raw = response.text.strip()
    result = _extract_json(raw)
    if result is None:
        logger.warning("Gemini returned non-JSON: %s", raw[:200])
        return UNKNOWN_RESULT
    return result


# ===================================================================
# OpenAI backend
# ===================================================================

async def _parse_with_openai(user_input: str) -> dict[str, Any]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        temperature=0.0,
        max_tokens=256,
    )
    raw = response.choices[0].message.content.strip()
    result = _extract_json(raw)
    if result is None:
        logger.warning("OpenAI returned non-JSON: %s", raw[:200])
        return UNKNOWN_RESULT
    return result


# ===================================================================
# Public entry point
# ===================================================================

async def parse_message(user_input: str) -> dict[str, Any]:
    """Send user message to the configured LLM and return parsed intent.

    Returns a dict with keys: type, amount, friend, category, description,
    budget_amount.  If parsing fails, returns {"type": "unknown", ...}.
    """
    try:
        if LLM_PROVIDER == "openai":
            if not OPENAI_API_KEY:
                logger.error("LLM_PROVIDER=openai but OPENAI_API_KEY is empty")
                return UNKNOWN_RESULT
            return await _parse_with_openai(user_input)

        # Default: Google Gemini
        if not GOOGLE_API_KEY:
            logger.error("LLM_PROVIDER=google but GOOGLE_API_KEY is empty")
            return UNKNOWN_RESULT
        return await _parse_with_gemini(user_input)

    except Exception as e:
        logger.error("LLM parsing failed: %s — %s", type(e).__name__, e)
        return UNKNOWN_RESULT
