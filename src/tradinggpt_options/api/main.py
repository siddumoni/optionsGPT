from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from tradinggpt_options import __version__
from tradinggpt_options.config.settings import Settings, get_settings
from tradinggpt_options.storage.database import (
    build_engine,
    build_session_factory,
    create_schema,
)
from tradinggpt_options.storage.tables import (
    InstrumentSnapshot,
    PaperAccount,
    PaperTrade,
    QuoteSnapshot,
)


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

    @application.get("/dashboard", include_in_schema=False)
    def dashboard() -> FileResponse:
        dashboard_path = (
            Path(__file__).resolve().parents[3] / "web" / "dashboard.html"
        )
        if not dashboard_path.is_file():
            raise HTTPException(status_code=404, detail="dashboard asset not found")
        return FileResponse(dashboard_path)

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

    def datetime_string(value: datetime | None) -> str | None:
        if value is None:
            return None
        # SQLite drops tzinfo for DateTime columns; all application writes are UTC.
        normalized = (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )
        return normalized.isoformat()

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
                    "entry_at": datetime_string(trade.entry_at),
                    "exit_at": datetime_string(trade.exit_at),
                    "status": trade.status,
                    "gross_pnl": decimal_string(trade.gross_pnl),
                    "charges": decimal_string(trade.charges),
                    "entry_charges": json.loads(trade.entry_charges_json),
                    "exit_charges": json.loads(trade.exit_charges_json),
                    "net_pnl": decimal_string(trade.net_pnl),
                    "entry_reason": trade.entry_reason,
                    "exit_reason": trade.exit_reason,
                }
                for trade in trades
            ]


    @application.get("/api/v1/market/instruments", tags=["market-data"])
    def market_instruments(underlying: str | None = None) -> list[dict[str, Any]]:
        """Read the latest persisted NFO option instrument-master snapshot."""
        with session_factory() as session:
            latest_date = select(
                func.max(InstrumentSnapshot.snapshot_date)
            ).scalar_subquery()
            statement = select(InstrumentSnapshot).where(
                InstrumentSnapshot.snapshot_date == latest_date
            )
            if underlying:
                statement = statement.where(
                    InstrumentSnapshot.underlying == underlying.strip().upper()
                )
            rows = session.scalars(
                statement.order_by(
                    InstrumentSnapshot.underlying,
                    InstrumentSnapshot.expiry,
                    InstrumentSnapshot.strike,
                    InstrumentSnapshot.option_type,
                )
            ).all()
            return [
                {
                    "snapshot_date": row.snapshot_date.isoformat(),
                    "exchange": row.exchange,
                    "tradingsymbol": row.tradingsymbol,
                    "instrument_token": row.instrument_token,
                    "underlying": row.underlying,
                    "expiry": row.expiry.isoformat(),
                    "strike": decimal_string(row.strike),
                    "option_type": row.option_type,
                    "lot_size": row.lot_size,
                    "tick_size": decimal_string(row.tick_size),
                }
                for row in rows
            ]

    @application.get("/api/v1/market/quotes", tags=["market-data"])
    def market_quotes(limit: int = 100) -> list[dict[str, Any]]:
        """Return the latest persisted quote per contract, including full depth."""
        if not 1 <= limit <= 500:
            raise HTTPException(
                status_code=422,
                detail="limit must be between 1 and 500",
            )
        ranked = (
            select(
                QuoteSnapshot.id.label("quote_id"),
                func.row_number()
                .over(
                    partition_by=(
                        QuoteSnapshot.exchange,
                        QuoteSnapshot.tradingsymbol,
                    ),
                    order_by=(
                        QuoteSnapshot.received_at.desc(),
                        QuoteSnapshot.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .subquery()
        )
        with session_factory() as session:
            rows = session.scalars(
                select(QuoteSnapshot)
                .join(ranked, QuoteSnapshot.id == ranked.c.quote_id)
                .where(ranked.c.row_number == 1)
                .order_by(QuoteSnapshot.received_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "exchange": row.exchange,
                    "tradingsymbol": row.tradingsymbol,
                    "instrument_token": row.instrument_token,
                    "exchange_timestamp": datetime_string(row.exchange_timestamp),
                    "received_at": datetime_string(row.received_at),
                    "last_price": (
                        decimal_string(row.last_price)
                        if row.last_price is not None else None
                    ),
                    "best_bid": (
                        decimal_string(row.best_bid)
                        if row.best_bid is not None else None
                    ),
                    "best_ask": (
                        decimal_string(row.best_ask)
                        if row.best_ask is not None else None
                    ),
                    "bid_depth": json.loads(row.bid_depth_json),
                    "ask_depth": json.loads(row.ask_depth_json),
                    "volume": row.volume,
                    "open_interest": row.open_interest,
                    "source": row.source,
                    "quality_flags": [
                        flag for flag in row.quality_flags.split(";") if flag
                    ],
                }
                for row in rows
            ]

    return application


app = create_app()
