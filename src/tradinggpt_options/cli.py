from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from tradinggpt_options.config.settings import Settings, get_settings
from tradinggpt_options.data.collector import KiteOptionsCollector
from tradinggpt_options.data.instrument_master import parse_kite_futures_instruments
from tradinggpt_options.data.kite_adapter import (
    KiteMarketDataAdapter,
    create_kite_ticker,
)
from tradinggpt_options.data.models import assess_quote_quality
from tradinggpt_options.execution.paper_broker import PaperBroker, PaperExecutionConfig
from tradinggpt_options.options.chain import (
    select_near_atm_contracts,
    select_nearest_expiry,
    select_nearest_future_contract,
)
from tradinggpt_options.options.chain_analytics import build_option_chain_view
from tradinggpt_options.research.baseline import (
    BaselineStrategyConfig,
    analyze_baseline,
)
from tradinggpt_options.storage.database import build_engine, build_session_factory, create_schema
from tradinggpt_options.storage.repository import MarketDataRepository
from tradinggpt_options.storage.tables import StrategyDecisionSnapshot

MARKET_TIMEZONE = ZoneInfo("Asia/Kolkata")


def _option_selection_date(market_now: datetime):
    if market_now.tzinfo is None or market_now.utcoffset() is None:
        raise ValueError("market_now must be timezone-aware")
    local_now = market_now.astimezone(MARKET_TIMEZONE)
    if local_now.time() >= datetime_time(hour=15, minute=30):
        return local_now.date() + timedelta(days=1)
    return local_now.date()


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


def _build_kite_client(settings: Settings):
    if not settings.kite_api_key.strip():
        raise RuntimeError("Set KITE_API_KEY in your local .env first")
    try:
        from kiteconnect import KiteConnect
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise RuntimeError("Install kiteconnect to use Kite Connect authentication") from exc
    return KiteConnect(api_key=settings.kite_api_key)


def print_kite_login_url(settings: Settings) -> None:
    client = _build_kite_client(settings)
    print("Open this URL and complete Zerodha login:")
    print(client.login_url())


def exchange_kite_request_token(
    settings: Settings,
    *,
    request_token: str,
) -> None:
    if not settings.kite_api_secret.strip():
        raise RuntimeError("Set KITE_API_SECRET in your local .env first")
    if not request_token.strip():
        raise ValueError("request_token cannot be empty")
    client = _build_kite_client(settings)
    session_data = client.generate_session(
        request_token,
        api_secret=settings.kite_api_secret,
    )
    access_token = session_data.get("access_token")
    if not access_token:
        raise RuntimeError("Kite did not return an access token")
    print("Access token generated. Copy it into KITE_ACCESS_TOKEN in your local .env:")
    print(access_token)
    print("Do not commit .env or share this token. Kite access tokens are short-lived.")


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
    underlyings = tuple(
        dict.fromkeys(item.strip().upper() for item in requested_underlyings if item.strip())
    )
    if not underlyings:
        raise ValueError("at least one underlying must be selected")
    if from_date >= to_date:
        raise ValueError("from_date must be earlier than to_date")

    client = _build_kite_rest_client(settings)
    adapter = KiteMarketDataAdapter(client)
    nfo_master_csv = adapter.fetch_option_instrument_master()
    futures = parse_kite_futures_instruments(
        nfo_master_csv,
        underlyings=set(underlyings),
    ).contracts
    selection_date = _option_selection_date(datetime.now(MARKET_TIMEZONE))

    engine = build_engine(settings.database_url)
    try:
        create_schema(engine)
        factory = build_session_factory(engine)
        total_saved = 0
        for underlying in underlyings:
            future_contract = select_nearest_future_contract(
                futures,
                underlying=underlying,
                as_of=selection_date,
            )
            if future_contract is None:
                print(f"{underlying}: no non-expired NFO future; skipped")
                continue
            candles = adapter.fetch_historical_candles(
                exchange=future_contract.exchange,
                tradingsymbol=future_contract.tradingsymbol,
                instrument_token=future_contract.instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
                include_oi=True,
            )
            with factory() as session:
                repository = MarketDataRepository(session)
                saved = repository.save_candles(candles)
            total_saved += saved
            print(
                f"{underlying} via {future_contract.tradingsymbol}: "
                f"fetched={len(candles)} new_saved={saved}"
            )
        print(
            f"Historical futures candle backfill complete. "
            f"New rows saved: {total_saved}"
        )
    finally:
        engine.dispose()


def _completed_intraday_candles(
    candles,
    *,
    now: datetime,
    interval_seconds: int,
):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now_local = now.astimezone(MARKET_TIMEZONE)
    return tuple(
        candle
        for candle in candles
        if candle.timestamp.astimezone(MARKET_TIMEZONE)
        + timedelta(seconds=interval_seconds)
        <= now_local
    )


def analyze_options(
    *,
    settings: Settings,
    requested_underlyings: tuple[str, ...],
    strikes_each_side: int,
    risk_free_rate: float,
    interval: str,
) -> None:
    """Run a single read-only live-data analysis pass; never places orders."""
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

    interval_seconds_by_name = {
        "minute": 60,
        "3minute": 180,
        "5minute": 300,
        "10minute": 600,
        "15minute": 900,
        "30minute": 1800,
        "60minute": 3600,
    }
    if interval not in interval_seconds_by_name:
        raise ValueError("analyze-options requires an intraday interval")
    interval_seconds = interval_seconds_by_name[interval]

    kite = _build_kite_rest_client(settings)
    adapter = KiteMarketDataAdapter(kite)
    engine = build_engine(settings.database_url)
    try:
        create_schema(engine)
        factory = build_session_factory(engine)
        collector = KiteOptionsCollector(
            adapter=adapter,
            session_factory=factory,
        )
        market_now = datetime.now(MARKET_TIMEZONE)
        market_date = market_now.date()
        selection_date = _option_selection_date(market_now)
        nfo_master_csv = adapter.fetch_option_instrument_master()
        contracts = collector.load_daily_instrument_master(
            underlyings=set(underlyings),
            snapshot_date=market_date,
            instrument_master_csv=nfo_master_csv,
        )
        futures = parse_kite_futures_instruments(
            nfo_master_csv,
            underlyings=set(underlyings),
        ).contracts
        spot_snapshot = adapter.fetch_full_quotes(
            [mappings[item] for item in underlyings]
        )
        if spot_snapshot.missing_symbols:
            raise RuntimeError(
                "Kite did not return spot quotes for: "
                + ", ".join(spot_snapshot.missing_symbols)
            )

        now = datetime.now(UTC)
        spot_quotes = {
            (quote.exchange, quote.tradingsymbol): quote
            for quote in spot_snapshot.quotes
        }
        spot_prices: dict[str, Decimal] = {}
        for underlying in underlyings:
            exchange, symbol = mappings[underlying]
            quote = spot_quotes.get((exchange, symbol))
            if quote is None or quote.last_price is None or quote.last_price <= 0:
                raise RuntimeError(f"missing valid spot price for {underlying}")
            observed_at = quote.exchange_timestamp or quote.received_at
            age = (now - observed_at).total_seconds()
            if age < -5 or age > 30:
                raise RuntimeError(f"spot quote for {underlying} is stale")
            spot_prices[underlying] = quote.last_price

        selected = select_near_atm_contracts(
            contracts,
            spot_prices=spot_prices,
            as_of=selection_date,
            strikes_each_side=strikes_each_side,
        )
        if not selected:
            raise RuntimeError("no near-ATM CE/PE contracts were selected")
        option_snapshot = adapter.fetch_full_quotes(
            [(contract.exchange, contract.tradingsymbol) for contract in selected]
        )
        option_quotes = {
            (quote.exchange, quote.tradingsymbol): quote
            for quote in option_snapshot.quotes
        }

        option_flags = tuple(
            assess_quote_quality(
                quote,
                now=now,
                max_age_seconds=15,
            ).warnings
            for quote in option_snapshot.quotes
        )
        with factory() as session:
            repository = MarketDataRepository(session)
            repository.save_quotes(spot_snapshot.quotes)
            repository.save_quotes(
                option_snapshot.quotes,
                quality_flags=option_flags,
            )

        print("TradingGPT Options — read-only analysis pass")
        print("Mode: PAPER / NO ORDER PLACEMENT")
        print(f"Snapshot: {now.isoformat()}")
        print(f"Risk-free rate assumption: {risk_free_rate:.4%}")
        print(
            f"Contracts selected: {len(selected)}; "
            f"quotes received: {len(option_snapshot.quotes)}; "
            f"missing quotes: {len(option_snapshot.missing_symbols)}"
        )

        for underlying in underlyings:
            underlying_contracts = [
                item for item in selected if item.underlying == underlying
            ]
            expiry = select_nearest_expiry(
                underlying_contracts,
                as_of=selection_date,
            )
            if expiry is None:
                print(f"{underlying}: NO_TRADE — no non-expired option expiry")
                continue
            exchange, symbol = mappings[underlying]
            spot_quote = spot_quotes[(exchange, symbol)]
            chain = build_option_chain_view(
                underlying_contracts,
                option_quotes,
                underlying=underlying,
                expiry=expiry,
                spot_price=spot_quote.last_price,
                snapshot_at=now,
                risk_free_rate=risk_free_rate,
            )
            future_contract = select_nearest_future_contract(
                futures,
                underlying=underlying,
                as_of=selection_date,
            )
            if future_contract is None:
                print(
                    f"{underlying}: NO_TRADE — no current NFO future available "
                    "for volume-backed VWAP analysis"
                )
                continue
            candles = adapter.fetch_historical_candles(
                exchange=future_contract.exchange,
                tradingsymbol=future_contract.tradingsymbol,
                instrument_token=future_contract.instrument_token,
                from_date=market_now - timedelta(days=5),
                to_date=market_now,
                interval=interval,
                include_oi=True,
            )
            with factory() as session:
                repository = MarketDataRepository(session)
                repository.save_candles(candles)

            completed_candles = _completed_intraday_candles(
                candles,
                now=now,
                interval_seconds=interval_seconds,
            )
            analysis = analyze_baseline(
                completed_candles,
                chain,
                now=now,
                config=BaselineStrategyConfig(
                    max_candle_age_seconds=max(600, interval_seconds * 2)
                ),
            )
            decision = analysis.decision
            candidate = analysis.candidate
            with factory() as session:
                session.add(
                    StrategyDecisionSnapshot(
                        id=str(uuid4()),
                        snapshot_at=now,
                        underlying=underlying,
                        expiry=expiry,
                        decision=decision.direction,
                        confidence_score=(
                            Decimal(str(decision.confidence_score))
                            if decision.confidence_score is not None else None
                        ),
                        estimated_win_probability=(
                            Decimal(str(decision.estimated_win_probability))
                            if decision.estimated_win_probability is not None else None
                        ),
                        model_version=decision.model_version,
                        spot_price=spot_quote.last_price,
                        risk_free_rate=Decimal(str(risk_free_rate)),
                        candle_source=future_contract.tradingsymbol,
                        candle_count=len(completed_candles),
                        candidate_symbol=(
                            candidate.contract.tradingsymbol if candidate else None
                        ),
                        candidate_strike=(
                            candidate.contract.strike if candidate else None
                        ),
                        candidate_option_type=(
                            candidate.contract.option_type if candidate else None
                        ),
                        candidate_mid=candidate.mid_price if candidate else None,
                        candidate_iv=(
                            Decimal(str(candidate.implied_volatility))
                            if candidate and candidate.implied_volatility is not None
                            else None
                        ),
                        candidate_delta=(
                            Decimal(str(candidate.greeks.delta))
                            if candidate and candidate.greeks is not None
                            else None
                        ),
                        rationale_json=json.dumps(list(decision.rationale)),
                        opposing_evidence_json=json.dumps(
                            list(decision.opposing_evidence)
                        ),
                        warnings_json=json.dumps(list(analysis.warnings)),
                    )
                )
                session.commit()
            print(
                f"\n{underlying} | expiry={expiry.isoformat()} | "
                f"spot={spot_quote.last_price} | "
                f"candle_source={future_contract.tradingsymbol} | "
                f"decision={decision.direction} | "
                f"heuristic_score={decision.confidence_score}"
            )
            if analysis.candidate is not None:
                leg = analysis.candidate
                print(
                    f"Candidate: {leg.contract.tradingsymbol} | "
                    f"mid={leg.mid_price} | delta={leg.greeks.delta:.3f} | "
                    f"IV={leg.implied_volatility:.2%} | "
                    f"spread={leg.spread_percent:.2f}%"
                )
            for reason in decision.rationale:
                print(f"- {reason}")
            for warning in analysis.warnings:
                print(f"WARNING: {warning}")

        print("\nAnalysis complete. No order was submitted.")
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

        market_now = datetime.now(MARKET_TIMEZONE)
        market_date = market_now.date()
        selection_date = _option_selection_date(market_now)
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
            as_of=selection_date,
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
        print(f"Expiry selection date: {selection_date.isoformat()}")
        print(f"Underlyings: {', '.join(underlyings)}")
        print(f"Valid contracts in master: {len(contracts)}")
        print(f"Selected near-ATM contracts: {len(selected)}")
        print(f"Subscribed instrument tokens: {len(tokens)}")
        print("Press Ctrl+C to stop collection.")

        next_report = time.monotonic()
        next_subscription_refresh = time.monotonic() + 300
        while True:
            time.sleep(1)
            monotonic_now = time.monotonic()
            if monotonic_now >= next_subscription_refresh:
                try:
                    refresh_market_now = datetime.now(MARKET_TIMEZONE)
                    refresh_snapshot = adapter.fetch_full_quotes(spot_instruments)
                    if refresh_snapshot.missing_symbols:
                        raise RuntimeError(
                            "missing spot quotes during subscription refresh: "
                            + ", ".join(refresh_snapshot.missing_symbols)
                        )
                    refresh_now = datetime.now(UTC)
                    refresh_quotes = {
                        (quote.exchange, quote.tradingsymbol): quote
                        for quote in refresh_snapshot.quotes
                    }
                    refresh_spot_prices: dict[str, Decimal] = {}
                    for underlying in underlyings:
                        exchange, symbol = mappings[underlying]
                        quote = refresh_quotes.get((exchange, symbol))
                        if quote is None or quote.last_price is None or quote.last_price <= 0:
                            raise RuntimeError(
                                f"missing valid spot price for {underlying}"
                            )
                        observed_at = quote.exchange_timestamp or quote.received_at
                        age_seconds = (refresh_now - observed_at).total_seconds()
                        if age_seconds < -5 or age_seconds > 30:
                            raise RuntimeError(
                                f"spot quote for {underlying} is stale during refresh"
                            )
                        refresh_spot_prices[underlying] = quote.last_price
                    refresh_selection_date = _option_selection_date(refresh_market_now)
                    refreshed_contracts = select_near_atm_contracts(
                        contracts,
                        spot_prices=refresh_spot_prices,
                        as_of=refresh_selection_date,
                        strikes_each_side=strikes_each_side,
                    )
                    if not refreshed_contracts:
                        raise RuntimeError("subscription refresh selected no contracts")
                    tokens = collector.update_contracts(refreshed_contracts)
                    selected = refreshed_contracts
                    print(
                        f"[{refresh_market_now:%H:%M:%S}] subscription window refreshed: "
                        f"{len(selected)} contracts / {len(tokens)} tokens"
                    )
                    next_subscription_refresh = time.monotonic() + 300
                except Exception as exc:
                    print(f"WARNING: subscription refresh failed; keeping prior window: {exc}")
                    next_subscription_refresh = time.monotonic() + 60
            if time.monotonic() >= next_report:
                status = collector.status()
                last_tick = (
                    status.last_tick_at.astimezone(MARKET_TIMEZONE).strftime("%H:%M:%S")
                    if status.last_tick_at is not None else "never"
                )
                tick_age = (
                    (datetime.now(UTC) - status.last_tick_at).total_seconds()
                    if status.last_tick_at is not None else None
                )
                feed_health = (
                    "NO_TICKS"
                    if tick_age is None
                    else "FRESH"
                    if tick_age <= 15
                    else "STALE"
                )
                print(
                    f"[{datetime.now(MARKET_TIMEZONE):%H:%M:%S}] "
                    f"state={status.state} feed={feed_health} last_tick={last_tick} "
                    f"ticks={status.received_ticks} saved={status.persisted_quotes} "
                    f"rejected={status.rejected_ticks} unknown={status.unknown_tokens} "
                    f"error={status.last_error or '-'}"
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
        "kite-login-url",
        help="Print the Zerodha Kite Connect login URL",
    )
    exchange_parser = subparsers.add_parser(
        "kite-exchange-token",
        help="Exchange a Kite request token for a daily access token",
    )
    exchange_parser.add_argument(
        "--request-token",
        required=True,
        help="Short-lived request_token from the Zerodha redirect URL",
    )
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
    analyze_parser = subparsers.add_parser(
        "analyze-options",
        help="Run one read-only baseline analysis pass for selected underlyings",
    )
    analyze_parser.add_argument(
        "--underlyings",
        default="",
        help="Comma-separated underlyings; defaults to configured spot mappings",
    )
    analyze_parser.add_argument(
        "--strikes-each-side",
        type=int,
        default=3,
        help="Number of strikes below and above ATM to analyze",
    )
    analyze_parser.add_argument(
        "--risk-free-rate",
        type=float,
        required=True,
        help="Annualized risk-free-rate assumption as a decimal, e.g. 0.065",
    )
    analyze_parser.add_argument(
        "--interval",
        choices=(
            "minute",
            "3minute",
            "5minute",
            "10minute",
            "15minute",
            "30minute",
            "60minute",
        ),
        default="5minute",
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

    if args.command == "kite-login-url":
        print_kite_login_url(get_settings())
    elif args.command == "kite-exchange-token":
        exchange_kite_request_token(
            get_settings(),
            request_token=args.request_token,
        )
    elif args.command == "init-paper-account":
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
    elif args.command == "analyze-options":
        settings = get_settings()
        configured = _parse_spot_instrument_mappings(
            settings.kite_underlying_spot_instruments
        )
        underlyings = (
            tuple(item.strip().upper() for item in args.underlyings.split(",") if item.strip())
            if args.underlyings
            else tuple(configured)
        )
        analyze_options(
            settings=settings,
            requested_underlyings=underlyings,
            strikes_each_side=args.strikes_each_side,
            risk_free_rate=args.risk_free_rate,
            interval=args.interval,
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
