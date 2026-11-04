from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from tradinggpt_options.data.models import DepthLevel, OptionContract, OptionQuote
from tradinggpt_options.options.chain_analytics import build_option_chain_view


def make_contract(
    symbol: str,
    token: int,
    option_type: str,
    strike: str = "25000",
) -> OptionContract:
    return OptionContract(
        exchange="NFO",
        tradingsymbol=symbol,
        instrument_token=token,
        underlying="NIFTY",
        expiry=date(2026, 11, 26),
        strike=Decimal(strike),
        option_type=option_type,  # type: ignore[arg-type]
        lot_size=65,
        tick_size=Decimal("0.05"),
    )


def make_quote(
    contract: OptionContract,
    now: datetime,
    bid: str,
    ask: str,
    *,
    timestamp: datetime | None = None,
) -> OptionQuote:
    return OptionQuote(
        exchange=contract.exchange,
        tradingsymbol=contract.tradingsymbol,
        instrument_token=contract.instrument_token,
        exchange_timestamp=timestamp or now,
        received_at=now,
        last_price=Decimal(ask),
        bid=(DepthLevel(Decimal(bid), 500),),
        ask=(DepthLevel(Decimal(ask), 500),),
        volume=1000,
        open_interest=20000,
    )


def test_builds_chain_with_mid_iv_greeks_and_atm_strike() -> None:
    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    call = make_contract("NIFTY26NOV25000CE", 123, "CE")
    put = make_contract("NIFTY26NOV25000PE", 124, "PE")
    quotes = {
        ("NFO", call.tradingsymbol): make_quote(call, now, "99.90", "100.10"),
        ("NFO", put.tradingsymbol): make_quote(put, now, "95.00", "95.20"),
    }
    view = build_option_chain_view(
        [call, put],
        quotes,
        underlying="nifty",
        expiry=date(2026, 11, 26),
        spot_price=Decimal("25000"),
        snapshot_at=now,
        risk_free_rate=0.065,
    )
    assert view.underlying == "NIFTY"
    assert view.atm_strike == Decimal("25000")
    assert len(view.strikes) == 1
    assert view.strikes[0].call is not None
    assert view.strikes[0].put is not None
    assert view.strikes[0].call.mid_price == Decimal("100.00")
    assert view.strikes[0].call.spread == Decimal("0.20")
    assert view.strikes[0].call.implied_volatility is not None
    assert view.strikes[0].call.greeks is not None
    assert view.strikes[0].put.implied_volatility is not None


def test_missing_or_stale_quote_suppresses_model_analytics() -> None:
    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    call = make_contract("NIFTY26NOV25000CE", 123, "CE")
    put = make_contract("NIFTY26NOV25000PE", 124, "PE")
    stale_quote = make_quote(
        call,
        now,
        "99.9",
        "100.1",
        timestamp=now - timedelta(minutes=2),
    )
    view = build_option_chain_view(
        [call, put],
        {("NFO", call.tradingsymbol): stale_quote},
        underlying="NIFTY",
        expiry=call.expiry,
        spot_price=Decimal("25000"),
        snapshot_at=now,
        risk_free_rate=0.065,
    )
    call_leg = view.strikes[0].call
    put_leg = view.strikes[0].put
    assert call_leg is not None and call_leg.implied_volatility is None
    assert any("freshness" in flag for flag in call_leg.quality_flags)
    assert put_leg is not None
    assert put_leg.quality_flags == ("missing_quote",)


def test_rejects_expired_chain_and_invalid_spot() -> None:
    now = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
    call = make_contract("NIFTY26NOV25000CE", 123, "CE")
    with pytest.raises(ValueError, match="expiry has passed"):
        build_option_chain_view(
            [call],
            {},
            underlying="NIFTY",
            expiry=call.expiry,
            spot_price=Decimal("25000"),
            snapshot_at=now,
            risk_free_rate=0.065,
        )
    with pytest.raises(ValueError, match="spot_price"):
        build_option_chain_view(
            [call],
            {},
            underlying="NIFTY",
            expiry=call.expiry,
            spot_price=Decimal("NaN"),
            snapshot_at=datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
            risk_free_rate=0.065,
        )
