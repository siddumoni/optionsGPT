from datetime import date
from decimal import Decimal

import pytest

from tradinggpt_options.execution.charges import NseOptionsChargeSchedule


def test_zerodha_nse_option_buy_and_sell_charges_are_side_specific() -> None:
    schedule = NseOptionsChargeSchedule()
    buy = schedule.calculate_order_charges(
        premium=Decimal("100.10"),
        quantity=65,
        side="BUY",
        trade_date=date(2026, 11, 4),
    )
    sell = schedule.calculate_order_charges(
        premium=Decimal("104.90"),
        quantity=65,
        side="SELL",
        trade_date=date(2026, 11, 4),
    )
    assert buy.brokerage == Decimal("20.00")
    assert buy.exchange_transaction == Decimal("2.31")
    assert buy.sebi_turnover == Decimal("0.01")
    assert buy.stt == Decimal("0.00")
    assert buy.stamp_duty == Decimal("0.20")
    assert buy.gst == Decimal("4.02")
    assert buy.total == Decimal("26.54")
    assert sell.stt == Decimal("10.23")
    assert sell.stamp_duty == Decimal("0.00")
    assert sell.total == Decimal("36.70")


def test_charge_schedule_rejects_dates_before_effective_version() -> None:
    schedule = NseOptionsChargeSchedule()
    with pytest.raises(ValueError, match="no charge schedule"):
        schedule.calculate_order_charges(
            premium=Decimal("100"),
            quantity=65,
            side="BUY",
            trade_date=date(2026, 3, 31),
        )


def test_charge_schedule_rejects_invalid_inputs_and_rates() -> None:
    with pytest.raises(ValueError, match="premium"):
        NseOptionsChargeSchedule().calculate_order_charges(
            premium=Decimal("NaN"),
            quantity=65,
            side="BUY",
            trade_date=date(2026, 11, 4),
        )
    with pytest.raises(ValueError, match="nonnegative"):
        NseOptionsChargeSchedule(stt_sell_rate=Decimal("-0.1"))
