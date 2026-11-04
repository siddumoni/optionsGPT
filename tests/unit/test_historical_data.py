from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tradinggpt_options.data.kite_adapter import KiteMarketDataAdapter
from tradinggpt_options.data.models import MarketCandle
from tradinggpt_options.storage.database import Base
from tradinggpt_options.storage.repository import MarketDataRepository
from tradinggpt_options.storage.tables import CandleSnapshot


class FakeHistoricalClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple] = []

    def instruments(self, exchange: str | None = None) -> list[dict]:
        return []

    def quote(self, *instruments: str) -> dict:
        return {}

    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict]:
        self.calls.append((instrument_token, from_date, to_date, interval, continuous, oi))
        return self.rows


def make_row(timestamp: datetime, close: str = "101") -> dict:
    return {
        "date": timestamp,
        "open": "100",
        "high": "102",
        "low": "99",
        "close": close,
        "volume": 1234,
        "oi": 9876,
    }


def test_fetches_and_normalizes_historical_candles() -> None:
    start = datetime(2026, 11, 4, 9, 15, tzinfo=UTC)
    end = start + timedelta(minutes=10)
    client = FakeHistoricalClient(
        [make_row(end, "101.5"), make_row(start, "100.5")]
    )
    adapter = KiteMarketDataAdapter(client, historical_interval_seconds=0)
    candles = adapter.fetch_historical_candles(
        exchange="nfo",
        tradingsymbol="nifty26nov25000ce",
        instrument_token=123,
        from_date=start,
        to_date=end,
        interval="5minute",
    )
    assert len(candles) == 2
    assert candles[0].timestamp == start
    assert candles[0].open == Decimal("100")
    assert candles[0].close == Decimal("100.5")
    assert candles[0].open_interest == 9876
    assert client.calls == [(123, start, end, "5minute", False, True)]


def test_rejects_invalid_interval_naive_dates_and_duplicate_candles() -> None:
    start = datetime(2026, 11, 4, 9, 15, tzinfo=UTC)
    end = start + timedelta(minutes=5)
    adapter = KiteMarketDataAdapter(
        FakeHistoricalClient([make_row(start)]),
        historical_interval_seconds=0,
    )
    with pytest.raises(ValueError, match="unsupported"):
        adapter.fetch_historical_candles(
            exchange="NSE",
            tradingsymbol="NIFTY 50",
            instrument_token=123,
            from_date=start,
            to_date=end,
            interval="2minute",
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        adapter.fetch_historical_candles(
            exchange="NSE",
            tradingsymbol="NIFTY 50",
            instrument_token=123,
            from_date=start.replace(tzinfo=None),
            to_date=end,
            interval="5minute",
        )

    duplicate_adapter = KiteMarketDataAdapter(
        FakeHistoricalClient([make_row(start), make_row(start)]),
        historical_interval_seconds=0,
    )
    with pytest.raises(ValueError, match="duplicate"):
        duplicate_adapter.fetch_historical_candles(
            exchange="NSE",
            tradingsymbol="NIFTY 50",
            instrument_token=123,
            from_date=start,
            to_date=end,
            interval="5minute",
        )


def test_rejects_malformed_ohlc_and_persists_candles_idempotently() -> None:
    start = datetime(2026, 11, 4, 9, 15, tzinfo=UTC)
    end = start + timedelta(minutes=5)
    bad_row = make_row(start)
    bad_row["high"] = "98"
    adapter = KiteMarketDataAdapter(
        FakeHistoricalClient([bad_row]),
        historical_interval_seconds=0,
    )
    with pytest.raises(ValueError, match="candle high"):
        adapter.fetch_historical_candles(
            exchange="NSE",
            tradingsymbol="NIFTY 50",
            instrument_token=123,
            from_date=start,
            to_date=end,
            interval="5minute",
        )

    candle = MarketCandle(
        exchange="NSE",
        tradingsymbol="NIFTY 50",
        instrument_token=256265,
        interval="5minute",
        timestamp=start,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=500,
        open_interest=None,
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = MarketDataRepository(session)
        assert repository.save_candles((candle,)) == 1
        assert repository.save_candles((candle,)) == 0
        stored = session.scalar(select(CandleSnapshot))
        assert stored is not None
        assert stored.tradingsymbol == "NIFTY 50"
        assert stored.close == Decimal("101.0000")
    engine.dispose()
