from datetime import UTC
from decimal import Decimal

from tradinggpt_options.data.quote_parser import parse_kite_quote, parse_kite_tick


def test_parses_kite_full_quote_depth() -> None:
    quote = parse_kite_quote(
        exchange="NFO",
        tradingsymbol="NIFTY26NOV25000CE",
        instrument_token=123,
        payload={
            "last_price": 101.5,
            "volume": 1500,
            "oi": 25000,
            "depth": {
                "buy": [{"price": 101.4, "quantity": 50, "orders": 2}],
                "sell": [{"price": 101.6, "quantity": 75, "orders": 3}],
            },
        },
    )
    assert quote.last_price == Decimal("101.5")
    assert quote.best_bid == Decimal("101.4")
    assert quote.best_ask == Decimal("101.6")
    assert quote.volume == 1500
    assert quote.open_interest == 25000
    assert quote.received_at.tzinfo == UTC


def test_invalid_optional_market_fields_are_not_fabricated() -> None:
    quote = parse_kite_quote(
        exchange="NFO",
        tradingsymbol="NIFTY26NOV25000CE",
        instrument_token=123,
        payload={"last_price": "NaN", "volume": "unknown", "oi": -5},
    )
    assert quote.last_price is None
    assert quote.volume is None
    assert quote.open_interest is None


def test_rejects_naive_local_receipt_timestamp() -> None:
    from datetime import datetime

    import pytest

    with pytest.raises(ValueError):
        parse_kite_quote(
            exchange="NFO",
            tradingsymbol="NIFTY26NOV25000CE",
            instrument_token=123,
            payload={},
            received_at=datetime(2026, 11, 4, 10, 0),
        )


def test_parses_kite_websocket_tick_field_names() -> None:
    from datetime import datetime

    timestamp = datetime(2026, 11, 4, 4, 30, tzinfo=UTC)
    quote = parse_kite_tick(
        exchange="NFO",
        tradingsymbol="NIFTY26NOV25000CE",
        instrument_token=123,
        payload={
            "last_price": 100.25,
            "volume_traded": 12345,
            "oi": 50000,
            "exchange_timestamp": timestamp,
            "depth": {
                "buy": [{"price": 100.2, "quantity": 65, "orders": 1}],
                "sell": [{"price": 100.3, "quantity": 130, "orders": 2}],
            },
        },
    )
    assert quote.exchange_timestamp == timestamp
    assert quote.volume == 12345
    assert quote.open_interest == 50000
    assert quote.best_bid == Decimal("100.2")
    assert quote.best_ask == Decimal("100.3")
