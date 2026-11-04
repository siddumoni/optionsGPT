from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tradinggpt_options.api.main import create_app
from tradinggpt_options.config.settings import Settings
from tradinggpt_options.data.models import DepthLevel, OptionContract, OptionQuote
from tradinggpt_options.execution.paper_broker import PaperBroker, PaperExecutionConfig
from tradinggpt_options.storage.database import build_engine, build_session_factory, create_schema


def test_paper_account_and_trade_read_endpoints(tmp_path) -> None:
    db_file = tmp_path / "paper-api.sqlite"
    database_url = f"sqlite:///{db_file.as_posix()}"
    settings = Settings(database_url=database_url)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/paper/account")
        assert response.status_code == 404
        assert client.get("/api/v1/paper/trades").json() == []

    engine = build_engine(database_url)
    create_schema(engine)
    factory = build_session_factory(engine)
    with Session(factory.kw["bind"]) as session:
        broker = PaperBroker(
            session,
            account_name="default",
            config=PaperExecutionConfig(initial_capital=Decimal("100000")),
        )
        contract = OptionContract(
            exchange="NFO",
            tradingsymbol="NIFTY26NOV25000CE",
            instrument_token=123,
            underlying="NIFTY",
            expiry=date(2026, 11, 26),
            strike=Decimal("25000"),
            option_type="CE",
            lot_size=65,
            tick_size=Decimal("0.05"),
        )
        now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
        quote = OptionQuote(
            exchange="NFO",
            tradingsymbol=contract.tradingsymbol,
            instrument_token=123,
            exchange_timestamp=now,
            received_at=now,
            last_price=Decimal("100"),
            bid=(DepthLevel(Decimal("99.9"), 100),),
            ask=(DepthLevel(Decimal("100.1"), 100),),
            volume=100,
            open_interest=1000,
        )
        broker.buy_to_open(contract=contract, quote=quote, lots=1, now=now)
    engine.dispose()

    with TestClient(app) as client:
        account = client.get("/api/v1/paper/account")
        assert account.status_code == 200
        assert account.json()["mode"] == "PAPER"
        assert account.json()["open_positions"] == 1
        assert account.json()["live_trading_enabled"] is False
        trades = client.get("/api/v1/paper/trades?status=open")
        assert trades.status_code == 200
        assert len(trades.json()) == 1
        assert trades.json()[0]["option_type"] == "CE"
