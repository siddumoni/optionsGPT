# Options data contract

## Contract identity

Use `(exchange, tradingsymbol)` as the durable natural key for the instrument master. Preserve the instrument token as a current-session streaming identifier, not as a permanent historical identity. Retain a daily copy of the master to resolve contract metadata as it existed on a given date.

## Quote observations

Persist at least:
- exchange and tradingsymbol
- instrument token observed from that day's master
- exchange timestamp when supplied
- local receipt timestamp (UTC, timezone-aware)
- LTP, best bid/ask and available depth
- volume and open interest when supplied
- source and ingestion version
- quality flags, including stale/crossed/missing-side states

Never silently substitute LTP for missing bid/ask. Quote snapshots and OHLC candles are different datasets and must be stored separately.

## Instrument-master ingestion

Fetch the full daily instrument master once per trading day, validate required columns, select NFO-OPT CE/PE rows, record rejected rows, and persist an immutable dated copy. The parser must not assume every row is valid.

## Scope

The first vertical slice supports parsing and selecting contracts from a supplied instrument CSV. Network access, credential handling, scheduled collection and database persistence are subsequent tasks.
