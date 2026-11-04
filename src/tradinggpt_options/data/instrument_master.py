from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from tradinggpt_options.data.models import OptionContract


@dataclass(frozen=True, slots=True)
class InstrumentParseResult:
    contracts: tuple[OptionContract, ...]
    rejected_rows: int
    errors: tuple[str, ...]


def parse_kite_instruments(
    csv_text: str,
    *,
    underlyings: Iterable[str] | None = None,
) -> InstrumentParseResult:
    """Parse Kite's daily instrument CSV, selecting NFO-OPT CE/PE rows.

    Treat exchange + trading symbol as the natural key. Instrument tokens are
    retained for live subscriptions but are not permanent historical identities.
    """
    allowed = {item.upper() for item in underlyings} if underlyings is not None else None
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {
        "instrument_token",
        "tradingsymbol",
        "name",
        "expiry",
        "strike",
        "tick_size",
        "lot_size",
        "instrument_type",
        "segment",
        "exchange",
    }
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        missing = sorted(required - set(reader.fieldnames or []))
        raise ValueError(f"instrument CSV missing required columns: {missing}")

    contracts: list[OptionContract] = []
    errors: list[str] = []
    rejected = 0
    seen: set[tuple[str, str]] = set()

    for line_number, row in enumerate(reader, start=2):
        if (
            (row.get("segment") or "").strip() != "NFO-OPT"
            or (row.get("instrument_type") or "").strip() not in {"CE", "PE"}
        ):
            continue
        try:
            underlying = (row.get("name") or "").strip().upper()
            if not underlying:
                raise ValueError("empty underlying name")
            if allowed is not None and underlying not in allowed:
                continue
            exchange = (row.get("exchange") or "").strip().upper()
            symbol = (row.get("tradingsymbol") or "").strip().upper()
            identity = (exchange, symbol)
            if not all(identity):
                raise ValueError("empty exchange/tradingsymbol")
            if identity in seen:
                raise ValueError("duplicate exchange/tradingsymbol")
            if not row.get("expiry"):
                raise ValueError("missing option expiry")
            contract = OptionContract(
                exchange=exchange,
                tradingsymbol=symbol,
                instrument_token=int(row["instrument_token"]),
                underlying=underlying,
                expiry=date.fromisoformat(row["expiry"]),
                strike=Decimal(row["strike"]),
                option_type=row["instrument_type"],  # type: ignore[arg-type]
                lot_size=int(row["lot_size"]),
                tick_size=Decimal(row["tick_size"]),
            )
            seen.add(identity)
            contracts.append(contract)
        except (ValueError, TypeError, InvalidOperation, KeyError) as exc:
            rejected += 1
            errors.append(f"line {line_number}: {exc}")

    contracts.sort(
        key=lambda item: (
            item.underlying, item.expiry, item.strike, item.option_type
        )
    )
    return InstrumentParseResult(tuple(contracts), rejected, tuple(errors))
