from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tradinggpt_options.storage.database import Base


class InstrumentSnapshot(Base):
    __tablename__ = "instrument_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", "exchange", "tradingsymbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    exchange: Mapped[str] = mapped_column(String(12), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(64), index=True)
    instrument_token: Mapped[int] = mapped_column(Integer)
    underlying: Mapped[str] = mapped_column(String(64), index=True)
    expiry: Mapped[date] = mapped_column(Date, index=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    option_type: Mapped[str] = mapped_column(String(2))
    lot_size: Mapped[int] = mapped_column(Integer)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(12, 4))


class QuoteSnapshot(Base):
    __tablename__ = "quote_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(12), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(64), index=True)
    instrument_token: Mapped[int] = mapped_column(Integer)
    exchange_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    best_bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    best_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    bid_quantity: Mapped[int | None] = mapped_column(Integer)
    ask_quantity: Mapped[int | None] = mapped_column(Integer)
    bid_depth_json: Mapped[str] = mapped_column(Text, default="[]")
    ask_depth_json: Mapped[str] = mapped_column(Text, default="[]")
    volume: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="kite")
    quality_flags: Mapped[str] = mapped_column(String(512), default="")


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    exchange: Mapped[str] = mapped_column(String(12))
    tradingsymbol: Mapped[str] = mapped_column(String(64), index=True)
    underlying: Mapped[str] = mapped_column(String(64), index=True)
    expiry: Mapped[date] = mapped_column(Date)
    strike: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    option_type: Mapped[str] = mapped_column(String(2))
    lot_size: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    entry_premium: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    exit_premium: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), index=True)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    charges: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    entry_charges_json: Mapped[str] = mapped_column(Text, default="{}")
    exit_charges_json: Mapped[str] = mapped_column(Text, default="{}")
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    entry_reason: Mapped[str] = mapped_column(String(2048), default="")
    exit_reason: Mapped[str] = mapped_column(String(2048), default="")



class CandleSnapshot(Base):
    __tablename__ = "candle_snapshots"
    __table_args__ = (
        UniqueConstraint("exchange", "tradingsymbol", "interval", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(12), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(64), index=True)
    instrument_token: Mapped[int] = mapped_column(Integer)
    interval: Mapped[str] = mapped_column(String(12), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)
