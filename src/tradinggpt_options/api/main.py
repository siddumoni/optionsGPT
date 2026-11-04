from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from sqlalchemy import select

from tradinggpt_options import __version__
from tradinggpt_options.config.settings import Settings, get_settings
from tradinggpt_options.storage.database import (
    build_engine,
    build_session_factory,
    create_schema,
)
from tradinggpt_options.storage.tables import PaperAccount, PaperTrade


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    engine = build_engine(app_settings.database_url)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        create_schema(engine)
        yield
        engine.dispose()

    application = FastAPI(
        title=app_settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str | bool]:
        return {
            "status": "ok",
            "application": app_settings.app_name,
            "version": __version__,
            "trading_mode": app_settings.trading_mode,
            "live_trading_enabled": False,
        }

    def decimal_string(value: Decimal) -> str:
        return format(value, "f")

    @application.get("/api/v1/paper/account", tags=["paper"])
    def paper_account() -> dict[str, Any]:
        """Read the persistent paper account. Does not create or place trades."""
        with session_factory() as session:
            account = session.scalar(
                select(PaperAccount).where(PaperAccount.name == "default")
            )
            if account is None:
                raise HTTPException(
                    status_code=404,
                    detail="Paper account has not been initialized",
                )
            open_positions = list(
                session.scalars(
                    select(PaperTrade).where(
                        PaperTrade.account_id == account.id,
                        PaperTrade.status == "OPEN",
                    )
                )
            )
            closed_trades = list(
                session.scalars(
                    select(PaperTrade).where(
                        PaperTrade.account_id == account.id,
                        PaperTrade.status == "CLOSED",
                    )
                )
            )
            realized = sum(
                (trade.net_pnl for trade in closed_trades),
                Decimal("0"),
            )
            return {
                "mode": "PAPER",
                "account": account.name,
                "initial_capital": decimal_string(account.initial_capital),
                "cash_balance": decimal_string(account.cash_balance),
                "realized_net_pnl": decimal_string(realized),
                "open_positions": len(open_positions),
                "closed_trades": len(closed_trades),
                "live_trading_enabled": False,
            }

    @application.get("/api/v1/paper/trades", tags=["paper"])
    def paper_trades(status: str = "all") -> list[dict[str, Any]]:
        """Return paper trade history, optionally filtered to open or closed trades."""
        normalized = status.lower()
        if normalized not in {"all", "open", "closed"}:
            raise HTTPException(
                status_code=422,
                detail="status must be all, open, or closed",
            )
        with session_factory() as session:
            account = session.scalar(
                select(PaperAccount).where(PaperAccount.name == "default")
            )
            if account is None:
                return []
            statement = select(PaperTrade).where(
                PaperTrade.account_id == account.id
            )
            if normalized != "all":
                statement = statement.where(
                    PaperTrade.status == normalized.upper()
                )
            trades = session.scalars(
                statement.order_by(PaperTrade.entry_at.desc())
            ).all()
            return [
                {
                    "trade_id": trade.id,
                    "exchange": trade.exchange,
                    "tradingsymbol": trade.tradingsymbol,
                    "underlying": trade.underlying,
                    "expiry": trade.expiry.isoformat(),
                    "strike": decimal_string(trade.strike),
                    "option_type": trade.option_type,
                    "lot_size": trade.lot_size,
                    "quantity": trade.quantity,
                    "entry_premium": decimal_string(trade.entry_premium),
                    "exit_premium": (
                        decimal_string(trade.exit_premium)
                        if trade.exit_premium is not None else None
                    ),
                    "entry_at": trade.entry_at.isoformat(),
                    "exit_at": (
                        trade.exit_at.isoformat() if trade.exit_at else None
                    ),
                    "status": trade.status,
                    "gross_pnl": decimal_string(trade.gross_pnl),
                    "charges": decimal_string(trade.charges),
                    "net_pnl": decimal_string(trade.net_pnl),
                    "entry_reason": trade.entry_reason,
                    "exit_reason": trade.exit_reason,
                }
                for trade in trades
            ]

    return application


app = create_app()
