from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint
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
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    best_bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    best_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    bid_quantity: Mapped[int | None] = mapped_column(Integer)
    ask_quantity: Mapped[int | None] = mapped_column(Integer)
    volume: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="kite")
    quality_flags: Mapped[str] = mapped_column(String(512), default="")
