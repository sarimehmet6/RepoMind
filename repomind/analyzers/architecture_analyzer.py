"""Architecture analysis using the LLM client; expects strict JSON schema."""

from typing import Any

from repomind.core.llm_client import LLMClientError, generate_structured_response

ARCHITECTURE_SCORE = "architecture_score"
KEY_ISSUES = "key_issues"
IMPROVEMENT_PRIORITIES = "improvement_priorities"

_SCHEMA_DESC = (
    '{"architecture_score": <int 0-100>, "key_issues": [<string>], '
    '"improvement_priorities": [<string>]}'
)

_OVER_CENTRALIZATION_THRESHOLD = 30

_SYSTEM_INSTRUCTION = (
    "You are a software architecture reviewer. "
    "Respond with valid JSON only—no markdown, no code fences, no extra text. "
    f"Use exactly this schema: {_SCHEMA_DESC}. "
    "Base your analysis on the repository summary. Consider the project size classification "
    "(Micro / Small / Medium / Large) in the summary. "
    "For Micro projects (<3 source files): do not penalize single-file or few-file structure; "
    "focus on code clarity and growth readiness instead of modularity. "
    "For Small and larger projects, apply standard modularity and structure criteria. "
    "Reason using percentages (e.g. "
    "'Largest file share of total lines', 'Most function-heavy file share of total functions') "
    "as well as absolute counts—percentages reveal concentration risk. "
    f"Treat over-centralization as a key_issue when any file has more than {_OVER_CENTRALIZATION_THRESHOLD}% "
    f"of total lines or more than {_OVER_CENTRALIZATION_THRESHOLD}% of total functions; flag it explicitly. "
    "If the summary reports 'Circular dependencies detected', treat this as a major architectural risk: "
    "circular dependencies reduce modularity and scalability—add a key_issue and an improvement_priority for breaking them. "
    "Consider: (1) Potential god files—oversized or over-responsibility modules; "
    "(2) Over-centralization—logic or dependencies concentrated in few places; "
    "(3) Separation of concerns—mixing of responsibilities or unclear boundaries; "
    "(4) Scalability risks—structure that will not scale as the codebase grows. "
    "Use folder-level coupling metrics (folder_coupling, cross-folder dependency ratio, coupling_risk_level) to "
    "evaluate modular boundaries, domain separation, and the risk of cross-feature entanglement. Distinguish clearly "
    "between healthy modular cross-communication (well-defined interfaces between folders/domains) and harmful tight "
    "coupling (many broad or cyclic cross-folder dependencies). If coupling_risk_level is 'high', treat this as a major "
    "architectural concern and reflect it in architecture_score, key_issues, and improvement_priorities. "
    "Evaluate growth and scalability risk using the summary's Growth risk indicators and growth_risk_score (0–4). "
    "Distinguish clearly between: (a) Current structural health—how the codebase is structured today, cohesion, "
    "modularity, and existing hotspots; (b) Future scalability risk—how well the structure will hold as the codebase "
    "grows, concentration of responsibility, and single points of failure. Include key_issues and improvement_priorities "
    "that address both dimensions; phrase so it is clear which relate to current health vs future scalability where relevant. "
    "Be analytical and specific: cite files or metrics from the summary where relevant, while keeping the JSON response "
    "concise but deep in reasoning. "
    "Avoid generic advice; every key_issue and improvement_priority must be concrete and tied to the data."
)

_USER_PREFIX = "Repository summary (use file complexity and size data for your analysis):\n\n"


class ArchitectureAnalysisError(Exception):
    """Raised when the model response does not match the expected schema."""


def _build_prompt(summary: str) -> str:
    """Construct a single user prompt: instruction + schema + summary."""
    return f"{_SYSTEM_INSTRUCTION}\n\n{_USER_PREFIX}{summary}"


def _validate_schema(data: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and normalize the response to the expected schema.
    Raises ArchitectureAnalysisError if invalid.
    """
    if not isinstance(data, dict):
        raise ArchitectureAnalysisError(f"Expected a JSON object, got {type(data).__name__}")

    # architecture_score: integer 0-100
    raw_score = data.get(ARCHITECTURE_SCORE)
    if raw_score is None:
        raise ArchitectureAnalysisError(f"Missing required key: {ARCHITECTURE_SCORE}")
    if not isinstance(raw_score, int):
        raise ArchitectureAnalysisError(
            f"{ARCHITECTURE_SCORE} must be an integer, got {type(raw_score).__name__}"
        )
    if not 0 <= raw_score <= 100:
        raise ArchitectureAnalysisError(
            f"{ARCHITECTURE_SCORE} must be between 0 and 100, got {raw_score}"
        )

    # key_issues: list of strings
    raw_issues = data.get(KEY_ISSUES)
    if raw_issues is None:
        raise ArchitectureAnalysisError(f"Missing required key: {KEY_ISSUES}")
    if not isinstance(raw_issues, list):
        raise ArchitectureAnalysisError(
            f"{KEY_ISSUES} must be an array, got {type(raw_issues).__name__}"
        )
    key_issues = [str(x) for x in raw_issues]

    # improvement_priorities: list of strings
    raw_priorities = data.get(IMPROVEMENT_PRIORITIES)
    if raw_priorities is None:
        raise ArchitectureAnalysisError(f"Missing required key: {IMPROVEMENT_PRIORITIES}")
    if not isinstance(raw_priorities, list):
        raise ArchitectureAnalysisError(
            f"{IMPROVEMENT_PRIORITIES} must be an array, got {type(raw_priorities).__name__}"
        )
    improvement_priorities = [str(x) for x in raw_priorities]

    return {
        ARCHITECTURE_SCORE: raw_score,
        KEY_ISSUES: key_issues,
        IMPROVEMENT_PRIORITIES: improvement_priorities,
    }


class ArchitectureAnalyzer:
    """
    Analyzes repository architecture from a summary string using the LLM client.
    Returns validated JSON with architecture_score, key_issues, improvement_priorities.
    """

    def __init__(self, summary: str) -> None:
        self.summary = summary

    def analyze(self) -> dict[str, Any]:
        """
        Run architecture analysis and return validated result.
        Raises LLMClientError on API or JSON parse failure, ArchitectureAnalysisError on schema violation.
        """
        prompt = _build_prompt(self.summary)
        try:
            data = generate_structured_response(prompt)
        except LLMClientError:
            raise
        return _validate_schema(data)
