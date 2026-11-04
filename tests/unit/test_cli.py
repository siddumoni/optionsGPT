import pytest

from tradinggpt_options.cli import (
    _completed_intraday_candles,
    _option_selection_date,
    _parse_aware_datetime,
    _parse_spot_instrument_mappings,
)


def test_parses_explicit_index_and_equity_spot_mappings() -> None:
    result = _parse_spot_instrument_mappings(
        "NIFTY=NSE:NIFTY 50;BANKNIFTY=NSE:NIFTY BANK;RELIANCE=NSE:RELIANCE"
    )
    assert result == {
        "NIFTY": ("NSE", "NIFTY 50"),
        "BANKNIFTY": ("NSE", "NIFTY BANK"),
        "RELIANCE": ("NSE", "RELIANCE"),
    }


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "NIFTY",
        "NIFTY=NIFTY 50",
        "NIFTY=NSE:",
        "NIFTY=NSE:NIFTY;NIFTY=NSE:NIFTY 50",
    ],
)
def test_rejects_invalid_spot_instrument_mappings(raw: str) -> None:
    with pytest.raises(ValueError):
        _parse_spot_instrument_mappings(raw)


def test_parses_timezone_aware_cli_datetime() -> None:
    value = _parse_aware_datetime("2026-11-04T09:15:00+05:30")
    assert value.isoformat() == "2026-11-04T09:15:00+05:30"


@pytest.mark.parametrize("raw", ["2026-11-04T09:15:00", "not-a-date"])
def test_rejects_cli_datetime_without_valid_timezone(raw: str) -> None:
    from argparse import ArgumentTypeError

    with pytest.raises(ArgumentTypeError):
        _parse_aware_datetime(raw)


def test_expiry_selection_rolls_forward_after_nse_market_close() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    market_tz = ZoneInfo("Asia/Kolkata")
    before_close = datetime(2026, 11, 4, 15, 29, tzinfo=market_tz)
    at_close = datetime(2026, 11, 4, 15, 30, tzinfo=market_tz)
    assert _option_selection_date(before_close).isoformat() == "2026-11-04"
    assert _option_selection_date(at_close).isoformat() == "2026-11-05"


def test_analysis_uses_only_completed_intraday_candles() -> None:
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from tradinggpt_options.data.models import MarketCandle

    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    completed = MarketCandle(
        exchange="NFO",
        tradingsymbol="NIFTY26NOVFUT",
        instrument_token=123,
        interval="5minute",
        timestamp=now - timedelta(minutes=10),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=1000,
    )
    in_progress = MarketCandle(
        exchange="NFO",
        tradingsymbol="NIFTY26NOVFUT",
        instrument_token=123,
        interval="5minute",
        timestamp=now - timedelta(minutes=2),
        open=Decimal("101"),
        high=Decimal("103"),
        low=Decimal("100"),
        close=Decimal("102"),
        volume=500,
    )
    result = _completed_intraday_candles(
        [completed, in_progress],
        now=now,
        interval_seconds=300,
    )
    assert result == (completed,)
