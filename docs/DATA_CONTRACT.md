# Options data contract

## Contract identity

Use `(exchange, tradingsymbol)` as the durable natural key for the instrument master. Preserve the instrument token as a current-session streaming identifier, not as a permanent historical identity. Retain a daily copy of the master to resolve contract metadata as it existed on a given date.

## Quote observations

Persist at least:
- exchange and tradingsymbol
- instrument token observed from that day's master
- exchange timestamp when supplied
- local receipt timestamp (UTC, timezone-aware)
- LTP, best bid/ask and every available bid/ask depth level (price, quantity, order count)
- volume and open interest when supplied
- source and ingestion version
- quality flags, including stale/crossed/missing-side states

Never silently substitute LTP for missing bid/ask. Quote snapshots and OHLC candles are different datasets and must be stored separately.

## Instrument-master ingestion

Fetch the full daily instrument master once per trading day, validate required columns, select NFO-OPT CE/PE rows, record rejected rows, and persist an immutable dated copy. The parser must not assume every row is valid.

## Historical candles

Store candles separately from quote snapshots. A candle identity is
`(exchange, tradingsymbol, interval, timestamp)`; preserve the instrument token
as the token used for the request, not as the permanent identity. Validate
timezone-aware timestamps and OHLC consistency before persistence. Keep OI
nullable when the source does not provide it.

Kite historical candles are useful for instruments whose historical token/data
is available. The API's continuous-history feature is documented for futures,
not expired options. Do not assume expired CE/PE history can be retrieved after
the contract leaves the daily instrument master.

## Scope

The read-only collector fetches the daily NFO instrument master, maps explicit
underlying spot instruments, selects near-ATM CE/PE contracts, subscribes in
full mode, and persists tick snapshots including all five bid/ask levels when
provided. A historical-candle adapter and idempotent candle persistence are
also available. Collection still needs process supervision and scheduled
backfills before it can be considered an unattended service.
