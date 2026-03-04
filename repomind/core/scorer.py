"""Deterministic score adjustments for architecture analysis."""

PENALTY_CIRCULAR_ONE = 15
PENALTY_CIRCULAR_MULTIPLE = 25
PENALTY_GROWTH_RISK_2 = 5   # growth_risk_score >= 2
PENALTY_GROWTH_RISK_3 = 10  # growth_risk_score >= 3
PENALTY_COUPLING_MODERATE = 5   # coupling_risk_level == "moderate"
PENALTY_COUPLING_HIGH = 10      # coupling_risk_level == "high"
MIN_SCORE = 0
MAX_SCORE = 100


class Scorer:
    """
    Applies deterministic penalties to an AI architecture score.
    Kept separate from AI logic; operates on raw score and scan-derived data.
    """

    def __init__(
        self,
        ai_score: int,
        circular_dependencies: list[list[str]] | None = None,
        growth_risk_score: int = 0,
        coupling_risk_level: str | None = None,
    ) -> None:
        self.ai_score = ai_score
        self.circular_dependencies = circular_dependencies or []
        self.growth_risk_score = max(0, min(4, growth_risk_score))
        normalized = (coupling_risk_level or "low").lower()
        if normalized not in ("low", "moderate", "high"):
            normalized = "low"
        self.coupling_risk_level = normalized

    def _penalty(self) -> int:
        """Compute total penalty from circular deps, growth risk, and coupling risk."""
        # 1) Circular dependency penalties.
        n_cycles = len(self.circular_dependencies)
        if n_cycles == 0:
            circular = 0
        elif n_cycles == 1:
            circular = PENALTY_CIRCULAR_ONE
        else:
            circular = PENALTY_CIRCULAR_MULTIPLE

        # 2) Growth risk penalties.
        growth = 0
        if self.growth_risk_score >= 2:
            growth += PENALTY_GROWTH_RISK_2
        if self.growth_risk_score >= 3:
            growth += PENALTY_GROWTH_RISK_3

        # 3) Coupling risk penalties.
        coupling = 0
        if self.coupling_risk_level == "moderate":
            coupling += PENALTY_COUPLING_MODERATE
        elif self.coupling_risk_level == "high":
            coupling += PENALTY_COUPLING_HIGH

        return circular + growth + coupling

    def adjusted_score(self) -> int:
        """Return score after penalties, clamped to [0, 100]."""
        penalty = self._penalty()
        raw = self.ai_score - penalty
        return max(MIN_SCORE, min(MAX_SCORE, raw))
