from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from tradinggpt_options.data.models import FutureContract, OptionContract


INDEX_UNDERLYING_PREFIXES = (
    "BANKNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "FINNIFTY",
    "NIFTY",
)


def _resolve_underlying(name: str, tradingsymbol: str) -> str:
    """Resolve stock underlyings from name and index underlyings from symbol prefix.

    Kite's daily instrument CSV may leave the name field blank for index
    derivatives. The index prefixes are explicit and longest-first to avoid
    matching NIFTY inside BANKNIFTY or NIFTYNXT50.
    """
    normalized_name = name.strip().upper()
    if normalized_name:
        return normalized_name
    symbol = tradingsymbol.strip().upper()
    for prefix in INDEX_UNDERLYING_PREFIXES:
        if symbol.startswith(prefix):
            return prefix
    raise ValueError(
        "empty underlying name and no recognized NSE index prefix in tradingsymbol"
    )


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
            exchange = (row.get("exchange") or "").strip().upper()
            symbol = (row.get("tradingsymbol") or "").strip().upper()
            underlying = _resolve_underlying(row.get("name") or "", symbol)
            if allowed is not None and underlying not in allowed:
                continue
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


@dataclass(frozen=True, slots=True)
class FutureInstrumentParseResult:
    contracts: tuple[FutureContract, ...]
    rejected_rows: int
    errors: tuple[str, ...]


def parse_kite_futures_instruments(
    csv_text: str,
    *,
    underlyings: Iterable[str] | None = None,
) -> FutureInstrumentParseResult:
    """Parse the NFO-FUT subset of Kite's daily NFO instrument master."""
    allowed = {item.upper() for item in underlyings} if underlyings is not None else None
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {
        "instrument_token",
        "tradingsymbol",
        "name",
        "expiry",
        "tick_size",
        "lot_size",
        "instrument_type",
        "segment",
        "exchange",
    }
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        missing = sorted(required - set(reader.fieldnames or []))
        raise ValueError(f"instrument CSV missing required columns: {missing}")

    contracts: list[FutureContract] = []
    errors: list[str] = []
    rejected = 0
    seen: set[tuple[str, str]] = set()
    for line_number, row in enumerate(reader, start=2):
        if (
            (row.get("segment") or "").strip() != "NFO-FUT"
            or (row.get("instrument_type") or "").strip() != "FUT"
        ):
            continue
        try:
            exchange = (row.get("exchange") or "").strip().upper()
            symbol = (row.get("tradingsymbol") or "").strip().upper()
            underlying = _resolve_underlying(row.get("name") or "", symbol)
            if allowed is not None and underlying not in allowed:
                continue
            identity = (exchange, symbol)
            if not all(identity):
                raise ValueError("empty exchange/tradingsymbol")
            if identity in seen:
                raise ValueError("duplicate exchange/tradingsymbol")
            contract = FutureContract(
                exchange=exchange,
                tradingsymbol=symbol,
                instrument_token=int(row["instrument_token"]),
                underlying=underlying,
                expiry=date.fromisoformat(row["expiry"]),
                lot_size=int(row["lot_size"]),
                tick_size=Decimal(row["tick_size"]),
            )
            seen.add(identity)
            contracts.append(contract)
        except (ValueError, TypeError, InvalidOperation, KeyError) as exc:
            rejected += 1
            errors.append(f"line {line_number}: {exc}")

    contracts.sort(key=lambda item: (item.underlying, item.expiry, item.tradingsymbol))
    return FutureInstrumentParseResult(
        tuple(contracts),
        rejected,
        tuple(errors),
    )
