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
        if self.option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")
        if (
            not self.strike.is_finite()
            or not self.tick_size.is_finite()
            or self.strike < 0
            or self.lot_size <= 0
            or self.tick_size <= 0
        ):
            raise ValueError("strike, lot_size and tick_size are invalid")


@dataclass(frozen=True, slots=True)
class DepthLevel:
    price: Decimal
    quantity: int
    orders: int = 0

    def __post_init__(self) -> None:
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("depth price must be finite and positive")
        if self.quantity < 0 or self.orders < 0:
            raise ValueError("depth quantity and order count cannot be negative")


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

    def __post_init__(self) -> None:
        if self.instrument_token <= 0:
            raise ValueError("instrument_token must be positive")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        if self.exchange_timestamp is not None and (
            self.exchange_timestamp.tzinfo is None
            or self.exchange_timestamp.utcoffset() is None
        ):
            raise ValueError("exchange_timestamp must be timezone-aware")
        if self.last_price is not None and (
            not self.last_price.is_finite() or self.last_price < 0
        ):
            raise ValueError("last_price must be finite and nonnegative")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume cannot be negative")
        if self.open_interest is not None and self.open_interest < 0:
            raise ValueError("open_interest cannot be negative")

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
        age_seconds = (now - age_source).total_seconds()
        stale = age_seconds > max_age_seconds or age_seconds < -5
        if age_seconds > max_age_seconds:
            warnings.append("quote exceeds configured freshness threshold")
        elif age_seconds < -5:
            warnings.append("quote timestamp is in the future beyond clock-skew tolerance")

    bid = quote.best_bid
    ask = quote.best_ask
    crossed = bid is not None and ask is not None and bid > ask
    if crossed:
        warnings.append("best bid is greater than best ask")
    missing_bid = (
        bid is None
        or bid <= 0
        or not quote.bid
        or quote.bid[0].quantity <= 0
    )
    missing_ask = (
        ask is None
        or ask <= 0
        or not quote.ask
        or quote.ask[0].quantity <= 0
    )
    if missing_bid:
        warnings.append("missing or invalid best bid")
    if missing_ask:
        warnings.append("missing or invalid best ask")
    return DataQuality(stale, crossed, missing_bid, missing_ask, tuple(warnings))


@dataclass(frozen=True, slots=True)
class MarketCandle:
    exchange: str
    tradingsymbol: str
    instrument_token: int
    interval: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    open_interest: int | None = None

    def __post_init__(self) -> None:
        if not self.exchange or not self.tradingsymbol:
            raise ValueError("candle exchange and tradingsymbol are required")
        if self.instrument_token <= 0:
            raise ValueError("candle instrument_token must be positive")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("candle timestamp must be timezone-aware")
        prices = (self.open, self.high, self.low, self.close)
        if not all(price.is_finite() and price > 0 for price in prices):
            raise ValueError("candle OHLC prices must be finite and positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("candle high is inconsistent with OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("candle low is inconsistent with OHLC values")
        if self.volume < 0:
            raise ValueError("candle volume cannot be negative")
        if self.open_interest is not None and self.open_interest < 0:
            raise ValueError("candle open interest cannot be negative")


@dataclass(frozen=True, slots=True)
class FutureContract:
    exchange: str
    tradingsymbol: str
    instrument_token: int
    underlying: str
    expiry: date
    lot_size: int
    tick_size: Decimal

    def __post_init__(self) -> None:
        if not self.exchange or not self.tradingsymbol or not self.underlying:
            raise ValueError("future exchange, symbol and underlying are required")
        if self.instrument_token <= 0 or self.lot_size <= 0:
            raise ValueError("future token and lot_size must be positive")
        if not self.tick_size.is_finite() or self.tick_size <= 0:
            raise ValueError("future tick_size must be finite and positive")
