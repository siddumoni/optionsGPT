from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradinggpt_options.data.models import OptionContract, OptionQuote, assess_quote_quality
from tradinggpt_options.storage.tables import PaperAccount, PaperTrade


@dataclass(frozen=True, slots=True)
class PaperExecutionConfig:
    initial_capital: Decimal = Decimal("100000")
    max_quote_age_seconds: int = 15
    charges_per_side: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be positive")
        if self.charges_per_side < 0:
            raise ValueError("charges_per_side cannot be negative")


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

    Entry uses best ask; exit uses best bid. If depth is missing, stale or crossed,
    execution is rejected. Fees are configurable placeholders until the versioned
    statutory charge schedule is implemented and independently verified.
    """

    def __init__(self, session: Session, *, account_name: str, config: PaperExecutionConfig) -> None:
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
        ask = quote.best_ask
        if ask is None:
            raise ValueError("best ask is required")
        notional = (ask * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_debit = notional + self.config.charges_per_side
        account = self._account()
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
                charges=self.config.charges_per_side,
                net_pnl=Decimal("0"),
                entry_reason=reason[:2048],
            )
        )
        self.session.commit()
        return PaperFill(
            trade_id, "OPEN", quantity, ask, account.cash_balance,
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

        bid = quote.best_bid
        if bid is None:
            raise ValueError("best bid is required")
        gross_pnl = ((bid - trade.entry_premium) * trade.quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        exit_charge = self.config.charges_per_side
        trade.charges += exit_charge
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
            trade.id, "CLOSED", trade.quantity, bid, account.cash_balance,
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
