from __future__ import annotations

import csv
import io
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from tradinggpt_options.data.models import OptionQuote
from tradinggpt_options.data.quote_parser import parse_kite_quote


class KiteRestClient(Protocol):
    """Narrow read-only surface used from the official KiteConnect SDK."""

    def instruments(self, exchange: str | None = None) -> list[dict[str, Any]]: ...

    def quote(self, *instruments: str) -> dict[str, dict[str, Any]]: ...


class KiteTickerClient(Protocol):
    MODE_FULL: str

    def subscribe(self, instrument_tokens: list[int]) -> None: ...

    def set_mode(self, mode: str, instrument_tokens: list[int]) -> None: ...

    def connect(self, threaded: bool = False) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ReadOnlyMarketSnapshot:
    received_at: datetime
    quotes: tuple[OptionQuote, ...]
    missing_symbols: tuple[str, ...]


class RequestPacer:
    """Thread-safe minimum interval between calls to one REST endpoint."""

    def __init__(self, *, interval_seconds: float, clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
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
    ) -> None:
        self._client = client
        self._quote_pacer = RequestPacer(interval_seconds=quote_interval_seconds)
        self._instrument_pacer = RequestPacer(interval_seconds=instrument_interval_seconds)

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
