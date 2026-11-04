import pytest

from tradinggpt_options.cli import _parse_spot_instrument_mappings


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
