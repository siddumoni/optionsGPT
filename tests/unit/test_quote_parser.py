from datetime import UTC
from decimal import Decimal

from tradinggpt_options.data.quote_parser import parse_kite_quote


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
