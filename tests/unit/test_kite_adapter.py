from datetime import UTC
from decimal import Decimal

import pytest

from tradinggpt_options.data.kite_adapter import (
    KiteMarketDataAdapter,
    RequestPacer,
    subscribe_full_market_data,
)


class FakeKiteClient:
    def __init__(self) -> None:
        self.quote_calls: list[tuple[str, ...]] = []
        self.instrument_calls: list[str | None] = []

    def instruments(self, exchange: str | None = None) -> list[dict]:
        self.instrument_calls.append(exchange)
        return [{
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

    def quote(self, *instruments: str) -> dict:
        self.quote_calls.append(instruments)
        return {
            "NFO:NIFTY26NOV25000CE": {
                "instrument_token": 123,
                "timestamp": None,
                "last_price": 100,
                "volume": 200,
                "oi": 3000,
                "depth": {
                    "buy": [{"price": 99.9, "quantity": 10, "orders": 1}],
                    "sell": [{"price": 100.1, "quantity": 15, "orders": 2}],
                },
            }
        }


class FakeTicker:
    MODE_FULL = "full"

    def __init__(self) -> None:
        self.subscriptions: list[int] = []
        self.modes: list[tuple[str, list[int]]] = []

    def subscribe(self, instrument_tokens: list[int]) -> None:
        self.subscriptions = instrument_tokens

    def set_mode(self, mode: str, instrument_tokens: list[int]) -> None:
        self.modes.append((mode, instrument_tokens))

    def connect(self, threaded: bool = False) -> None:
        return None

    def close(self) -> None:
        return None


def test_fetches_daily_nfo_master_as_csv() -> None:
    client = FakeKiteClient()
    adapter = KiteMarketDataAdapter(client, instrument_interval_seconds=0)
    csv_text = adapter.fetch_option_instrument_master()
    assert client.instrument_calls == ["NFO"]
    assert "NIFTY26NOV25000CE" in csv_text
    assert "NFO-OPT" in csv_text


def test_fetches_quote_and_reports_missing_symbols() -> None:
    client = FakeKiteClient()
    adapter = KiteMarketDataAdapter(client, quote_interval_seconds=0)
    snapshot = adapter.fetch_full_quotes([
        ("NFO", "NIFTY26NOV25000CE"),
        ("NFO", "NIFTY26NOV25000PE"),
    ])
    assert len(snapshot.quotes) == 1
    assert snapshot.quotes[0].best_bid == Decimal("99.9")
    assert snapshot.quotes[0].received_at.tzinfo == UTC
    assert snapshot.missing_symbols == ("NFO:NIFTY26NOV25000PE",)


def test_rejects_more_than_500_quotes_in_a_batch() -> None:
    client = FakeKiteClient()
    adapter = KiteMarketDataAdapter(client, quote_interval_seconds=0)
    instruments = [("NFO", f"TEST{i}") for i in range(501)]
    with pytest.raises(ValueError):
        adapter.fetch_full_quotes(instruments)
    assert client.quote_calls == []


def test_full_depth_websocket_subscription_limit_and_deduplication() -> None:
    ticker = FakeTicker()
    subscribed = subscribe_full_market_data(ticker, [1, 2, 2, 3])
    assert subscribed == (1, 2, 3)
    assert ticker.subscriptions == [1, 2, 3]
    assert ticker.modes == [("full", [1, 2, 3])]


def test_websocket_rejects_invalid_token_and_over_limit() -> None:
    ticker = FakeTicker()
    with pytest.raises(ValueError):
        subscribe_full_market_data(ticker, [0])
    with pytest.raises(ValueError):
        subscribe_full_market_data(ticker, range(1, 3002))


def test_request_pacer_rejects_negative_interval() -> None:
    with pytest.raises(ValueError):
        RequestPacer(interval_seconds=-0.1)


def test_websocket_session_tracks_connect_disconnect_and_tick_events() -> None:
    from tradinggpt_options.data.kite_adapter import KiteWebSocketSession

    ticker = FakeTicker()
    received: list[list[dict]] = []
    states: list[tuple[str, str | None]] = []
    session = KiteWebSocketSession(
        ticker,
        on_ticks=received.append,
        on_state=lambda state, detail: states.append((state, detail)),
    )
    ticker.on_connect(ticker, {})
    assert session.is_connected
    ticker.on_ticks(ticker, [{"instrument_token": 123, "last_price": 100}])
    assert received == [[{"instrument_token": 123, "last_price": 100}]]
    assert session.last_tick_at is not None
    ticker.on_close(ticker, 1006, "network disconnected")
    assert not session.is_connected
    assert states[0] == ("connected", None)
    assert states[-1] == ("disconnected", "1006: network disconnected")
