from datetime import datetime

import pytest

from tradinggpt_options.cli import (
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
