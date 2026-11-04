from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from tradinggpt_options.data.models import OptionContract, OptionQuote


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
        grouped[(contract.underlying, contract.expiry, contract.strike)][contract.option_type] = contract
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


def select_nearest_expiry(contracts: Iterable[OptionContract], *, as_of: date) -> date | None:
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
