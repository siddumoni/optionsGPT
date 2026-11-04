from decimal import Decimal

from tradinggpt_options.risk.limits import RiskLimits, size_long_option_position


def test_sizes_whole_lots_with_premium_at_risk() -> None:
    limits = RiskLimits(
        max_position_loss=Decimal("15000"),
        max_daily_loss=Decimal("20000"),
        max_concurrent_positions=3,
    )
    result = size_long_option_position(
        available_cash=Decimal("100000"),
        premium_per_unit=Decimal("100"),
        lot_size=65,
        limits=limits,
    )
    assert result.approved
    assert result.lots == 2
    assert result.quantity == 130
    assert result.max_loss == Decimal("13000")


def test_rejects_trade_after_daily_loss_limit() -> None:
    limits = RiskLimits(Decimal("5000"), Decimal("10000"), 2)
    result = size_long_option_position(
        available_cash=Decimal("100000"),
        premium_per_unit=Decimal("50"),
        lot_size=65,
        limits=limits,
        current_daily_net_pnl=Decimal("-10000"),
    )
    assert not result.approved
    assert result.lots == 0
