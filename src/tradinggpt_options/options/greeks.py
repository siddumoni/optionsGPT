from __future__ import annotations

from dataclasses import dataclass
from math import erf, exp, log, pi, sqrt
from typing import Literal


OptionType = Literal["CE", "PE"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


@dataclass(frozen=True, slots=True)
class Greeks:
    delta: float
    gamma: float
    theta_per_day: float
    vega_per_1pct: float
    implied_volatility: float
    model: str = "black_scholes_european"


def black_scholes_greeks(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    option_type: OptionType,
    dividend_yield: float = 0.0,
) -> Greeks:
    """European Black–Scholes–Merton Greeks.

    Theta is returned per calendar day; vega is returned per 1 volatility point
    (1 percentage point). This is an analytical model, not an exchange-provided
    Greek. Use actual time-to-expiry conventions and appropriate carry inputs.
    """
    values = (spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
    if not all(isinstance(v, (int, float)) for v in values):
        raise TypeError("model inputs must be numeric")
    if spot <= 0 or strike <= 0 or time_to_expiry_years <= 0 or volatility <= 0:
        raise ValueError("spot, strike, time to expiry and volatility must be positive")
    if option_type not in ("CE", "PE"):
        raise ValueError("option_type must be CE or PE")

    t = time_to_expiry_years
    sigma = volatility
    root_t = sqrt(t)
    d1 = (log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * sigma * sigma) * t) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    discount_q = exp(-dividend_yield * t)
    discount_r = exp(-risk_free_rate * t)
    density = _norm_pdf(d1)
    gamma = discount_q * density / (spot * sigma * root_t)
    vega = spot * discount_q * density * root_t / 100.0

    common_theta = -(spot * discount_q * density * sigma) / (2.0 * root_t)
    if option_type == "CE":
        delta = discount_q * _norm_cdf(d1)
        theta = common_theta - risk_free_rate * strike * discount_r * _norm_cdf(d2) + dividend_yield * spot * discount_q * _norm_cdf(d1)
    else:
        delta = discount_q * (_norm_cdf(d1) - 1.0)
        theta = common_theta + risk_free_rate * strike * discount_r * _norm_cdf(-d2) - dividend_yield * spot * discount_q * _norm_cdf(-d1)

    return Greeks(
        delta=delta,
        gamma=gamma,
        theta_per_day=theta / 365.0,
        vega_per_1pct=vega,
        implied_volatility=sigma,
    )


def implied_volatility_bisection(
    *,
    option_price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: OptionType,
    dividend_yield: float = 0.0,
    low_vol: float = 1e-4,
    high_vol: float = 5.0,
    tolerance: float = 1e-7,
    max_iterations: int = 200,
) -> float | None:
    """Solve European BSM IV by bisection; returns None if price is outside bounds."""
    if option_price <= 0:
        return None
    if time_to_expiry_years <= 0:
        return None

    def theoretical(vol: float) -> float:
        g = black_scholes_greeks(
            spot=spot, strike=strike, time_to_expiry_years=time_to_expiry_years,
            risk_free_rate=risk_free_rate, volatility=vol, option_type=option_type,
            dividend_yield=dividend_yield,
        )
        t = time_to_expiry_years
        d1 = (log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * vol * vol) * t) / (vol * sqrt(t))
        d2 = d1 - vol * sqrt(t)
        if option_type == "CE":
            return spot * exp(-dividend_yield * t) * _norm_cdf(d1) - strike * exp(-risk_free_rate * t) * _norm_cdf(d2)
        return strike * exp(-risk_free_rate * t) * _norm_cdf(-d2) - spot * exp(-dividend_yield * t) * _norm_cdf(-d1)

    lower_price = theoretical(low_vol)
    upper_price = theoretical(high_vol)
    if option_price < lower_price - tolerance or option_price > upper_price + tolerance:
        return None

    lo, hi = low_vol, high_vol
    for _ in range(max_iterations):
        mid = (lo + hi) / 2.0
        model_price = theoretical(mid)
        if abs(model_price - option_price) <= tolerance:
            return mid
        if model_price < option_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
