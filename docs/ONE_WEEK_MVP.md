# One-week delivery target

A one-week schedule is a time-box for a **paper-trading MVP**, not a guarantee of profitability or production readiness.

## Day 1 — Contract/data foundation
- Instrument master ingestion and immutable dated snapshots.
- Option contract identity and validation.
- Contract selection (underlying, expiry, ATM/nearby strikes).
- CI and parser tests.

## Day 2 — Live data collection
- Kite authentication adapter with no embedded secrets.
- Quote/WebSocket adapter.
- Reconnect, heartbeat, stale-data and missing-depth handling.
- Local persistent raw snapshots.

## Day 3 — Options analytics
- Option-chain snapshots.
- Implied-volatility solver and Black–Scholes Greeks with documented assumptions.
- Intrinsic/extrinsic value, expiry/time conventions.
- Deterministic test vectors.

## Day 4 — Research and risk
- Initial transparent baseline signal (or NO_TRADE).
- Underlying regime and multi-timeframe context.
- Long CE/PE contract ranking.
- Independent lot sizing, premium debit and max-loss controls.

## Day 5 — Paper execution
- Bid/ask-aware conservative fills.
- Fees/charges configuration versioned by effective date.
- Position lifecycle, duplicate prevention and restart recovery.
- Daily loss and capital circuit breakers.

## Day 6 — Dashboard and reporting
- Market/data status, opportunity table, open positions, closed trades and net P&L.
- Decision journal with evidence and missing-data reasons.
- Exportable session report.

## Day 7 — End-to-end validation
- Replay tests on recorded market data.
- Failure/reconnect/stale-feed tests.
- Regression suite and code review.
- Document gaps and whether the MVP is safe to run in paper mode.

## Explicitly out of scope for the one-week MVP
- A guaranteed or presumed 75% win rate.
- Proven profitability.
- Deep learning or online self-modifying strategies.
- Verified multi-year options backtesting without licensed and validated historical contract-level data.
- Live order placement.

## Exit criteria
- Clean setup succeeds on Windows 11.
- CI passes on supported Python versions.
- No live-order code path.
- Instrument master and quotes preserve provenance.
- Stale/incomplete data leads to NO_TRADE.
- Paper accounting matches deterministic tests.
- All displayed metrics can be traced to stored trades/data.
