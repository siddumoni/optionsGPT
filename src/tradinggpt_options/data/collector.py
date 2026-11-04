from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import sessionmaker

from tradinggpt_options.data.instrument_master import parse_kite_instruments
from tradinggpt_options.data.kite_adapter import (
    KiteMarketDataAdapter,
    KiteTickerClient,
    KiteWebSocketSession,
)
from tradinggpt_options.data.models import OptionContract, OptionQuote, assess_quote_quality
from tradinggpt_options.data.quote_parser import parse_kite_tick
from tradinggpt_options.storage.repository import MarketDataRepository

LOGGER = logging.getLogger(__name__)
MARKET_TIMEZONE = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class CollectorStatus:
    state: str
    instrument_count: int
    subscribed_count: int
    received_ticks: int
    persisted_quotes: int
    rejected_ticks: int
    unknown_tokens: int
    last_tick_at: datetime | None
    last_error: str | None


class KiteOptionsCollector:
    """Persist full-mode Kite option ticks; this class has no order API.

    The caller chooses the contracts to subscribe to after the daily master has
    been parsed. This avoids indiscriminately subscribing to every listed option.
    Each WebSocket callback persists a batch in one database transaction.
    """

    def __init__(
        self,
        *,
        adapter: KiteMarketDataAdapter,
        session_factory: sessionmaker,
        max_quote_age_seconds: int = 15,
    ) -> None:
        if max_quote_age_seconds < 1:
            raise ValueError("max_quote_age_seconds must be at least one")
        self._adapter = adapter
        self._session_factory = session_factory
        self._max_quote_age_seconds = max_quote_age_seconds
        self._lock = threading.RLock()
        self._contracts_by_token: dict[int, OptionContract] = {}
        self._selected_tokens: tuple[int, ...] = ()
        self._session: KiteWebSocketSession | None = None
        self._state = "stopped"
        self._received_ticks = 0
        self._persisted_quotes = 0
        self._rejected_ticks = 0
        self._unknown_tokens = 0
        self._last_tick_at: datetime | None = None
        self._last_error: str | None = None

    def load_daily_instrument_master(
        self,
        *,
        underlyings: Iterable[str] | None = None,
        snapshot_date: date | None = None,
    ) -> tuple[OptionContract, ...]:
        """Fetch, parse and persist today's NFO-OPT CE/PE contract master."""
        csv_text = self._adapter.fetch_option_instrument_master()
        parsed = parse_kite_instruments(csv_text, underlyings=underlyings)
        if not parsed.contracts:
            raise RuntimeError(
                "No valid NFO option contracts found in Kite instrument master"
            )
        token_map: dict[int, OptionContract] = {}
        for contract in parsed.contracts:
            if contract.instrument_token in token_map:
                raise ValueError(
                    f"duplicate instrument token {contract.instrument_token} "
                    "in daily options master"
                )
            token_map[contract.instrument_token] = contract

        market_date = snapshot_date or datetime.now(MARKET_TIMEZONE).date()
        with self._session_factory() as db_session:
            repository = MarketDataRepository(db_session)
            repository.save_instrument_master(parsed.contracts, snapshot_date=market_date)

        with self._lock:
            self._contracts_by_token = token_map
        if parsed.rejected_rows:
            LOGGER.warning(
                "Instrument master loaded with rejected rows",
                extra={
                    "rejected_rows": parsed.rejected_rows,
                    "valid_contracts": len(parsed.contracts),
                },
            )
        return parsed.contracts

    def start(
        self,
        *,
        ticker: KiteTickerClient,
        contracts: Iterable[OptionContract],
    ) -> tuple[int, ...]:
        """Start the socket and subscribe to the caller-selected option contracts."""
        selected = tuple(contracts)
        if not selected:
            raise ValueError("at least one option contract must be selected")
        if len(selected) > 3000:
            raise ValueError("select no more than 3,000 contracts per Kite connection")

        with self._lock:
            if self._session is not None:
                raise RuntimeError("collector is already started")
            if not self._contracts_by_token:
                raise RuntimeError("load_daily_instrument_master must run before start")
            tokens: list[int] = []
            for contract in selected:
                master_contract = self._contracts_by_token.get(contract.instrument_token)
                if master_contract != contract:
                    raise ValueError(
                        f"contract {contract.tradingsymbol} is not in the loaded daily master"
                    )
                tokens.append(contract.instrument_token)
            self._selected_tokens = tuple(dict.fromkeys(tokens))
            self._state = "connecting"
            self._last_error = None
            self._session = KiteWebSocketSession(
                ticker,
                on_ticks=self._handle_ticks,
                on_state=self._handle_state,
            )
            session = self._session

        try:
            session.connect(threaded=True)
        except Exception as exc:
            with self._lock:
                self._state = "error"
                self._last_error = str(exc)
            raise
        return self._selected_tokens

    def _handle_state(self, state: str, detail: str | None) -> None:
        with self._lock:
            self._state = state
            if state == "error" or state == "reconnect_exhausted":
                self._last_error = detail or state
            elif state == "connected":
                self._last_error = None
                session = self._session
                tokens = self._selected_tokens
            else:
                session = None
                tokens = ()

        # Re-subscribe only after the server confirms connection. This also runs
        # after automatic reconnect, when KiteTicker invokes on_connect again.
        if state == "connected" and session is not None and tokens:
            try:
                session.subscribe(tokens)
            except Exception as exc:
                with self._lock:
                    self._state = "error"
                    self._last_error = str(exc)
                LOGGER.exception("Kite option subscription failed")

    def _handle_ticks(self, ticks: list[dict]) -> None:
        received_at = datetime.now(UTC)
        quotes: list[OptionQuote] = []
        flags: list[tuple[str, ...]] = []
        accepted_tick_count = 0
        unknown_count = 0
        rejected_count = 0

        with self._lock:
            contract_map = dict(self._contracts_by_token)
            selected_tokens = set(self._selected_tokens)

        for tick in ticks:
            accepted_tick_count += 1
            try:
                token = int(tick.get("instrument_token", 0))
            except (TypeError, ValueError):
                rejected_count += 1
                continue
            contract = contract_map.get(token)
            if contract is None or token not in selected_tokens:
                unknown_count += 1
                continue
            try:
                quote = parse_kite_tick(
                    exchange=contract.exchange,
                    tradingsymbol=contract.tradingsymbol,
                    instrument_token=contract.instrument_token,
                    payload=tick,
                    received_at=received_at,
                )
                quality = assess_quote_quality(
                    quote,
                    now=received_at,
                    max_age_seconds=self._max_quote_age_seconds,
                )
                quote_flags = list(quality.warnings)
                if quality.is_stale:
                    quote_flags.append("not_executable_stale")
                if quality.is_crossed_market:
                    quote_flags.append("not_executable_crossed")
                quotes.append(quote)
                flags.append(tuple(dict.fromkeys(quote_flags)))
            except (KeyError, TypeError, ValueError) as exc:
                rejected_count += 1
                LOGGER.warning(
                    "Rejected malformed Kite option tick",
                    extra={"instrument_token": token, "error": str(exc)},
                )

        persisted = 0
        if quotes:
            try:
                with self._session_factory() as db_session:
                    repository = MarketDataRepository(db_session)
                    persisted = repository.save_quotes(tuple(quotes), quality_flags=tuple(flags))
            except Exception as exc:
                rejected_count += len(quotes)
                LOGGER.exception("Failed to persist Kite option quote batch")
                with self._lock:
                    self._last_error = f"quote persistence failed: {exc}"

        with self._lock:
            self._received_ticks += accepted_tick_count
            self._persisted_quotes += persisted
            self._rejected_ticks += rejected_count
            self._unknown_tokens += unknown_count
            self._last_tick_at = received_at

    def stop(self) -> None:
        with self._lock:
            session = self._session
            self._session = None
            self._selected_tokens = ()
            self._state = "stopping"
        if session is not None:
            session.close()
        with self._lock:
            self._state = "stopped"

    def status(self) -> CollectorStatus:
        with self._lock:
            return CollectorStatus(
                state=self._state,
                instrument_count=len(self._contracts_by_token),
                subscribed_count=len(self._selected_tokens),
                received_ticks=self._received_ticks,
                persisted_quotes=self._persisted_quotes,
                rejected_ticks=self._rejected_ticks,
                unknown_tokens=self._unknown_tokens,
                last_tick_at=self._last_tick_at,
                last_error=self._last_error,
            )
