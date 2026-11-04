import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tradinggpt_options.data.models import DepthLevel, OptionContract, OptionQuote
from tradinggpt_options.execution.paper_broker import PaperBroker, PaperExecutionConfig
from tradinggpt_options.storage.database import Base


def setup_broker(
    *, charges_per_side: Decimal | None = Decimal("0")
) -> tuple[PaperBroker, OptionContract, datetime]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    broker = PaperBroker(
        session,
        account_name="unit-test",
        config=PaperExecutionConfig(
            initial_capital=Decimal("100000"),
            charges_per_side=charges_per_side,
        ),
    )
    contract = OptionContract(
        exchange="NFO",
        tradingsymbol="NIFTY26NOV25000CE",
        instrument_token=123,
        underlying="NIFTY",
        expiry=date(2026, 11, 26),
        strike=Decimal("25000"),
        option_type="CE",
        lot_size=65,
        tick_size=Decimal("0.05"),
    )
    return broker, contract, now


def quote(contract: OptionContract, now: datetime, bid: str, ask: str) -> OptionQuote:
    return OptionQuote(
        exchange=contract.exchange,
        tradingsymbol=contract.tradingsymbol,
        instrument_token=contract.instrument_token,
        exchange_timestamp=now,
        received_at=now,
        last_price=Decimal(ask),
        bid=(DepthLevel(Decimal(bid), 500),),
        ask=(DepthLevel(Decimal(ask), 500),),
        volume=1000,
        open_interest=20000,
    )


def test_paper_buy_at_ask_and_sell_at_bid_updates_ledger() -> None:
    broker, contract, now = setup_broker()
    entry = broker.buy_to_open(
        contract=contract,
        quote=quote(contract, now, "99.90", "100.10"),
        lots=1,
        now=now,
        reason="unit-test entry",
    )
    assert entry.status == "OPEN"
    assert entry.quantity == 65
    assert entry.price == Decimal("100.10")
    assert entry.cash_balance == Decimal("93493.50")

    exit_fill = broker.sell_to_close(
        trade_id=entry.trade_id,
        quote=quote(contract, now + timedelta(minutes=5), "104.90", "105.10"),
        now=now + timedelta(minutes=5),
        reason="unit-test exit",
    )
    assert exit_fill.status == "CLOSED"
    assert exit_fill.price == Decimal("104.90")
    assert exit_fill.cash_balance == Decimal("100312.00")
    trade = broker.trade_history()[0]
    assert trade.gross_pnl == Decimal("312.00")
    assert trade.net_pnl == Decimal("312.00")


def test_paper_rejects_stale_quote() -> None:
    broker, contract, now = setup_broker()
    stale = quote(contract, now - timedelta(minutes=2), "99.9", "100.1")
    with pytest.raises(ValueError, match="stale"):
        broker.buy_to_open(contract=contract, quote=stale, lots=1, now=now)


def test_paper_rejects_missing_bid_or_ask() -> None:
    broker, contract, now = setup_broker()
    no_bid = OptionQuote(
        exchange="NFO",
        tradingsymbol=contract.tradingsymbol,
        instrument_token=123,
        exchange_timestamp=now,
        received_at=now,
        last_price=Decimal("100"),
        bid=(),
        ask=(DepthLevel(Decimal("100.1"), 20),),
        volume=10,
        open_interest=20,
    )
    with pytest.raises(ValueError, match="two-sided"):
        broker.buy_to_open(contract=contract, quote=no_bid, lots=1, now=now)


def test_paper_rejects_duplicate_open_contract() -> None:
    broker, contract, now = setup_broker()
    q = quote(contract, now, "99.9", "100.1")
    broker.buy_to_open(contract=contract, quote=q, lots=1, now=now)
    with pytest.raises(ValueError, match="already exists"):
        broker.buy_to_open(contract=contract, quote=q, lots=1, now=now)


def test_paper_rejects_insufficient_cash_and_bad_lots() -> None:
    broker, contract, now = setup_broker()
    q = quote(contract, now, "1599.9", "1600.1")
    with pytest.raises(ValueError, match="insufficient"):
        broker.buy_to_open(contract=contract, quote=q, lots=1, now=now)
    with pytest.raises(ValueError, match="at least one"):
        broker.buy_to_open(
            contract=contract,
            quote=quote(contract, now, "99.9", "100.1"),
            lots=0,
            now=now,
        )


def test_equity_marks_open_option_at_bid_and_requires_fresh_quote() -> None:
    broker, contract, now = setup_broker()
    entry_quote = quote(contract, now, "99.90", "100.10")
    broker.buy_to_open(
        contract=contract,
        quote=entry_quote,
        lots=1,
        now=now,
    )
    current_quote = quote(contract, now + timedelta(minutes=1), "105.00", "105.20")
    assert broker.equity(
        {(contract.exchange, contract.tradingsymbol): current_quote},
        now=now + timedelta(minutes=1),
    ) == Decimal("100318.50")

    stale_quote = quote(contract, now - timedelta(minutes=1), "105.00", "105.20")
    with pytest.raises(ValueError, match="stale"):
        broker.equity(
            {(contract.exchange, contract.tradingsymbol): stale_quote},
            now=now + timedelta(minutes=1),
        )


def test_paper_broker_applies_versioned_zerodha_option_charges() -> None:
    broker, contract, now = setup_broker(charges_per_side=None)
    entry = broker.buy_to_open(
        contract=contract,
        quote=quote(contract, now, "99.90", "100.10"),
        lots=1,
        now=now,
    )
    assert entry.cash_balance == Decimal("93466.96")
    trade = broker.trade_history()[0]
    assert trade.charges == Decimal("26.54")
    entry_breakdown = json.loads(trade.entry_charges_json)
    assert entry_breakdown["schedule_version"] == "zerodha-nse-options-2026-04-01"
    assert entry_breakdown["stamp_duty"] == "0.20"
    assert entry_breakdown["stt"] == "0.00"

    exit_fill = broker.sell_to_close(
        trade_id=entry.trade_id,
        quote=quote(contract, now + timedelta(minutes=5), "104.90", "105.10"),
        now=now + timedelta(minutes=5),
    )
    assert exit_fill.cash_balance == Decimal("100248.76")
    trade = broker.trade_history()[0]
    assert trade.charges == Decimal("63.24")
    assert trade.gross_pnl == Decimal("312.00")
    assert trade.net_pnl == Decimal("248.76")
    exit_breakdown = json.loads(trade.exit_charges_json)
    assert exit_breakdown["stt"] == "10.23"
    assert exit_breakdown["stamp_duty"] == "0.00"
