from datetime import UTC, datetime
from decimal import Decimal

from tradinggpt_options.data.models import DepthLevel, OptionQuote, assess_quote_quality


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
