from __future__ import annotations

import csv
import io
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from tradinggpt_options.data.models import MarketCandle, OptionQuote
from tradinggpt_options.data.quote_parser import parse_kite_quote


class KiteRestClient(Protocol):
    """Narrow read-only surface used from the official KiteConnect SDK."""

    def instruments(self, exchange: str | None = None) -> list[dict[str, Any]]: ...

    def quote(self, *instruments: str) -> dict[str, dict[str, Any]]: ...

    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict[str, Any]]: ...


class KiteTickerClient(Protocol):
    MODE_FULL: str

    def subscribe(self, instrument_tokens: list[int]) -> None: ...

    def set_mode(self, mode: str, instrument_tokens: list[int]) -> None: ...


@dataclass(frozen=True, slots=True)
class ReadOnlyMarketSnapshot:
    received_at: datetime
    quotes: tuple[OptionQuote, ...]
    missing_symbols: tuple[str, ...]


class RequestPacer:
    """Thread-safe minimum interval between calls to one REST endpoint."""

    def __init__(
        self,
        *,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if interval_seconds < 0:
            raise ValueError("interval_seconds cannot be negative")
        self._interval = interval_seconds
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            delay = max(0.0, self._next_allowed - now)
            if delay:
                self._sleep(delay)
                now = self._clock()
            self._next_allowed = max(now, self._next_allowed) + self._interval


class KiteMarketDataAdapter:
    """Read-only Kite Connect integration. No order methods are exposed.

    Inject a KiteConnect instance from the official SDK. Authentication and token
    refresh are owned by the application bootstrap; the access token must never
    be written to the repository or logs.
    """

    def __init__(
        self,
        client: KiteRestClient,
        *,
        quote_interval_seconds: float = 1.0,
        instrument_interval_seconds: float = 0.1,
        historical_interval_seconds: float = 1.0,
    ) -> None:
        self._client = client
        self._quote_pacer = RequestPacer(interval_seconds=quote_interval_seconds)
        self._instrument_pacer = RequestPacer(interval_seconds=instrument_interval_seconds)
        self._historical_pacer = RequestPacer(interval_seconds=historical_interval_seconds)

    def fetch_option_instrument_master(self) -> str:
        """Fetch NFO instruments once per day and return a normalized CSV snapshot."""
        self._instrument_pacer.wait()
        rows = self._client.instruments("NFO")
        if not rows:
            raise RuntimeError("Kite returned an empty NFO instrument master")
        output = io.StringIO()
        columns = (
            "instrument_token", "exchange_token", "tradingsymbol", "name",
            "last_price", "expiry", "strike", "tick_size", "lot_size",
            "instrument_type", "segment", "exchange",
        )
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def fetch_full_quotes(
        self,
        instruments: Iterable[tuple[str, str]],
    ) -> ReadOnlyMarketSnapshot:
        """Fetch full snapshots in batches of <=500, respecting quote endpoint pace."""
        keys = tuple(dict.fromkeys(
            f"{exchange.upper()}:{symbol.upper()}" for exchange, symbol in instruments
        ))
        if not keys:
            return ReadOnlyMarketSnapshot(datetime.now(UTC), (), ())
        if len(keys) > 500:
            raise ValueError("fetch_full_quotes accepts at most 500 instruments per call")

        self._quote_pacer.wait()
        payload = self._client.quote(*keys)
        received_at = datetime.now(UTC)
        result: list[OptionQuote] = []
        missing: list[str] = []
        for key in keys:
            item = payload.get(key)
            if item is None:
                missing.append(key)
                continue
            try:
                exchange, symbol = key.split(":", maxsplit=1)
                result.append(
                    parse_kite_quote(
                        exchange=exchange,
                        tradingsymbol=symbol,
                        instrument_token=int(item["instrument_token"]),
                        payload=item,
                        received_at=received_at,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Malformed full quote for {key}: {exc}") from exc
        return ReadOnlyMarketSnapshot(received_at, tuple(result), tuple(missing))

    def fetch_historical_candles(
        self,
        *,
        exchange: str,
        tradingsymbol: str,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        include_oi: bool = True,
    ) -> tuple[MarketCandle, ...]:
        """Fetch candles for a known token; expired-option availability is not implied."""
        supported_intervals = {
            "minute", "3minute", "5minute", "10minute",
            "15minute", "30minute", "60minute", "day",
        }
        if interval not in supported_intervals:
            raise ValueError(f"unsupported historical interval: {interval}")
        if instrument_token <= 0:
            raise ValueError("instrument_token must be positive")
        for label, value in (("from_date", from_date), ("to_date", to_date)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{label} must be timezone-aware")
        if from_date >= to_date:
            raise ValueError("from_date must be earlier than to_date")

        self._historical_pacer.wait()
        rows = self._client.historical_data(
            instrument_token,
            from_date,
            to_date,
            interval,
            continuous=False,
            oi=include_oi,
        )
        candles: list[MarketCandle] = []
        for index, row in enumerate(rows):
            timestamp = row.get("date")
            if not isinstance(timestamp, datetime):
                raise ValueError(f"historical candle {index} has no datetime timestamp")
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"historical candle {index} timestamp is naive")
            try:
                prices = {
                    field: Decimal(str(row[field]))
                    for field in ("open", "high", "low", "close")
                }
                volume = int(row.get("volume", 0))
                oi_raw = row.get("oi")
                open_interest = int(oi_raw) if oi_raw is not None else None
                candles.append(
                    MarketCandle(
                        exchange=exchange.upper(),
                        tradingsymbol=tradingsymbol.upper(),
                        instrument_token=instrument_token,
                        interval=interval,
                        timestamp=timestamp,
                        open=prices["open"],
                        high=prices["high"],
                        low=prices["low"],
                        close=prices["close"],
                        volume=volume,
                        open_interest=open_interest,
                    )
                )
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise ValueError(f"malformed historical candle {index}: {exc}") from exc
        candles.sort(key=lambda candle: candle.timestamp)
        if len({candle.timestamp for candle in candles}) != len(candles):
            raise ValueError("historical response contains duplicate candle timestamps")
        return tuple(candles)



def create_kite_ticker(api_key: str, access_token: str) -> Any:
    """Construct the official KiteTicker lazily to keep imports easy to test."""
    if not api_key.strip() or not access_token.strip():
        raise ValueError("Kite API key and access token are required")
    try:
        from kiteconnect import KiteTicker
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise RuntimeError("Install the kiteconnect package to use live market data") from exc
    return KiteTicker(api_key, access_token)


def subscribe_full_market_data(
    ticker: KiteTickerClient,
    instrument_tokens: Iterable[int],
) -> tuple[int, ...]:
    """Subscribe at most 3,000 unique positive tokens in full-depth mode."""
    tokens = tuple(dict.fromkeys(int(token) for token in instrument_tokens))
    if any(token <= 0 for token in tokens):
        raise ValueError("instrument tokens must be positive integers")
    if len(tokens) > 3000:
        raise ValueError("Kite supports at most 3,000 subscriptions per connection")
    if tokens:
        ticker.subscribe(list(tokens))
        ticker.set_mode(ticker.MODE_FULL, list(tokens))
    return tokens


class KiteWebSocketSession:
    """Lifecycle wrapper for a single official KiteTicker connection."""

    def __init__(
        self,
        ticker: Any,
        *,
        on_ticks: Callable[[list[dict[str, Any]]], None],
        on_state: Callable[[str, str | None], None] | None = None,
    ) -> None:
        self._ticker = ticker
        self._on_ticks = on_ticks
        self._on_state = on_state or (lambda _state, _detail: None)
        self._connected = threading.Event()
        self._last_tick_at: datetime | None = None

        ticker.on_ticks = self._handle_ticks
        ticker.on_connect = self._handle_connect
        ticker.on_close = self._handle_close
        ticker.on_error = self._handle_error
        ticker.on_reconnect = self._handle_reconnect
        ticker.on_noreconnect = self._handle_no_reconnect

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def last_tick_at(self) -> datetime | None:
        return self._last_tick_at

    def _handle_ticks(self, _ws: Any, ticks: list[dict[str, Any]]) -> None:
        self._last_tick_at = datetime.now(UTC)
        self._on_ticks(ticks)

    def _handle_connect(self, _ws: Any, _response: Any) -> None:
        self._connected.set()
        self._on_state("connected", None)

    def _handle_close(self, _ws: Any, code: Any, reason: Any) -> None:
        self._connected.clear()
        self._on_state("disconnected", f"{code}: {reason}")

    def _handle_error(self, _ws: Any, code: Any, reason: Any) -> None:
        self._on_state("error", f"{code}: {reason}")

    def _handle_reconnect(self, _ws: Any, attempt: Any) -> None:
        self._connected.clear()
        self._on_state("reconnecting", str(attempt))

    def _handle_no_reconnect(self, _ws: Any) -> None:
        self._connected.clear()
        self._on_state("reconnect_exhausted", None)

    def connect(self, *, threaded: bool = True) -> None:
        self._ticker.connect(threaded=threaded)

    def subscribe(self, instrument_tokens: Iterable[int]) -> tuple[int, ...]:
        return subscribe_full_market_data(self._ticker, instrument_tokens)

    def close(self) -> None:
        self._connected.clear()
        self._ticker.close()
        self._on_state("stopped", None)
