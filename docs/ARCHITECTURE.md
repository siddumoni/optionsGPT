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
