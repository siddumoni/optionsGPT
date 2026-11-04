from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from tradinggpt_options.data.models import DepthLevel, OptionQuote


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _depth_levels(levels: Any) -> tuple[DepthLevel, ...]:
    if not isinstance(levels, list):
        return ()
    result: list[DepthLevel] = []
    for item in levels:
        if not isinstance(item, dict):
            continue
        price = _decimal(item.get("price"))
        try:
            quantity = int(item.get("quantity", 0))
            orders = int(item.get("orders", 0))
        except (TypeError, ValueError):
            continue
        if price is None or price <= 0 or quantity < 0 or orders < 0:
            continue
        result.append(DepthLevel(price=price, quantity=quantity, orders=orders))
    return tuple(result)


def parse_kite_quote(
    *, exchange: str, tradingsymbol: str, instrument_token: int,
    payload: dict[str, Any], received_at: datetime | None = None,
) -> OptionQuote:
    """Normalize a Kite full-quote payload without inventing absent fields."""
    depth = payload.get("depth") if isinstance(payload.get("depth"), dict) else {}
    timestamp = payload.get("timestamp")
    if timestamp is not None and not isinstance(timestamp, datetime):
        timestamp = None
    return OptionQuote(
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        instrument_token=instrument_token,
        exchange_timestamp=timestamp,
        received_at=received_at or datetime.now(timezone.utc),
        last_price=_decimal(payload.get("last_price")),
        bid=_depth_levels(depth.get("buy")),
        ask=_depth_levels(depth.get("sell")),
        volume=int(payload["volume"]) if payload.get("volume") is not None else None,
        open_interest=int(payload["oi"]) if payload.get("oi") is not None else None,
    )
