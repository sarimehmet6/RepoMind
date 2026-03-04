"""Architecture analysis using an LLM; designed for OpenAI API integration.

For real API: pass a llm_callable that reads OPENAI_API_KEY from the environment,
calls the OpenAI API with the given prompt and low temperature, and returns the
response text. Use the _SYSTEM_PROMPT and _build_prompt() for consistency.
"""

import json
from typing import Any, Callable

# Expected keys in the analyzer's JSON response.
ARCHITECTURE_SCORE = "architecture_score"
KEY_ISSUES = "key_issues"
IMPROVEMENT_PRIORITIES = "improvement_priorities"

DEFAULT_TEMPERATURE = 0.2

# System prompt for structured analysis.
_SYSTEM_PROMPT = """You are a software architecture reviewer. Analyze the given repository summary and respond with valid JSON only, no markdown or extra text.
The JSON must have exactly these keys:
- "architecture_score": integer from 0 to 100
- "key_issues": list of strings (concise issues)
- "improvement_priorities": list of strings (ordered by priority)"""


def _placeholder_llm_call(_prompt: str) -> str:
    """
    Placeholder for the LLM call. Replace with a real implementation that reads
    OPENAI_API_KEY from the environment and calls the OpenAI API.
    """
    return json.dumps({
        ARCHITECTURE_SCORE: 0,
        KEY_ISSUES: [],
        IMPROVEMENT_PRIORITIES: [],
    })


def _build_prompt(summary: str) -> str:
    """Build the user prompt from the repository summary."""
    return f"Repository summary:\n\n{summary}\n\nProvide the analysis as JSON only."


def _parse_analysis_response(raw: str) -> dict[str, Any]:
    """Parse and validate the LLM response into the expected structure."""
    data = json.loads(raw.strip())
    score = data.get(ARCHITECTURE_SCORE, 0)
    if not isinstance(score, int) or score < 0 or score > 100:
        score = 0
    return {
        ARCHITECTURE_SCORE: score,
        KEY_ISSUES: _ensure_list_of_str(data.get(KEY_ISSUES)),
        IMPROVEMENT_PRIORITIES: _ensure_list_of_str(data.get(IMPROVEMENT_PRIORITIES)),
    }


def _ensure_list_of_str(value: Any) -> list[str]:
    """Return a list of strings; coerce or default to []."""
    if isinstance(value, list):
        return [str(x) for x in value]
    return []


class ArchitectureAnalyzer:
    """
    Analyzes repository architecture from a summary string using an LLM.
    Uses a placeholder LLM call by default; inject a real call for API integration.
    """

    def __init__(
        self,
        summary: str,
        *,
        llm_callable: Callable[[str], str] | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self.summary = summary
        self.llm_callable = llm_callable or _placeholder_llm_call
        self.temperature = temperature

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM with the given prompt. Override or replace for real API."""
        return self.llm_callable(prompt)

    def analyze(self) -> dict[str, Any]:
        """
        Run architecture analysis and return structured result:
        architecture_score (0-100), key_issues, improvement_priorities.
        """
        prompt = _build_prompt(self.summary)
        raw = self._call_llm(prompt)
        return _parse_analysis_response(raw)
