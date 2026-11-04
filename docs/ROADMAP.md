# Delivery roadmap

1. **Data foundation:** instrument master ingestion, contract identity, quote snapshots with full depth, historical OHLCV candles, WebSocket lifecycle, persistence and quality checks. Core read-only collection is implemented; unattended service supervision and scheduled backfills remain.
2. **Options analytics:** nearest-expiry/ATM selection, quality-aware CE/PE chain view, mid-price IV, spread and European BSM Greeks are implemented as a view builder. Remaining: persisted chain snapshots, OI changes, liquidity filters and model calibration.
3. **Research:** an explainable EMA9/EMA21 + session VWAP + RSI14 + volume baseline and CE/PE liquidity/delta ranking are implemented as a research-only analyzer. Remaining: multi-timeframe regime, event/news ingestion, strategy registry, risk gates and calibrated probability evaluation.
4. **Backtesting:** contract-level option data, charge schedule reconciliation, spread/slippage, walk-forward and out-of-sample evaluation. The first effective-dated Zerodha/NSE charge schedule is implemented; historical options data must be archived before expiry or sourced separately.
5. **Paper execution:** virtual ledger, conservative fills, partial-fill model, automated exits, restart recovery, daily loss and capital circuit breakers, audit journal.
6. **Dashboard:** market/data health, ranked candidates, open positions, realized/unrealized P&L, decision journal and downloadable reports.
7. **Forward validation:** multiple market regimes, sample-size review, calibration, reconciliation and independent readiness assessment.
8. **Live readiness:** separate project phase requiring regulatory/broker verification and explicit user approval; not part of this scaffold.

## Non-negotiable research rules

- A model confidence score is not a calibrated probability.
- Do not target or advertise 75% win probability until a sufficiently large, untouched out-of-sample dataset demonstrates calibration and stability.
- A strategy may return NO_TRADE.
- Do not use future information, survivorship-biased universes or revised data in historical simulation.
- Report net P&L after actual charges, spread, slippage and rejected/partial fills.
- Never promote a strategy based on in-sample optimization alone.
