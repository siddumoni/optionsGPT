# Kite Connect market-data integration

## Current design

The adapter wraps the official `KiteConnect` read-only methods used by this application:

- `instruments("NFO")`: daily NFO instrument master, normalized to the parser's CSV format.
- `quote(...)`: full snapshot batches capped at 500 exchange/tradingsymbol keys.
- `KiteTicker`: full-mode WebSocket subscriptions capped at 3,000 instrument tokens per connection.

The quote REST endpoint is paced at one request per second by default. The instrument master is expected to be fetched once per trading day and saved as an immutable dated snapshot. WebSocket streaming is the live-session path; REST snapshots are for controlled synchronization and recovery. The `collect-options` CLI is the current foreground collector. It requires explicit `UNDERLYING=EXCHANGE:TRADINGSYMBOL` spot mappings, fetches a fresh spot snapshot, selects the nearest expiry and near-ATM CE/PE strike window, then persists WebSocket ticks. It does not silently guess index spot symbols.

The adapter also supports historical OHLCV retrieval for a known instrument token and persists normalized candles separately from quote observations. Historical candles are not a substitute for order-book depth or executable bid/ask prices.

## Authentication

The API key and access token are injected by application bootstrap from environment variables or an approved secret store. Never log or commit them. The API secret is used only in the login/access-token exchange; do not store it in the source tree.

## Safety boundaries

The adapter deliberately exposes no place/modify/cancel order methods. It can only retrieve instruments and market data. Paper execution remains a local application component.

## Data correctness

- Kite's instrument master is generated daily and its `last_price` field is not live.
- Quote responses may omit keys for instruments with no available quote; the adapter records missing symbols explicitly.
- Never replace missing bid/ask with LTP.
- A reconnect re-subscribes the selected tokens; quote freshness, two-sided depth and clock-skew checks must pass before a paper fill can be accepted.
- A subscription set above 3,000 must be rejected or sharded by a separately managed connection pool; this first version rejects it to avoid hidden connection fan-out.

## Sources

- https://kite.trade/docs/connect/v3/market-quotes/
- https://kite.trade/docs/connect/v3/websocket/
- https://kite.trade/docs/connect/v3/historical/
- https://github.com/zerodha/pykiteconnect


## Rolling near-ATM WebSocket window

The foreground collector does not pin its subscriptions for the entire session.
Every five minutes it refreshes the configured underlying spot quotes, reselects
the nearest non-expired expiry and the configured strike window, unsubscribes
contracts that have moved out of range, and subscribes newly selected tokens in
full mode. The current token set is also used after automatic WebSocket
reconnects. If the refresh spot quote is missing or stale, the collector keeps
the previous subscription window and retries after one minute.

This is still a bounded near-ATM archive, not a complete historical option-chain
dataset. The selected underlyings, expiry and strike window define which option
contracts are persisted.
