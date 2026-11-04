import pytest

from tradinggpt_options.options.greeks import black_scholes_greeks, implied_volatility_bisection


def test_call_delta_and_put_delta_are_in_expected_ranges() -> None:
    call = black_scholes_greeks(
        spot=100, strike=100, time_to_expiry_years=0.5,
        risk_free_rate=0.05, volatility=0.2, option_type="CE",
    )
    put = black_scholes_greeks(
        spot=100, strike=100, time_to_expiry_years=0.5,
        risk_free_rate=0.05, volatility=0.2, option_type="PE",
    )
    assert 0.5 < call.delta < 1.0
    assert -0.5 < put.delta < 0.0
    assert call.gamma > 0
    assert call.vega_per_1pct > 0
    assert call.theta_per_day < 0


def test_iv_solver_recovers_known_volatility() -> None:
    price = 6.888728577680624
    iv = implied_volatility_bisection(
        option_price=price, spot=100, strike=100, time_to_expiry_years=0.5,
        risk_free_rate=0.05, option_type="CE",
    )
    assert iv == pytest.approx(0.2, abs=1e-5)


def test_iv_returns_none_for_nonpositive_premium() -> None:
    iv = implied_volatility_bisection(
        option_price=0, spot=100, strike=100, time_to_expiry_years=0.5,
        risk_free_rate=0.05, option_type="CE",
    )
    assert iv is None
