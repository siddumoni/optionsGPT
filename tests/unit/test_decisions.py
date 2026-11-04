import pytest

from tradinggpt_options.research.decisions import TradeDecision


def test_confidence_must_be_in_range() -> None:
    with pytest.raises(ValueError):
        TradeDecision(
            underlying="NIFTY",
            direction="NO_TRADE",
            confidence_score=101,
            estimated_win_probability=None,
            rationale=("No validated setup",),
            opposing_evidence=(),
            model_version="baseline-0.1",
        )
