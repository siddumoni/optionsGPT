from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradinggpt_options.data.models import OptionContract, OptionQuote
from tradinggpt_options.storage.tables import InstrumentSnapshot, QuoteSnapshot


class MarketDataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_instrument_master(
        self,
        contracts: tuple[OptionContract, ...],
        *,
        snapshot_date: date,
    ) -> int:
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
                self.session.add(
                    InstrumentSnapshot(
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
                    )
                )
                saved += 1
        self.session.commit()
        return saved

    def save_quotes(
        self,
        quotes: tuple[OptionQuote, ...],
        *,
        quality_flags: tuple[tuple[str, ...], ...] | None = None,
    ) -> int:
        if not quotes:
            return 0
        flags = quality_flags or tuple(() for _ in quotes)
        if len(flags) != len(quotes):
            raise ValueError("quality_flags must have the same length as quotes")
        rows = [
            QuoteSnapshot(
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
                bid_depth_json=json.dumps(
                    [
                        {
                            "price": str(level.price),
                            "quantity": level.quantity,
                            "orders": level.orders,
                        }
                        for level in quote.bid
                    ],
                    separators=(",", ":"),
                ),
                ask_depth_json=json.dumps(
                    [
                        {
                            "price": str(level.price),
                            "quantity": level.quantity,
                            "orders": level.orders,
                        }
                        for level in quote.ask
                    ],
                    separators=(",", ":"),
                ),
                volume=quote.volume,
                open_interest=quote.open_interest,
                source=quote.source,
                quality_flags=";".join(flags[index]),
            )
            for index, quote in enumerate(quotes)
        ]
        self.session.add_all(rows)
        self.session.commit()
        return len(rows)

    def save_quote(
        self,
        quote: OptionQuote,
        *,
        quality_flags: tuple[str, ...] = (),
    ) -> int:
        self.save_quotes((quote,), quality_flags=(quality_flags,))
        return 1
