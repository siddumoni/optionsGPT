from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tradinggpt_options.api.main import create_app
from tradinggpt_options.config.settings import Settings
from tradinggpt_options.storage.database import build_engine, build_session_factory, create_schema
from tradinggpt_options.storage.tables import StrategyDecisionSnapshot


def test_research_decision_journal_returns_evidence_and_never_invents_probability(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'research.sqlite').as_posix()}"
    app = create_app(Settings(database_url=database_url))
    with TestClient(app) as client:
        assert client.get("/api/v1/research/decisions").json() == []
        assert client.get("/api/v1/research/decisions?limit=0").status_code == 422

    engine = build_engine(database_url)
    create_schema(engine)
    factory = build_session_factory(engine)
    with Session(factory.kw["bind"]) as session:
        session.add(
            StrategyDecisionSnapshot(
                id="decision-test-1",
                snapshot_at=datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
                underlying="NIFTY",
                expiry=date(2026, 11, 26),
                decision="CE",
                confidence_score=Decimal("78.50"),
                estimated_win_probability=None,
                model_version="baseline-ema-vwap-rsi-v1",
                spot_price=Decimal("25000"),
                risk_free_rate=Decimal("0.065"),
                candle_source="NIFTY26NOVFUT",
                candle_count=30,
                candidate_symbol="NIFTY26NOV25000CE",
                candidate_strike=Decimal("25000"),
                candidate_option_type="CE",
                candidate_mid=Decimal("150"),
                candidate_iv=Decimal("0.043"),
                candidate_delta=Decimal("0.61"),
                rationale_json='["EMA9 is above EMA21"]',
                opposing_evidence_json="[]",
                warnings_json='["score is not a probability"]',
            )
        )
        session.commit()
    engine.dispose()

    with TestClient(app) as client:
        response = client.get("/api/v1/research/decisions?limit=10")
        assert response.status_code == 200
        decisions = response.json()
        assert len(decisions) == 1
        decision = decisions[0]
        assert decision["decision"] == "CE"
        assert decision["confidence_score"] == 78.5
        assert decision["estimated_win_probability"] is None
        assert decision["candidate_symbol"] == "NIFTY26NOV25000CE"
        assert decision["rationale"] == ["EMA9 is above EMA21"]
        assert decision["snapshot_at"].endswith("+00:00")
