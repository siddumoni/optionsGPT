from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from tradinggpt_options.data.models import DepthLevel, MarketCandle, OptionContract, OptionQuote
from tradinggpt_options.options.chain_analytics import build_option_chain_view
from tradinggpt_options.research.baseline import (
    BaselineStrategyConfig,
    analyze_baseline,
)


def make_candles(now: datetime, count: int = 30) -> list[MarketCandle]:
    candles: list[MarketCandle] = []
    close = Decimal("24970")
    increments = (Decimal("2"), Decimal("1"), Decimal("-2"))
    for index in range(count):
        close += increments[index % len(increments)]
        timestamp = now - timedelta(minutes=5 * (count - index))
        candles.append(
            MarketCandle(
                exchange="NSE",
                tradingsymbol="NIFTY 50",
                instrument_token=256265,
                interval="5minute",
                timestamp=timestamp,
                open=close - Decimal("0.5"),
                high=close + Decimal("2"),
                low=close - Decimal("2"),
                close=close,
                volume=1200 if index == count - 1 else 1000,
                open_interest=None,
            )
        )
    return candles


def make_chain(now: datetime):
    expiry = date(2026, 11, 26)
    call = OptionContract(
        exchange="NFO",
        tradingsymbol="NIFTY26NOV25000CE",
        instrument_token=123,
        underlying="NIFTY",
        expiry=expiry,
        strike=Decimal("25000"),
        option_type="CE",
        lot_size=65,
        tick_size=Decimal("0.05"),
    )
    put = OptionContract(
        exchange="NFO",
        tradingsymbol="NIFTY26NOV25000PE",
        instrument_token=124,
        underlying="NIFTY",
        expiry=expiry,
        strike=Decimal("25000"),
        option_type="PE",
        lot_size=65,
        tick_size=Decimal("0.05"),
    )
    quotes = {
        ("NFO", call.tradingsymbol): OptionQuote(
            exchange="NFO",
            tradingsymbol=call.tradingsymbol,
            instrument_token=123,
            exchange_timestamp=now,
            received_at=now,
            last_price=Decimal("150"),
            bid=(DepthLevel(Decimal("149.9"), 1000),),
            ask=(DepthLevel(Decimal("150.1"), 1000),),
            volume=1000,
            open_interest=20000,
        ),
        ("NFO", put.tradingsymbol): OptionQuote(
            exchange="NFO",
            tradingsymbol=put.tradingsymbol,
            instrument_token=124,
            exchange_timestamp=now,
            received_at=now,
            last_price=Decimal("140"),
            bid=(DepthLevel(Decimal("139.9"), 1000),),
            ask=(DepthLevel(Decimal("140.1"), 1000),),
            volume=1000,
            open_interest=20000,
        ),
    }
    spot = Decimal("24980")
    return build_option_chain_view(
        [call, put],
        quotes,
        underlying="NIFTY",
        expiry=expiry,
        spot_price=spot,
        snapshot_at=now,
        risk_free_rate=0.065,
    )


def test_baseline_emits_explainable_call_candidate_not_probability() -> None:
    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    candles = make_candles(now)
    chain = make_chain(now)
    result = analyze_baseline(
        candles,
        chain,
        now=now,
        config=BaselineStrategyConfig(minimum_confidence_score=50),
    )
    assert result.decision.direction == "CE"
    assert result.decision.estimated_win_probability is None
    assert result.decision.confidence_score is not None
    assert result.candidate is not None
    assert result.candidate.contract.option_type == "CE"
    assert any("EMA9" in reason for reason in result.decision.rationale)
    assert any("not a calibrated" in warning for warning in result.warnings)


def test_baseline_returns_no_trade_for_stale_or_insufficient_data() -> None:
    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    chain = make_chain(now)
    short_history = make_candles(now, count=20)
    insufficient = analyze_baseline(short_history, chain, now=now)
    assert insufficient.decision.direction == "NO_TRADE"

    stale_candles = make_candles(now - timedelta(minutes=30))
    stale = analyze_baseline(stale_candles, chain, now=now)
    assert stale.decision.direction == "NO_TRADE"
    assert any("stale" in item for item in stale.decision.rationale)


def test_baseline_returns_no_trade_when_option_liquidity_filters_fail() -> None:
    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    candles = make_candles(now)
    chain = make_chain(now)
    # Use a zero-volume configuration threshold that exceeds the quote's actual volume.
    result = analyze_baseline(
        candles,
        chain,
        now=now,
        config=BaselineStrategyConfig(
            minimum_confidence_score=50,
            minimum_option_volume=5000,
        ),
    )
    assert result.decision.direction == "NO_TRADE"
    assert result.candidate is None
