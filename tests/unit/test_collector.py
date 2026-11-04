import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from tradinggpt_options.data.collector import KiteOptionsCollector
from tradinggpt_options.data.kite_adapter import KiteMarketDataAdapter
from tradinggpt_options.storage.database import Base
from tradinggpt_options.storage.tables import InstrumentSnapshot, QuoteSnapshot


class FakeRestClient:
    def __init__(self, *, include_second: bool = False) -> None:
        self.include_second = include_second

    def instruments(self, exchange: str | None = None) -> list[dict]:
        assert exchange == "NFO"
        rows = [{
            "instrument_token": 123,
            "exchange_token": 1,
            "tradingsymbol": "NIFTY26NOV25000CE",
            "name": "NIFTY",
            "last_price": 0,
            "expiry": "2026-11-26",
            "strike": 25000,
            "tick_size": 0.05,
            "lot_size": 65,
            "instrument_type": "CE",
            "segment": "NFO-OPT",
            "exchange": "NFO",
        }]
        if self.include_second:
            rows.append({
                "instrument_token": 124,
                "exchange_token": 2,
                "tradingsymbol": "NIFTY26NOV25000PE",
                "name": "NIFTY",
                "last_price": 0,
                "expiry": "2026-11-26",
                "strike": 25000,
                "tick_size": 0.05,
                "lot_size": 65,
                "instrument_type": "PE",
                "segment": "NFO-OPT",
                "exchange": "NFO",
            })
        return rows

    def quote(self, *instruments: str) -> dict:
        return {}


class FakeTicker:
    MODE_FULL = "full"

    def __init__(self) -> None:
        self.subscribed: list[int] = []
        self.unsubscribed: list[int] = []
        self.mode_calls: list[tuple[str, list[int]]] = []
        self.closed = False
        self.on_ticks = None
        self.on_connect = None
        self.on_close = None
        self.on_error = None
        self.on_reconnect = None
        self.on_noreconnect = None

    def subscribe(self, tokens: list[int]) -> None:
        self.subscribed = tokens

    def unsubscribe(self, tokens: list[int]) -> None:
        self.unsubscribed.extend(tokens)
        self.subscribed = [token for token in self.subscribed if token not in tokens]

    def set_mode(self, mode: str, tokens: list[int]) -> None:
        self.mode_calls.append((mode, tokens))

    def connect(self, threaded: bool = False) -> None:
        assert threaded
        self.on_connect(self, {})

    def close(self) -> None:
        self.closed = True
        self.on_close(self, 1000, "closed")


def setup_collector(
    *, include_second: bool = False
) -> tuple[KiteOptionsCollector, sessionmaker]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    adapter = KiteMarketDataAdapter(
        FakeRestClient(include_second=include_second),
        instrument_interval_seconds=0,
    )
    return KiteOptionsCollector(adapter=adapter, session_factory=factory), factory


def test_collector_archives_master_and_persists_websocket_ticks() -> None:
    collector, factory = setup_collector()
    contracts = collector.load_daily_instrument_master(
        underlyings={"NIFTY"},
        snapshot_date=date(2026, 11, 4),
    )
    assert len(contracts) == 1

    ticker = FakeTicker()
    subscribed = collector.start(ticker=ticker, contracts=contracts)
    assert subscribed == (123,)
    assert ticker.subscribed == [123]
    assert ticker.mode_calls == [("full", [123])]
    assert collector.status().state == "connected"

    tick_time = datetime.now(UTC)
    ticker.on_ticks(
        ticker,
        [{
            "instrument_token": 123,
            "last_price": 100.25,
            "volume_traded": 1200,
            "oi": 5500,
            "exchange_timestamp": tick_time,
            "depth": {
                "buy": [{"price": 100.2, "quantity": 65, "orders": 1}],
                "sell": [{"price": 100.3, "quantity": 65, "orders": 1}],
            },
        }],
    )

    status = collector.status()
    assert status.received_ticks == 1
    assert status.persisted_quotes == 1
    assert status.rejected_ticks == 0
    assert status.unknown_tokens == 0
    assert status.last_tick_at is not None

    with factory() as session:
        instrument = session.scalar(select(InstrumentSnapshot))
        quote = session.scalar(select(QuoteSnapshot))
        assert instrument is not None
        assert instrument.tradingsymbol == "NIFTY26NOV25000CE"
        assert quote is not None
        assert quote.last_price == Decimal("100.25")
        assert quote.best_bid == Decimal("100.2")
        assert quote.best_ask == Decimal("100.3")
        assert quote.volume == 1200
        assert quote.open_interest == 5500
        assert json.loads(quote.bid_depth_json) == [
            {"price": "100.2", "quantity": 65, "orders": 1}
        ]
        assert json.loads(quote.ask_depth_json) == [
            {"price": "100.3", "quantity": 65, "orders": 1}
        ]

    collector.stop()
    assert ticker.closed
    assert collector.status().state == "stopped"


def test_collector_persists_stale_flag_and_counts_unknown_tokens() -> None:
    collector, factory = setup_collector()
    contracts = collector.load_daily_instrument_master(
        underlyings={"NIFTY"},
        snapshot_date=date(2026, 11, 4),
    )
    ticker = FakeTicker()
    collector.start(ticker=ticker, contracts=contracts)
    old_time = datetime.now(UTC) - timedelta(minutes=2)
    ticker.on_ticks(
        ticker,
        [
            {
                "instrument_token": 123,
                "last_price": 100,
                "volume_traded": 100,
                "oi": 200,
                "exchange_timestamp": old_time,
                "depth": {
                    "buy": [{"price": 99.9, "quantity": 10, "orders": 1}],
                    "sell": [{"price": 100.1, "quantity": 10, "orders": 1}],
                },
            },
            {"instrument_token": 999, "last_price": 1},
        ],
    )
    status = collector.status()
    assert status.persisted_quotes == 1
    assert status.unknown_tokens == 1
    with factory() as session:
        quote = session.scalar(select(QuoteSnapshot))
        assert quote is not None
        assert "quote exceeds configured freshness threshold" in quote.quality_flags
    collector.stop()


def test_collector_rolls_near_atm_subscriptions_without_restarting_socket() -> None:
    collector, _factory = setup_collector(include_second=True)
    contracts = collector.load_daily_instrument_master(
        underlyings={"NIFTY"},
        snapshot_date=date(2026, 11, 4),
    )
    assert len(contracts) == 2

    ticker = FakeTicker()
    collector.start(ticker=ticker, contracts=(contracts[0],))
    assert ticker.subscribed == [123]

    updated = collector.update_contracts((contracts[1],))
    assert updated == (124,)
    assert ticker.unsubscribed == [123]
    assert ticker.subscribed == [124]
    assert collector.status().subscribed_count == 1

    # KiteTicker reconnect callback must resubscribe the latest window, not
    # the original token set.
    ticker.on_connect(ticker, {})
    assert ticker.subscribed == [124]
    collector.stop()
