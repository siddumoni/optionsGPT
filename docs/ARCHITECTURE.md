# Architecture decisions

## ADR-001: Independent repository and runtime

TradingGPT Options is a separate application. It may use the existing `tradinggpt` repository as a reference for engineering patterns, but it must not import its code, share its database, reuse its runtime state, or change its deployment.

## ADR-002: Paper-only initial release

The initial application exposes no live order-placement capability. `TRADING_MODE` accepts only `PAPER`; live trading is not a selectable configuration in this scaffold.

## ADR-003: Data provenance is mandatory

Market observations must preserve source, exchange timestamp, receipt timestamp, contract identity and quality flags. Missing data must remain missing rather than be silently synthesized.

## ADR-004: Options accounting is contract-aware

Positions are represented by exchange-traded option contracts and quantities in units/lots. Premium, lot size, expiry, option type and charges are distinct from cash-equity accounting.

## ADR-005: Backtests must disclose data quality

Reports distinguish historical quote-based fills, OHLC-based simulations and synthetic estimates. Only actual historical contract observations can support claims about historical option premiums.


## ADR-006: Read-only market-data boundaries

The Kite adapter exposes only instrument-master, quote and historical-candle reads.
The WebSocket collector is limited to subscribing to market data. It does not
receive a Kite order client and cannot place, modify or cancel broker orders.

The current collection CLI uses explicit underlying-to-spot-instrument mappings
to derive the near-ATM strike window. It fails closed if spot data is missing,
stale or invalid. The instrument master is captured as a dated snapshot because
derivative instrument tokens are not durable identifiers.

## ADR-007: Preserve depth and candles as distinct observations

Quote snapshots retain the complete bid and ask depth arrays available in each
Kite packet. Historical OHLCV candles are stored in a separate table and cannot
be substituted for quote-level execution prices. Backtest fills must state
whether they are derived from candle OHLC, actual historical quotes or a
synthetic assumption.
