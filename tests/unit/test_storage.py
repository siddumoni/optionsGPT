from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tradinggpt_options.data.models import DepthLevel, OptionContract, OptionQuote
from tradinggpt_options.storage.database import Base
from tradinggpt_options.storage.repository import MarketDataRepository
from tradinggpt_options.storage.tables import InstrumentSnapshot, QuoteSnapshot


def test_market_data_repository_persists_contract_and_quote() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    contract = OptionContract(
        exchange="NFO", tradingsymbol="NIFTY26NOV25000CE", instrument_token=123,
        underlying="NIFTY", expiry=date(2026, 11, 26), strike=Decimal("25000"),
        option_type="CE", lot_size=65, tick_size=Decimal("0.05"),
    )
    quote = OptionQuote(
        exchange="NFO", tradingsymbol=contract.tradingsymbol, instrument_token=123,
        exchange_timestamp=None, received_at=datetime.now(timezone.utc),
        last_price=Decimal("100"), bid=(DepthLevel(Decimal("99.9"), 10),),
        ask=(DepthLevel(Decimal("100.1"), 20),), volume=100, open_interest=500,
    )
    with Session(engine) as session:
        repo = MarketDataRepository(session)
        assert repo.save_instrument_master((contract,), snapshot_date=date(2026, 11, 4)) == 1
        assert repo.save_instrument_master((contract,), snapshot_date=date(2026, 11, 4)) == 0
        repo.save_quote(quote, quality_flags=("fresh",))
        assert session.scalar(select(InstrumentSnapshot).where(InstrumentSnapshot.tradingsymbol == contract.tradingsymbol))
        stored = session.scalar(select(QuoteSnapshot).where(QuoteSnapshot.tradingsymbol == contract.tradingsymbol))
        assert stored is not None
        assert stored.best_bid == Decimal("99.9")
