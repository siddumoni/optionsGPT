from __future__ import annotations

from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradinggpt_options.data.models import OptionContract, OptionQuote
from tradinggpt_options.storage.tables import InstrumentSnapshot, QuoteSnapshot


class MarketDataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_instrument_master(self, contracts: tuple[OptionContract, ...], *, snapshot_date: date) -> int:
        saved = 0
        for contract in contracts:
            existing = self.session.scalar(
                select(InstrumentSnapshot).where(
                    InstrumentSnapshot.snapshot_date == snapshot_date,
                    InstrumentSnapshot.exchange == contract.exchange,
                    InstrumentSnapshot.tradingsymbol == contract.tradingsymbol,
                )
            )
            if existing is None:
                self.session.add(InstrumentSnapshot(
                    snapshot_date=snapshot_date,
                    exchange=contract.exchange,
                    tradingsymbol=contract.tradingsymbol,
                    instrument_token=contract.instrument_token,
                    underlying=contract.underlying,
                    expiry=contract.expiry,
                    strike=contract.strike,
                    option_type=contract.option_type,
                    lot_size=contract.lot_size,
                    tick_size=contract.tick_size,
                ))
                saved += 1
        self.session.commit()
        return saved

    def save_quote(self, quote: OptionQuote, *, quality_flags: tuple[str, ...] = ()) -> int:
        row = QuoteSnapshot(
            exchange=quote.exchange,
            tradingsymbol=quote.tradingsymbol,
            instrument_token=quote.instrument_token,
            exchange_timestamp=quote.exchange_timestamp,
            received_at=quote.received_at,
            last_price=quote.last_price,
            best_bid=quote.best_bid,
            best_ask=quote.best_ask,
            bid_quantity=quote.bid[0].quantity if quote.bid else None,
            ask_quantity=quote.ask[0].quantity if quote.ask else None,
            volume=quote.volume,
            open_interest=quote.open_interest,
            source=quote.source,
            quality_flags=";".join(quality_flags),
        )
        self.session.add(row)
        self.session.commit()
        return row.id
