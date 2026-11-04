from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tradinggpt_options.data.models import FutureContract, OptionContract, OptionQuote


@dataclass(frozen=True, slots=True)
class StrikePair:
    underlying: str
    expiry: date
    strike: Decimal
    call: OptionContract | None
    put: OptionContract | None


def build_strike_pairs(contracts: Iterable[OptionContract]) -> tuple[StrikePair, ...]:
    grouped: dict[tuple[str, date, Decimal], dict[str, OptionContract]] = defaultdict(dict)
    for contract in contracts:
        key = (contract.underlying, contract.expiry, contract.strike)
        grouped[key][contract.option_type] = contract
    pairs = [
        StrikePair(
            underlying=key[0],
            expiry=key[1],
            strike=key[2],
            call=items.get("CE"),
            put=items.get("PE"),
        )
        for key, items in grouped.items()
    ]
    return tuple(
        sorted(pairs, key=lambda item: (item.underlying, item.expiry, item.strike))
    )


@dataclass(frozen=True, slots=True)
class ChainRow:
    contract: OptionContract
    quote: OptionQuote | None


def select_nearest_expiry(
    contracts: Iterable[OptionContract],
    *,
    as_of: date,
) -> date | None:
    expiries = sorted({item.expiry for item in contracts if item.expiry >= as_of})
    return expiries[0] if expiries else None


def select_atm_strike(
    pairs: Iterable[StrikePair],
    *,
    underlying: str,
    expiry: date,
    underlying_price: Decimal,
) -> StrikePair | None:
    eligible = [
        pair for pair in pairs
        if pair.underlying == underlying.upper() and pair.expiry == expiry
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda pair: (abs(pair.strike - underlying_price), pair.strike))


def select_near_atm_contracts(
    contracts: Iterable[OptionContract],
    *,
    spot_prices: dict[str, Decimal],
    as_of: date,
    strikes_each_side: int = 3,
) -> tuple[OptionContract, ...]:
    """Select both CE and PE contracts around ATM for each supplied underlying.

    Only the nearest non-expired expiry is selected for each underlying. The
    selector uses a caller-supplied spot snapshot so it can work with any
    validated underlying-price source; it never guesses missing spot prices.
    """
    if strikes_each_side < 0:
        raise ValueError("strikes_each_side cannot be negative")
    by_underlying: dict[str, list[OptionContract]] = defaultdict(list)
    for contract in contracts:
        by_underlying[contract.underlying.upper()].append(contract)

    selected: list[OptionContract] = []
    for underlying, spot in spot_prices.items():
        key = underlying.upper()
        if not spot.is_finite() or spot <= 0:
            raise ValueError(f"spot price for {key} must be finite and positive")
        universe = by_underlying.get(key, [])
        if not universe:
            continue
        expiry = select_nearest_expiry(universe, as_of=as_of)
        if expiry is None:
            continue
        expiry_contracts = [item for item in universe if item.expiry == expiry]
        strikes = sorted({item.strike for item in expiry_contracts})
        if not strikes:
            continue
        atm_index = min(
            range(len(strikes)),
            key=lambda index: (abs(strikes[index] - spot), strikes[index]),
        )
        start = max(0, atm_index - strikes_each_side)
        end = min(len(strikes), atm_index + strikes_each_side + 1)
        selected_strikes = set(strikes[start:end])
        selected.extend(
            item
            for item in expiry_contracts
            if item.strike in selected_strikes
        )

    return tuple(
        sorted(
            selected,
            key=lambda item: (
                item.underlying,
                item.expiry,
                item.strike,
                item.option_type,
            ),
        )
    )


def select_nearest_future_contract(
    contracts: Iterable[FutureContract],
    *,
    underlying: str,
    as_of: date,
) -> FutureContract | None:
    eligible = [
        item
        for item in contracts
        if item.underlying.upper() == underlying.upper() and item.expiry >= as_of
    ]
    if not eligible:
        return None
    nearest_expiry = min(item.expiry for item in eligible)
    return min(
        (item for item in eligible if item.expiry == nearest_expiry),
        key=lambda item: item.tradingsymbol,
    )
