from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradinggpt_options.data.models import (
    DepthLevel,
    OptionContract,
    OptionQuote,
    assess_quote_quality,
)
from tradinggpt_options.execution.charges import NseOptionsChargeSchedule, OrderSide
from tradinggpt_options.risk.limits import RiskLimits, size_long_option_position
from tradinggpt_options.storage.tables import PaperAccount, PaperTrade


@dataclass(frozen=True, slots=True)
class PaperExecutionConfig:
    initial_capital: Decimal = Decimal("100000")
    max_quote_age_seconds: int = 15
    charges_per_side: Decimal | None = None
    charge_schedule: NseOptionsChargeSchedule = field(
        default_factory=NseOptionsChargeSchedule
    )
    risk_limits: RiskLimits | None = None

    def __post_init__(self) -> None:
        if not self.initial_capital.is_finite() or self.initial_capital <= 0:
            raise ValueError("initial_capital must be finite and positive")
        if self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be positive")
        if self.charges_per_side is not None and (
            not self.charges_per_side.is_finite() or self.charges_per_side < 0
        ):
            raise ValueError("charges_per_side override must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class PaperFill:
    trade_id: str
    status: str
    quantity: int
    price: Decimal
    cash_balance: Decimal
    message: str


class PaperBroker:
    """Local long-options paper broker. Has no connection to broker order APIs.

    Entry consumes ask depth and exit consumes bid depth using VWAP. Stale, crossed,
    one-sided or insufficient-depth quotes are rejected. Each side uses the
    effective-dated Zerodha/NSE charge schedule. Opening a position also requires
    explicit risk limits; open premium is conservatively counted against daily loss.
    """

    def __init__(
        self,
        session: Session,
        *,
        account_name: str,
        config: PaperExecutionConfig,
    ) -> None:
        if not account_name.strip():
            raise ValueError("account_name is required")
        self.session = session
        self.account_name = account_name
        self.config = config
        account = self.session.scalar(
            select(PaperAccount).where(PaperAccount.name == account_name)
        )
        if account is None:
            account = PaperAccount(
                name=account_name,
                initial_capital=config.initial_capital,
                cash_balance=config.initial_capital,
            )
            self.session.add(account)
            self.session.commit()
        elif account.initial_capital != config.initial_capital:
            raise ValueError(
                "configured initial capital does not match persisted account capital"
            )
        self.account_id = account.id

    def _account(self) -> PaperAccount:
        account = self.session.get(PaperAccount, self.account_id)
        if account is None:
            raise RuntimeError("paper account disappeared from storage")
        return account

    @staticmethod
    def _depth_fill_price(levels: tuple[DepthLevel, ...], quantity: int) -> Decimal:
        """Calculate a full-fill VWAP by consuming displayed depth from best price."""
        remaining = quantity
        turnover = Decimal("0")
        for level in levels:
            filled = min(remaining, level.quantity)
            turnover += level.price * filled
            remaining -= filled
            if remaining == 0:
                break
        if remaining:
            raise ValueError(
                f"insufficient displayed depth: requested {quantity}, "
                f"unfilled quantity {remaining}"
            )
        return (turnover / quantity).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    def _calculate_charges(
        self,
        *,
        premium: Decimal,
        quantity: int,
        side: OrderSide,
        at: datetime,
    ) -> tuple[Decimal, str]:
        if self.config.charges_per_side is not None:
            amount = self.config.charges_per_side.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            payload = {
                "schedule_version": "flat-override",
                "flat_override": format(amount, "f"),
                "total": format(amount, "f"),
            }
            return amount, json.dumps(payload, separators=(",", ":"))

        trade_date = at.astimezone(ZoneInfo("Asia/Kolkata")).date()
        breakdown = self.config.charge_schedule.calculate_order_charges(
            premium=premium,
            quantity=quantity,
            side=side,
            trade_date=trade_date,
        )
        payload = {
            "schedule_version": self.config.charge_schedule.version,
            **breakdown.as_dict(),
        }
        return breakdown.total, json.dumps(payload, separators=(",", ":"))

    def _daily_risk_state(self, *, now: datetime) -> tuple[Decimal, int]:
        local_date = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
        realized_today = Decimal("0")
        for trade in self.trade_history():
            if trade.status != "CLOSED" or trade.exit_at is None:
                continue
            exit_at = (
                trade.exit_at.replace(tzinfo=UTC)
                if trade.exit_at.tzinfo is None
                else trade.exit_at.astimezone(UTC)
            )
            if exit_at.astimezone(ZoneInfo("Asia/Kolkata")).date() == local_date:
                realized_today += trade.net_pnl

        open_positions = self.open_trades()
        worst_case_open_exposure = sum(
            (
                trade.entry_premium * trade.quantity + trade.charges
                for trade in open_positions
            ),
            Decimal("0"),
        )
        # Count all open premium at risk against today's loss budget. This is
        # conservative and avoids depending on a missing mark for an open leg.
        daily_risk_pnl = realized_today - worst_case_open_exposure
        return daily_risk_pnl, len(open_positions)

    def _validate_quote(self, quote: OptionQuote, *, now: datetime) -> None:
        quality = assess_quote_quality(
            quote,
            now=now,
            max_age_seconds=self.config.max_quote_age_seconds,
        )
        if quality.is_stale:
            raise ValueError("quote is stale; paper order rejected")
        if quality.is_crossed_market:
            raise ValueError("quote has crossed bid/ask; paper order rejected")
        if quality.missing_bid or quality.missing_ask:
            raise ValueError("two-sided market depth is required for paper execution")

    def buy_to_open(
        self,
        *,
        contract: OptionContract,
        quote: OptionQuote,
        lots: int,
        now: datetime | None = None,
        reason: str = "",
    ) -> PaperFill:
        observed_now = now or datetime.now(UTC)
        if observed_now.tzinfo is None or observed_now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        self._validate_quote(quote, now=observed_now)
        if (contract.exchange, contract.tradingsymbol, contract.instrument_token) != (
            quote.exchange, quote.tradingsymbol, quote.instrument_token
        ):
            raise ValueError("quote identity does not match selected option contract")
        if lots < 1:
            raise ValueError("lots must be at least one")
        quantity = lots * contract.lot_size
        ask = self._depth_fill_price(quote.ask, quantity)
        account = self._account()
        limits = self.config.risk_limits
        if limits is None:
            raise ValueError("risk limits must be configured before opening paper positions")
        daily_risk_pnl, open_position_count = self._daily_risk_state(now=observed_now)
        sizing = size_long_option_position(
            available_cash=account.cash_balance,
            premium_per_unit=ask,
            lot_size=contract.lot_size,
            limits=limits,
            current_daily_net_pnl=daily_risk_pnl,
            current_open_positions=open_position_count,
        )
        if not sizing.approved:
            raise ValueError(f"paper risk rejected: {sizing.reason}")
        if lots > sizing.lots:
            raise ValueError(
                f"requested {lots} lots exceeds configured risk limits; "
                f"maximum approved lots: {sizing.lots}"
            )
        notional = (ask * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        entry_charge, entry_charges_json = self._calculate_charges(
            premium=ask,
            quantity=quantity,
            side="BUY",
            at=observed_now,
        )
        total_debit = notional + entry_charge
        if account.cash_balance < total_debit:
            raise ValueError("insufficient paper cash for premium debit and charges")

        open_trade = self.session.scalar(
            select(PaperTrade).where(
                PaperTrade.account_id == self.account_id,
                PaperTrade.exchange == contract.exchange,
                PaperTrade.tradingsymbol == contract.tradingsymbol,
                PaperTrade.status == "OPEN",
            )
        )
        if open_trade is not None:
            raise ValueError("an open paper position already exists for this contract")

        trade_id = str(uuid4())
        account.cash_balance -= total_debit
        self.session.add(
            PaperTrade(
                id=trade_id,
                account_id=self.account_id,
                exchange=contract.exchange,
                tradingsymbol=contract.tradingsymbol,
                underlying=contract.underlying,
                expiry=contract.expiry,
                strike=contract.strike,
                option_type=contract.option_type,
                lot_size=contract.lot_size,
                quantity=quantity,
                entry_premium=ask,
                entry_at=observed_now,
                status="OPEN",
                gross_pnl=Decimal("0"),
                charges=entry_charge,
                entry_charges_json=entry_charges_json,
                exit_charges_json="{}",
                net_pnl=Decimal("0"),
                entry_reason=reason[:2048],
            )
        )
        self.session.commit()
        return PaperFill(
            trade_id,
            "OPEN",
            quantity,
            ask,
            account.cash_balance,
            "paper buy filled at best ask",
        )

    def sell_to_close(
        self,
        *,
        trade_id: str,
        quote: OptionQuote,
        now: datetime | None = None,
        reason: str = "",
    ) -> PaperFill:
        observed_now = now or datetime.now(UTC)
        if observed_now.tzinfo is None or observed_now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        self._validate_quote(quote, now=observed_now)
        trade = self.session.get(PaperTrade, trade_id)
        if trade is None or trade.account_id != self.account_id:
            raise ValueError("paper trade not found in this account")
        if trade.status != "OPEN":
            raise ValueError("paper trade is not open")
        if (
            trade.exchange != quote.exchange
            or trade.tradingsymbol != quote.tradingsymbol
        ):
            raise ValueError("exit quote does not match open contract")

        bid = self._depth_fill_price(quote.bid, trade.quantity)
        gross_pnl = ((bid - trade.entry_premium) * trade.quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        exit_charge, exit_charges_json = self._calculate_charges(
            premium=bid,
            quantity=trade.quantity,
            side="SELL",
            at=observed_now,
        )
        trade.charges += exit_charge
        trade.exit_charges_json = exit_charges_json
        trade.gross_pnl = gross_pnl
        trade.net_pnl = gross_pnl - trade.charges
        trade.exit_premium = bid
        trade.exit_at = observed_now
        trade.status = "CLOSED"
        trade.exit_reason = reason[:2048]

        account = self._account()
        proceeds = (bid * trade.quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        account.cash_balance += proceeds - exit_charge
        self.session.commit()
        return PaperFill(
            trade.id,
            "CLOSED",
            trade.quantity,
            bid,
            account.cash_balance,
            "paper sell filled at best bid",
        )

    def open_trades(self) -> list[PaperTrade]:
        return list(
            self.session.scalars(
                select(PaperTrade).where(
                    PaperTrade.account_id == self.account_id,
                    PaperTrade.status == "OPEN",
                ).order_by(PaperTrade.entry_at)
            )
        )

    def trade_history(self) -> list[PaperTrade]:
        return list(
            self.session.scalars(
                select(PaperTrade).where(
                    PaperTrade.account_id == self.account_id
                ).order_by(PaperTrade.entry_at.desc())
            )
        )

    def cash_balance(self) -> Decimal:
        return self._account().cash_balance

    def equity(self, quotes: dict[tuple[str, str], OptionQuote], *, now: datetime) -> Decimal:
        """Mark open long positions conservatively at bid; missing/stale quotes fail closed."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        value = self.cash_balance()
        for trade in self.open_trades():
            quote = quotes.get((trade.exchange, trade.tradingsymbol))
            if quote is None:
                raise ValueError(f"missing mark quote for {trade.tradingsymbol}")
            self._validate_quote(quote, now=now)
            if quote.best_bid is None:
                raise ValueError(f"missing bid for {trade.tradingsymbol}")
            position_value = (quote.best_bid * trade.quantity).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            value += position_value
        return value
