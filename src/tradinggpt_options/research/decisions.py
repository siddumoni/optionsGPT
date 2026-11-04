from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TradeDecision:
    underlying: str
    direction: Literal["CE", "PE", "NO_TRADE"]
    confidence_score: float | None
    estimated_win_probability: float | None
    rationale: tuple[str, ...]
    opposing_evidence: tuple[str, ...]
    model_version: str

    def __post_init__(self) -> None:
        if self.confidence_score is not None and not 0 <= self.confidence_score <= 100:
            raise ValueError("confidence_score must be between 0 and 100")
        probability = self.estimated_win_probability
        if probability is not None and not 0 <= probability <= 1:
            raise ValueError("estimated_win_probability must be between 0 and 1")
