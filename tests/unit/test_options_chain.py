from datetime import date
from decimal import Decimal

from tradinggpt_options.data.models import OptionContract
from tradinggpt_options.options.chain import (
    build_strike_pairs,
    select_atm_strike,
    select_nearest_expiry,
)


def contract(
    symbol: str,
    typ: str,
    strike: str,
    expiry: date = date(2026, 11, 26),
) -> OptionContract:
    return OptionContract(
        exchange="NFO",
        tradingsymbol=symbol,
        instrument_token=1 if typ == "CE" else 2,
        underlying="NIFTY",
        expiry=expiry,
        strike=Decimal(strike),
        option_type=typ,  # type: ignore[arg-type]
        lot_size=65,
        tick_size=Decimal("0.05"),
    )


def test_builds_call_put_pairs_and_selects_atm() -> None:
    contracts = [
        contract("NIFTY25000CE", "CE", "25000"),
        contract("NIFTY25000PE", "PE", "25000"),
        contract("NIFTY25100CE", "CE", "25100"),
    ]
    pairs = build_strike_pairs(contracts)
    atm = select_atm_strike(
        pairs,
        underlying="NIFTY",
        expiry=date(2026, 11, 26),
        underlying_price=Decimal("25020"),
    )
    assert atm is not None
    assert atm.strike == Decimal("25000")
    assert atm.call is not None and atm.put is not None


def test_selects_next_expiry_not_expired_contract() -> None:
    contracts = [
        contract("OLD", "CE", "25000", date(2026, 10, 29)),
        contract("NEW", "PE", "25000", date(2026, 11, 26)),
    ]
    assert select_nearest_expiry(contracts, as_of=date(2026, 11, 4)) == date(2026, 11, 26)


def test_selects_near_atm_call_and_put_window_for_each_underlying() -> None:
    from tradinggpt_options.options.chain import select_near_atm_contracts

    expiry = date(2026, 11, 26)
    contracts = [
        contract(f"NIFTY{strike}{side}", side, str(strike), expiry)
        for strike in (24900, 25000, 25100, 25200, 25300)
        for side in ("CE", "PE")
    ]
    selected = select_near_atm_contracts(
        contracts,
        spot_prices={"NIFTY": Decimal("25120")},
        as_of=date(2026, 11, 4),
        strikes_each_side=1,
    )
    assert {item.strike for item in selected} == {
        Decimal("25000"), Decimal("25100"), Decimal("25200")
    }
    assert {item.option_type for item in selected} == {"CE", "PE"}
    assert len(selected) == 6


def test_near_atm_selector_rejects_invalid_spot_and_negative_window() -> None:
    import pytest

    from tradinggpt_options.options.chain import select_near_atm_contracts

    contracts = [contract("NIFTY25000CE", "CE", "25000")]
    with pytest.raises(ValueError, match="spot price"):
        select_near_atm_contracts(
            contracts,
            spot_prices={"NIFTY": Decimal("NaN")},
            as_of=date(2026, 11, 4),
        )
    with pytest.raises(ValueError, match="strikes_each_side"):
        select_near_atm_contracts(
            contracts,
            spot_prices={"NIFTY": Decimal("25000")},
            as_of=date(2026, 11, 4),
            strikes_each_side=-1,
        )


def test_selects_nearest_nonexpired_future_contract() -> None:
    from tradinggpt_options.data.models import FutureContract
    from tradinggpt_options.options.chain import select_nearest_future_contract

    futures = [
        FutureContract(
            exchange="NFO",
            tradingsymbol="NIFTY26OCTFUT",
            instrument_token=1,
            underlying="NIFTY",
            expiry=date(2026, 10, 29),
            lot_size=65,
            tick_size=Decimal("0.05"),
        ),
        FutureContract(
            exchange="NFO",
            tradingsymbol="NIFTY26NOVFUT",
            instrument_token=2,
            underlying="NIFTY",
            expiry=date(2026, 11, 26),
            lot_size=65,
            tick_size=Decimal("0.05"),
        ),
        FutureContract(
            exchange="NFO",
            tradingsymbol="NIFTY26DECFUT",
            instrument_token=3,
            underlying="NIFTY",
            expiry=date(2026, 12, 31),
            lot_size=65,
            tick_size=Decimal("0.05"),
        ),
    ]
    selected = select_nearest_future_contract(
        futures,
        underlying="NIFTY",
        as_of=date(2026, 11, 4),
    )
    assert selected is not None
    assert selected.tradingsymbol == "NIFTY26NOVFUT"
