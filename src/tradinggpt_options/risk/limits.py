from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_position_loss: Decimal
    max_daily_loss: Decimal
    max_concurrent_positions: int
    max_capital_utilization: Decimal = Decimal("1.0")

    def __post_init__(self) -> None:
        if self.max_position_loss <= 0 or self.max_daily_loss <= 0:
            raise ValueError("loss limits must be positive")
        if self.max_concurrent_positions < 1:
            raise ValueError("max_concurrent_positions must be >= 1")
        if not Decimal("0") < self.max_capital_utilization <= Decimal("1"):
            raise ValueError("max_capital_utilization must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class SizingResult:
    approved: bool
    lots: int
    quantity: int
    premium_debit: Decimal
    max_loss: Decimal
    reason: str


def size_long_option_position(
    *,
    available_cash: Decimal,
    premium_per_unit: Decimal,
    lot_size: int,
    limits: RiskLimits,
    current_daily_net_pnl: Decimal = Decimal("0"),
    current_open_positions: int = 0,
) -> SizingResult:
    """Bound long-option premium exposure by risk and available cash."""
    if available_cash <= 0 or premium_per_unit <= 0 or lot_size <= 0:
        return SizingResult(
            False, 0, 0, Decimal("0"), Decimal("0"), "invalid capital/premium/lot"
        )
    if current_open_positions >= limits.max_concurrent_positions:
        return SizingResult(
            False, 0, 0, Decimal("0"), Decimal("0"), "position limit reached"
        )
    if current_daily_net_pnl <= -limits.max_daily_loss:
        return SizingResult(
            False, 0, 0, Decimal("0"), Decimal("0"), "daily loss limit reached"
        )

    daily_headroom = limits.max_daily_loss + current_daily_net_pnl
    per_lot_debit = premium_per_unit * lot_size
    max_cash = available_cash * limits.max_capital_utilization
    risk_budget = min(limits.max_position_loss, daily_headroom)
    lots_by_risk = int(risk_budget // per_lot_debit)
    lots_by_cash = int(max_cash // per_lot_debit)
    lots = min(lots_by_risk, lots_by_cash)
    if lots < 1:
        return SizingResult(
            False,
            0,
            0,
            Decimal("0"),
            Decimal("0"),
            "one lot exceeds capital or risk headroom",
        )
    quantity = lots * lot_size
    debit = per_lot_debit * lots
    return SizingResult(
        True,
        lots,
        quantity,
        debit,
        debit,
        "approved within configured premium-risk and cash limits",
    )
