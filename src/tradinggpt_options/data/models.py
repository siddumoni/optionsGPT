from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal


OptionType = Literal["CE", "PE"]


@dataclass(frozen=True, slots=True)
class OptionContract:
    exchange: str
    tradingsymbol: str
    instrument_token: int
    underlying: str
    expiry: date
    strike: Decimal
    option_type: OptionType
    lot_size: int
    tick_size: Decimal

    def __post_init__(self) -> None:
        if not self.exchange or not self.tradingsymbol or not self.underlying:
            raise ValueError("exchange, tradingsymbol and underlying are required")
        if self.instrument_token <= 0:
            raise ValueError("instrument_token must be positive")
        if self.strike < 0 or self.lot_size <= 0 or self.tick_size <= 0:
            raise ValueError("strike, lot_size and tick_size are invalid")


@dataclass(frozen=True, slots=True)
class DepthLevel:
    price: Decimal
    quantity: int
    orders: int = 0


@dataclass(frozen=True, slots=True)
class OptionQuote:
    exchange: str
    tradingsymbol: str
    instrument_token: int
    exchange_timestamp: datetime | None
    received_at: datetime
    last_price: Decimal | None
    bid: tuple[DepthLevel, ...]
    ask: tuple[DepthLevel, ...]
    volume: int | None
    open_interest: int | None
    source: str = "kite"

    @property
    def best_bid(self) -> Decimal | None:
        return self.bid[0].price if self.bid else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.ask[0].price if self.ask else None

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid


@dataclass(frozen=True, slots=True)
class DataQuality:
    is_stale: bool
    is_crossed_market: bool
    missing_bid: bool
    missing_ask: bool
    warnings: tuple[str, ...]


def assess_quote_quality(quote: OptionQuote, *, now: datetime, max_age_seconds: int = 15) -> DataQuality:
    warnings: list[str] = []
    age_source = quote.exchange_timestamp or quote.received_at
    if age_source.tzinfo is None or now.tzinfo is None:
        warnings.append("timestamps must be timezone-aware")
        stale = True
    else:
        stale = (now - age_source).total_seconds() > max_age_seconds
        if stale:
            warnings.append("quote exceeds configured freshness threshold")

    bid = quote.best_bid
    ask = quote.best_ask
    crossed = bid is not None and ask is not None and bid > ask
    if crossed:
        warnings.append("best bid is greater than best ask")
    missing_bid = bid is None or bid <= 0
    missing_ask = ask is None or ask <= 0
    if missing_bid:
        warnings.append("missing or invalid best bid")
    if missing_ask:
        warnings.append("missing or invalid best ask")
    return DataQuality(stale, crossed, missing_bid, missing_ask, tuple(warnings))
