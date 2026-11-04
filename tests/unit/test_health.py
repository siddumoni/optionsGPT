from fastapi.testclient import TestClient

from tradinggpt_options.api.main import app

client = TestClient(app)


def test_health_reports_paper_only_mode() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["trading_mode"] == "PAPER"
    assert body["live_trading_enabled"] is False
