from __future__ import annotations

from collections import defaultdict
from math import isfinite
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from tradinggpt_options.data.models import (
    OptionContract,
    OptionQuote,
    assess_quote_quality,
)
from tradinggpt_options.options.greeks import (
    Greeks,
    black_scholes_greeks,
    implied_volatility_bisection,
)

MARKET_TIMEZONE = ZoneInfo("Asia/Kolkata")
SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0


@dataclass(frozen=True, slots=True)
class OptionLegAnalytics:
    contract: OptionContract
    quote: OptionQuote | None
    last_price: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    mid_price: Decimal | None
    spread: Decimal | None
    spread_percent: Decimal | None
    volume: int | None
    open_interest: int | None
    implied_volatility: float | None
    greeks: Greeks | None
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OptionChainStrike:
    strike: Decimal
    call: OptionLegAnalytics | None
    put: OptionLegAnalytics | None


@dataclass(frozen=True, slots=True)
class OptionChainView:
    underlying: str
    expiry: date
    snapshot_at: datetime
    spot_price: Decimal
    atm_strike: Decimal
    time_to_expiry_years: float
    risk_free_rate: float
    dividend_yield: float
    strikes: tuple[OptionChainStrike, ...]


def _expiry_time(expiry: date) -> datetime:
    return datetime.combine(
        expiry,
        time(hour=15, minute=30),
        tzinfo=MARKET_TIMEZONE,
    )


def _leg_analytics(
    *,
    contract: OptionContract,
    quote: OptionQuote | None,
    spot_price: Decimal,
    time_to_expiry_years: float,
    risk_free_rate: float,
    dividend_yield: float,
    snapshot_at: datetime,
    max_quote_age_seconds: int,
) -> OptionLegAnalytics:
    if quote is None:
        return OptionLegAnalytics(
            contract=contract,
            quote=None,
            last_price=None,
            bid=None,
            ask=None,
            mid_price=None,
            spread=None,
            spread_percent=None,
            volume=None,
            open_interest=None,
            implied_volatility=None,
            greeks=None,
            quality_flags=("missing_quote",),
        )
    if (
        quote.exchange != contract.exchange
        or quote.tradingsymbol != contract.tradingsymbol
        or quote.instrument_token != contract.instrument_token
    ):
        raise ValueError(
            f"quote identity does not match {contract.exchange}:{contract.tradingsymbol}"
        )

    quality = assess_quote_quality(
        quote,
        now=snapshot_at,
        max_age_seconds=max_quote_age_seconds,
    )
    flags = list(quality.warnings)
    bid = quote.best_bid
    ask = quote.best_ask
    spread = quote.spread
    mid: Decimal | None = None
    spread_percent: Decimal | None = None
    iv: float | None = None
    greeks: Greeks | None = None

    executable_market = not (
        quality.is_stale
        or quality.is_crossed_market
        or quality.missing_bid
        or quality.missing_ask
    )
    if executable_market and bid is not None and ask is not None:
        mid = (bid + ask) / Decimal("2")
        spread_percent = (spread / mid * Decimal("100")) if spread is not None else None
        iv = implied_volatility_bisection(
            option_price=float(mid),
            spot=float(spot_price),
            strike=float(contract.strike),
            time_to_expiry_years=time_to_expiry_years,
            risk_free_rate=risk_free_rate,
            option_type=contract.option_type,
            dividend_yield=dividend_yield,
        )
        if iv is not None:
            greeks = black_scholes_greeks(
                spot=float(spot_price),
                strike=float(contract.strike),
                time_to_expiry_years=time_to_expiry_years,
                risk_free_rate=risk_free_rate,
                volatility=iv,
                option_type=contract.option_type,
                dividend_yield=dividend_yield,
            )
    else:
        flags.append("analytics_suppressed_by_quote_quality")

    return OptionLegAnalytics(
        contract=contract,
        quote=quote,
        last_price=quote.last_price,
        bid=bid,
        ask=ask,
        mid_price=mid,
        spread=spread,
        spread_percent=spread_percent,
        volume=quote.volume,
        open_interest=quote.open_interest,
        implied_volatility=iv,
        greeks=greeks,
        quality_flags=tuple(dict.fromkeys(flags)),
    )


def build_option_chain_view(
    contracts: Iterable[OptionContract],
    quotes: dict[tuple[str, str], OptionQuote],
    *,
    underlying: str,
    expiry: date,
    spot_price: Decimal,
    snapshot_at: datetime,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
    max_quote_age_seconds: int = 15,
) -> OptionChainView:
    """Build a quote-quality-aware CE/PE chain with mid-price IV and BSM Greeks.

    The caller must supply a current spot observation and explicit annualized
    risk-free/dividend assumptions. Expiry time is treated as 15:30 Asia/Kolkata.
    Greeks and IV are model estimates, not exchange-provided values.
    """
    if snapshot_at.tzinfo is None or snapshot_at.utcoffset() is None:
        raise ValueError("snapshot_at must be timezone-aware")
    if not spot_price.is_finite() or spot_price <= 0:
        raise ValueError("spot_price must be finite and positive")
    if max_quote_age_seconds < 1:
        raise ValueError("max_quote_age_seconds must be positive")
    if not underlying.strip():
        raise ValueError("underlying is required")
    if not isfinite(risk_free_rate) or not isfinite(dividend_yield):
        raise ValueError("risk_free_rate and dividend_yield must be finite")

    expiry_at = _expiry_time(expiry)
    seconds_to_expiry = (
        expiry_at - snapshot_at.astimezone(MARKET_TIMEZONE)
    ).total_seconds()
    if seconds_to_expiry <= 0:
        raise ValueError("expiry has passed; an option chain cannot be built")
    time_to_expiry_years = seconds_to_expiry / SECONDS_PER_YEAR

    selected: dict[Decimal, dict[str, OptionContract]] = defaultdict(dict)
    for contract in contracts:
        if (
            contract.underlying.upper() == underlying.strip().upper()
            and contract.expiry == expiry
        ):
            selected[contract.strike][contract.option_type] = contract
    if not selected:
        raise ValueError("no contracts found for requested underlying and expiry")

    strike_values = sorted(selected)
    atm_strike = min(
        strike_values,
        key=lambda strike: (abs(strike - spot_price), strike),
    )
    rows: list[OptionChainStrike] = []
    for strike in strike_values:
        pair = selected[strike]
        call = (
            _leg_analytics(
                contract=pair["CE"],
                quote=quotes.get((pair["CE"].exchange, pair["CE"].tradingsymbol)),
                spot_price=spot_price,
                time_to_expiry_years=time_to_expiry_years,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
                snapshot_at=snapshot_at,
                max_quote_age_seconds=max_quote_age_seconds,
            )
            if "CE" in pair else None
        )
        put = (
            _leg_analytics(
                contract=pair["PE"],
                quote=quotes.get((pair["PE"].exchange, pair["PE"].tradingsymbol)),
                spot_price=spot_price,
                time_to_expiry_years=time_to_expiry_years,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
                snapshot_at=snapshot_at,
                max_quote_age_seconds=max_quote_age_seconds,
            )
            if "PE" in pair else None
        )
        rows.append(OptionChainStrike(strike, call, put))

    return OptionChainView(
        underlying=underlying.strip().upper(),
        expiry=expiry,
        snapshot_at=snapshot_at.astimezone(UTC),
        spot_price=spot_price,
        atm_strike=atm_strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        strikes=tuple(rows),
    )
