from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradinggpt_options.data.models import DepthLevel, OptionQuote, assess_quote_quality


def make_quote(*, bid_quantity: int = 10, ask_quantity: int = 10, timestamp_offset: int = 0):
    now = datetime(2026, 11, 4, 4, 30, tzinfo=UTC)
    return OptionQuote(
        exchange="NFO",
        tradingsymbol="NIFTY26NOV25000CE",
        instrument_token=123,
        exchange_timestamp=now + timedelta(seconds=timestamp_offset),
        received_at=now,
        last_price=Decimal("100"),
        bid=(DepthLevel(Decimal("99.9"), bid_quantity),),
        ask=(DepthLevel(Decimal("100.1"), ask_quantity),),
        volume=100,
        open_interest=1000,
    ), now


def test_quote_quality_detects_stale_and_crossed_market() -> None:
    now = datetime(2026, 11, 4, 4, 30, tzinfo=UTC)
    quote = OptionQuote(
        exchange="NFO",
        tradingsymbol="NIFTY26NOV25000CE",
        instrument_token=123,
        exchange_timestamp=datetime(2026, 11, 4, 4, 0, tzinfo=UTC),
        received_at=now,
        last_price=Decimal("100"),
        bid=(DepthLevel(Decimal("101"), 10),),
        ask=(DepthLevel(Decimal("100"), 10),),
        volume=100,
        open_interest=1000,
    )
    result = assess_quote_quality(quote, now=now)
    assert result.is_stale
    assert result.is_crossed_market


def test_zero_quantity_top_of_book_is_not_executable() -> None:
    quote, now = make_quote(bid_quantity=0)
    result = assess_quote_quality(quote, now=now)
    assert result.missing_bid
    assert not result.missing_ask


def test_future_exchange_timestamp_beyond_clock_skew_is_rejected() -> None:
    quote, now = make_quote(timestamp_offset=10)
    result = assess_quote_quality(quote, now=now)
    assert result.is_stale
    assert any("future" in warning for warning in result.warnings)
