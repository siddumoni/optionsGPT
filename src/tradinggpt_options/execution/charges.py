from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

OrderSide = Literal["BUY", "SELL"]
PAISE = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def _whole_rupee(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ChargeBreakdown:
    brokerage: Decimal
    exchange_transaction: Decimal
    sebi_turnover: Decimal
    ipft: Decimal
    stt: Decimal
    stamp_duty: Decimal
    gst: Decimal

    @property
    def total(self) -> Decimal:
        return sum(
            (
                self.brokerage,
                self.exchange_transaction,
                self.sebi_turnover,
                self.ipft,
                self.stt,
                self.stamp_duty,
                self.gst,
            ),
            Decimal("0"),
        )

    def as_dict(self) -> dict[str, str]:
        values = asdict(self)
        values["total"] = self.total
        return {key: format(_money(value), "f") for key, value in values.items()}


@dataclass(frozen=True, slots=True)
class NseOptionsChargeSchedule:
    """Estimated Zerodha/NSE NSE-equity-options charges for trades from 1-Apr-2026.

    Rates are versioned and date-gated. Brokerage is Zerodha's flat per-order
    option brokerage. Exchange, SEBI, STT, stamp duty and GST follow published
    rates. Final contract-note reconciliation remains authoritative.
    """

    effective_from: date = date(2026, 4, 1)
    brokerage_per_order: Decimal = Decimal("20")
    exchange_transaction_rate: Decimal = Decimal("0.000355299")
    sebi_turnover_rate: Decimal = Decimal("0.000001")
    ipft_turnover_rate: Decimal = Decimal("0.000000001")
    stt_sell_rate: Decimal = Decimal("0.0015")
    stamp_duty_buy_rate: Decimal = Decimal("0.00003")
    gst_rate: Decimal = Decimal("0.18")
    version: str = "zerodha-nse-options-2026-04-01"

    def __post_init__(self) -> None:
        rates = (
            self.brokerage_per_order,
            self.exchange_transaction_rate,
            self.sebi_turnover_rate,
            self.ipft_turnover_rate,
            self.stt_sell_rate,
            self.stamp_duty_buy_rate,
            self.gst_rate,
        )
        if any(not value.is_finite() or value < 0 for value in rates):
            raise ValueError("charge rates must be finite and nonnegative")
        if not self.version.strip():
            raise ValueError("charge schedule version is required")

    def calculate_order_charges(
        self,
        *,
        premium: Decimal,
        quantity: int,
        side: OrderSide,
        trade_date: date,
    ) -> ChargeBreakdown:
        if not premium.is_finite() or premium <= 0:
            raise ValueError("premium must be finite and positive")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if trade_date < self.effective_from:
            raise ValueError(
                f"no charge schedule configured for trade date before "
                f"{self.effective_from.isoformat()}"
            )

        premium_turnover = premium * quantity
        brokerage = _money(self.brokerage_per_order)
        exchange = _money(premium_turnover * self.exchange_transaction_rate)
        sebi = _money(premium_turnover * self.sebi_turnover_rate)
        ipft = _money(premium_turnover * self.ipft_turnover_rate)
        stt = _whole_rupee(
            premium_turnover * self.stt_sell_rate if side == "SELL" else Decimal("0")
        )
        stamp = _money(
            premium_turnover * self.stamp_duty_buy_rate
            if side == "BUY" else Decimal("0")
        )
        gst = _money((brokerage + exchange + sebi + ipft) * self.gst_rate)
        return ChargeBreakdown(
            brokerage=brokerage,
            exchange_transaction=exchange,
            sebi_turnover=sebi,
            ipft=ipft,
            stt=stt,
            stamp_duty=stamp,
            gst=gst,
        )
