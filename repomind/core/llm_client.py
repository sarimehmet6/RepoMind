
"""OpenAI client wrapper for structured JSON responses."""

import json
import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MODEL = "gpt-4o-mini"

_SYSTEM_MESSAGE = "You are a helpful assistant. Respond with valid JSON only, no markdown or extra text."


class LLMClientError(Exception):
    """Raised when the LLM client fails (missing key, API error, invalid JSON)."""


def _get_client():
    """Build OpenAI client from environment. Raises LLMClientError if key missing."""
    try:
        from openai import OpenAI
    except ImportError as err:
        raise LLMClientError("openai package not installed; pip install openai") from err

    api_key = os.environ.get(OPENAI_API_KEY_ENV)
    if not api_key or not api_key.strip():
        raise LLMClientError(
            f"Missing {OPENAI_API_KEY_ENV}. Set it in the environment or in a .env file."
        )
    return OpenAI(api_key=api_key.strip())


def generate_structured_response(prompt: str) -> dict:
    """
    Send the prompt to the OpenAI API and return the response as a parsed JSON dict.
    Uses low temperature and JSON mode. Raises LLMClientError on failure.
    """
    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
            temperature=DEFAULT_TEMPERATURE,
            response_format={"type": "json_object"},
        )
    except Exception as err:
        raise LLMClientError(f"OpenAI API request failed: {err}") from err

    content = response.choices[0].message.content
    if not content:
        raise LLMClientError("OpenAI API returned empty content.")

    try:
        return json.loads(content.strip())
    except json.JSONDecodeError as err:
        raise LLMClientError(f"OpenAI response was not valid JSON: {err}") from err
