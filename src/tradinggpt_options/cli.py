from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from tradinggpt_options.config.settings import Settings, get_settings
from tradinggpt_options.data.collector import KiteOptionsCollector
from tradinggpt_options.data.kite_adapter import (
    KiteMarketDataAdapter,
    create_kite_ticker,
)
from tradinggpt_options.execution.paper_broker import PaperBroker, PaperExecutionConfig
from tradinggpt_options.options.chain import select_near_atm_contracts
from tradinggpt_options.storage.database import build_engine, build_session_factory, create_schema
from tradinggpt_options.storage.repository import MarketDataRepository

MARKET_TIMEZONE = ZoneInfo("Asia/Kolkata")


def initialize_paper_account() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        create_schema(engine)
        factory = build_session_factory(engine)
        with factory() as session:
            broker = PaperBroker(
                session,
                account_name="default",
                config=PaperExecutionConfig(
                    initial_capital=Decimal(str(settings.paper_initial_capital))
                ),
            )
            print("Paper account initialized.")
            print("Account: default")
            print(f"Cash balance: INR {broker.cash_balance():,.2f}")
            print("Trading mode: PAPER (no live order functionality)")
    finally:
        engine.dispose()


def _parse_spot_instrument_mappings(raw: str) -> dict[str, tuple[str, str]]:
    mappings: dict[str, tuple[str, str]] = {}
    for entry in raw.split(";"):
        if not entry.strip():
            continue
        if "=" not in entry:
            raise ValueError(
                "spot mapping entries must use UNDERLYING=EXCHANGE:TRADINGSYMBOL"
            )
        underlying, instrument = entry.split("=", maxsplit=1)
        if ":" not in instrument:
            raise ValueError(
                "spot mapping entries must use UNDERLYING=EXCHANGE:TRADINGSYMBOL"
            )
        exchange, symbol = instrument.split(":", maxsplit=1)
        key = underlying.strip().upper()
        exchange = exchange.strip().upper()
        symbol = symbol.strip().upper()
        if not key or not exchange or not symbol:
            raise ValueError("spot mapping entries cannot contain empty values")
        if key in mappings:
            raise ValueError(f"duplicate spot mapping for {key}")
        mappings[key] = (exchange, symbol)
    if not mappings:
        raise ValueError(
            "KITE_UNDERLYING_SPOT_INSTRUMENTS must be configured before collection"
        )
    return mappings


def _build_kite_rest_client(settings: Settings):
    if not settings.kite_api_key.strip() or not settings.kite_access_token.strip():
        raise RuntimeError(
            "Set KITE_API_KEY and KITE_ACCESS_TOKEN in your local .env first"
        )
    try:
        from kiteconnect import KiteConnect
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise RuntimeError("Install kiteconnect to use live market data") from exc
    client = KiteConnect(api_key=settings.kite_api_key)
    client.set_access_token(settings.kite_access_token)
    return client


def _parse_aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "use ISO format with timezone, e.g. 2026-11-04T09:15:00+05:30"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("datetime must include a timezone offset")
    return parsed


def backfill_underlying_candles(
    *,
    settings: Settings,
    requested_underlyings: tuple[str, ...],
    from_date: datetime,
    to_date: datetime,
    interval: str,
) -> None:
    mappings = _parse_spot_instrument_mappings(
        settings.kite_underlying_spot_instruments
    )
    underlyings = tuple(
        dict.fromkeys(item.strip().upper() for item in requested_underlyings if item.strip())
    )
    if not underlyings:
        raise ValueError("at least one underlying must be selected")
    unmapped = sorted(set(underlyings) - set(mappings))
    if unmapped:
        raise ValueError(
            "missing spot instrument mappings for: " + ", ".join(unmapped)
        )

    client = _build_kite_rest_client(settings)
    adapter = KiteMarketDataAdapter(client)
    instruments = [mappings[item] for item in underlyings]
    snapshot = adapter.fetch_full_quotes(instruments)
    if snapshot.missing_symbols:
        raise RuntimeError(
            "Kite did not return instrument tokens for: "
            + ", ".join(snapshot.missing_symbols)
        )
    quotes = {
        (quote.exchange, quote.tradingsymbol): quote
        for quote in snapshot.quotes
    }

    engine = build_engine(settings.database_url)
    try:
        create_schema(engine)
        factory = build_session_factory(engine)
        total_saved = 0
        with factory() as session:
            repository = MarketDataRepository(session)
            for underlying in underlyings:
                exchange, symbol = mappings[underlying]
                quote = quotes.get((exchange, symbol))
                if quote is None:
                    raise RuntimeError(f"missing instrument token for {underlying}")
                candles = adapter.fetch_historical_candles(
                    exchange=exchange,
                    tradingsymbol=symbol,
                    instrument_token=quote.instrument_token,
                    from_date=from_date,
                    to_date=to_date,
                    interval=interval,
                    include_oi=True,
                )
                saved = repository.save_candles(candles)
                total_saved += saved
                print(
                    f"{underlying} ({exchange}:{symbol}): "
                    f"fetched={len(candles)} new_saved={saved}"
                )
        print(
            f"Historical underlying candle backfill complete. "
            f"New rows saved: {total_saved}"
        )
    finally:
        engine.dispose()


def collect_options(
    *,
    settings: Settings,
    requested_underlyings: tuple[str, ...],
    strikes_each_side: int,
) -> None:
    if strikes_each_side < 0:
        raise ValueError("strikes_each_side cannot be negative")

    mappings = _parse_spot_instrument_mappings(
        settings.kite_underlying_spot_instruments
    )
    underlyings = tuple(
        dict.fromkeys(item.strip().upper() for item in requested_underlyings if item.strip())
    )
    if not underlyings:
        raise ValueError("at least one underlying must be selected")
    unmapped = sorted(set(underlyings) - set(mappings))
    if unmapped:
        raise ValueError(
            "missing spot instrument mappings for: " + ", ".join(unmapped)
        )

    kite = _build_kite_rest_client(settings)
    adapter = KiteMarketDataAdapter(kite)

    engine = build_engine(settings.database_url)
    collector: KiteOptionsCollector | None = None
    try:
        create_schema(engine)
        session_factory = build_session_factory(engine)
        collector = KiteOptionsCollector(
            adapter=adapter,
            session_factory=session_factory,
        )

        market_date = datetime.now(MARKET_TIMEZONE).date()
        contracts = collector.load_daily_instrument_master(
            underlyings=set(underlyings),
            snapshot_date=market_date,
        )
        spot_instruments = [mappings[item] for item in underlyings]
        spot_snapshot = adapter.fetch_full_quotes(spot_instruments)
        if spot_snapshot.missing_symbols:
            raise RuntimeError(
                "Kite did not return spot quotes for: "
                + ", ".join(spot_snapshot.missing_symbols)
            )

        now = datetime.now(UTC)
        spot_prices: dict[str, Decimal] = {}
        quotes_by_symbol = {
            (quote.exchange, quote.tradingsymbol): quote
            for quote in spot_snapshot.quotes
        }
        for underlying in underlyings:
            exchange, symbol = mappings[underlying]
            quote = quotes_by_symbol.get((exchange, symbol))
            if quote is None or quote.last_price is None or quote.last_price <= 0:
                raise RuntimeError(f"missing valid spot price for {underlying}")
            observed_at = quote.exchange_timestamp or quote.received_at
            age_seconds = (now - observed_at).total_seconds()
            if age_seconds < -5 or age_seconds > 30:
                raise RuntimeError(
                    f"spot quote for {underlying} is outside the 30-second freshness window"
                )
            spot_prices[underlying] = quote.last_price

        selected = select_near_atm_contracts(
            contracts,
            spot_prices=spot_prices,
            as_of=market_date,
            strikes_each_side=strikes_each_side,
        )
        if not selected:
            raise RuntimeError(
                "No near-ATM option contracts selected; check the underlying names "
                "and the daily instrument master"
            )

        ticker = create_kite_ticker(
            settings.kite_api_key,
            settings.kite_access_token,
        )
        tokens = collector.start(ticker=ticker, contracts=selected)
        print("TradingGPT Options live market-data collector started.")
        print("Mode: PAPER / READ-ONLY MARKET DATA")
        print("No broker order-placement methods are available.")
        print(f"Market date: {market_date.isoformat()}")
        print(f"Underlyings: {', '.join(underlyings)}")
        print(f"Valid contracts in master: {len(contracts)}")
        print(f"Selected near-ATM contracts: {len(selected)}")
        print(f"Subscribed instrument tokens: {len(tokens)}")
        print("Press Ctrl+C to stop collection.")

        next_report = time.monotonic()
        while True:
            time.sleep(1)
            if time.monotonic() >= next_report:
                status = collector.status()
                print(
                    f"[{datetime.now(MARKET_TIMEZONE):%H:%M:%S}] "
                    f"state={status.state} ticks={status.received_ticks} "
                    f"saved={status.persisted_quotes} rejected={status.rejected_ticks} "
                    f"unknown={status.unknown_tokens} error={status.last_error or '-'}"
                )
                next_report = time.monotonic() + 30
    except KeyboardInterrupt:
        print("Stopping options market-data collector...")
    finally:
        if collector is not None:
            collector.stop()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="tradinggpt-options")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "init-paper-account",
        help="Initialize the persistent local paper account",
    )
    collect_parser = subparsers.add_parser(
        "collect-options",
        help="Collect read-only Kite option quotes for near-ATM contracts",
    )
    collect_parser.add_argument(
        "--underlyings",
        default="",
        help="Comma-separated NFO underlying names; defaults to configured spot mappings",
    )
    collect_parser.add_argument(
        "--strikes-each-side",
        type=int,
        default=3,
        help="Number of strikes below and above ATM to subscribe (default: 3)",
    )
    backfill_parser = subparsers.add_parser(
        "backfill-underlying",
        help="Download and persist historical underlying OHLCV candles",
    )
    backfill_parser.add_argument(
        "--underlyings",
        default="",
        help="Comma-separated underlyings; defaults to configured spot mappings",
    )
    backfill_parser.add_argument(
        "--from-date",
        required=True,
        type=_parse_aware_datetime,
        help="Timezone-aware ISO timestamp, e.g. 2026-11-04T09:15:00+05:30",
    )
    backfill_parser.add_argument(
        "--to-date",
        required=True,
        type=_parse_aware_datetime,
        help="Timezone-aware ISO timestamp, e.g. 2026-11-04T15:30:00+05:30",
    )
    backfill_parser.add_argument(
        "--interval",
        choices=(
            "minute",
            "3minute",
            "5minute",
            "10minute",
            "15minute",
            "30minute",
            "60minute",
            "day",
        ),
        default="5minute",
    )
    args = parser.parse_args()

    if args.command == "init-paper-account":
        initialize_paper_account()
    elif args.command == "collect-options":
        settings = get_settings()
        configured = _parse_spot_instrument_mappings(
            settings.kite_underlying_spot_instruments
        )
        underlyings = (
            tuple(item.strip().upper() for item in args.underlyings.split(",") if item.strip())
            if args.underlyings
            else tuple(configured)
        )
        collect_options(
            settings=settings,
            requested_underlyings=underlyings,
            strikes_each_side=args.strikes_each_side,
        )
    elif args.command == "backfill-underlying":
        settings = get_settings()
        configured = _parse_spot_instrument_mappings(
            settings.kite_underlying_spot_instruments
        )
        underlyings = (
            tuple(item.strip().upper() for item in args.underlyings.split(",") if item.strip())
            if args.underlyings
            else tuple(configured)
        )
        backfill_underlying_candles(
            settings=settings,
            requested_underlyings=underlyings,
            from_date=args.from_date,
            to_date=args.to_date,
            interval=args.interval,
        )


if __name__ == "__main__":
    main()
