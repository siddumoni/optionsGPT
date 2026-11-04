# TradingGPT Options

Independent NSE index and stock-options research and paper-trading platform using Zerodha Kite Connect market data.

> **Safety:** This application is paper-only. It has no Kite order-placement path. Do not add live execution without separate architecture review, current broker/exchange compliance checks, explicit user approval and dedicated safety tests.

## Principles

- The existing cash-equity tradinggpt repository is an engineering reference only; this repository shares no code, database, configuration or runtime state with it.
- Start with long CE/PE paper trades only.
- Preserve market-data provenance and exchange contract identity.
- Distinguish observed data, calculations, estimates and model predictions.
- Never fabricate option prices, historical trades, fills, Greeks or returns.
- NO_TRADE is a valid system decision.
- Confidence scores are not calibrated probabilities.

## Environment

- NSE F&O
- ₹1,00,000 initial virtual capital by default
- Python 3.12 and 3.13
- SQLite for local development
- FastAPI backend
- Kite Connect read-only market-data integration

Create a local .env from .env.example. Never commit API keys, access tokens or secrets.

## Windows 11 setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
pytest
```

Initialize the local paper account:

```powershell
tradinggpt-options init-paper-account
```

This only creates the local SQLite account and its starting virtual balance. It does not authenticate to a broker or send an order.

## Run the API

```powershell
uvicorn tradinggpt_options.api.main:app --reload
```

Open http://127.0.0.1:8000/docs.

- GET /health — application and paper/live-mode status
- GET /api/v1/paper/account — persistent paper-account summary
- GET /api/v1/paper/trades?status=all|open|closed — trade history

There is no HTTP order-placement endpoint. The paper account is initialized by the CLI or local paper broker, not by a read-only API request.

## Implemented foundations

- Defensive parser for Kite's daily NFO option instrument master
- Read-only Kite REST adapter for instrument master and full quote snapshots
- Quote endpoint pacing and full-quote 500-instrument batch validation
- Full-depth WebSocket subscription helper (3,000 token guard) and lifecycle state callbacks
- Validated option contract, quote and order-book data models
- CE/PE strike pairing, nearest-expiry and ATM selection
- European Black–Scholes Greeks and implied-volatility bisection solver
- SQLite models/repository for instrument snapshots, quote snapshots, paper accounts and trades
- Premium-risk lot sizing
- Local long-option paper broker with ask-side entries and bid-side exits
- Bid-side mark-to-market equity, stale/missing quote rejection and duplicate-open-trade protection
- Read-only paper account and trade-history API endpoints
- GitHub Actions lint/test matrix for Python 3.12 and 3.13

## Known limitations

- Kite credentials have not yet been supplied or used to test the adapter against a real account.
- Live quote ingestion is not yet running as a managed background service; WebSocket adapter is implemented as a library component only.
- Full options-chain snapshots and OI history need scheduled persistence and more depth than best bid/ask.
- Statutory options charges are not yet implemented as effective-dated rules. The paper broker's charge value is explicitly a configurable placeholder and currently defaults to zero.
- Kite's historical candle service is not a long-term expired-options archive. Historical contract-level option data must be licensed/collected and validated before backtesting options.
- Greeks use European Black–Scholes assumptions; expiry calendar/time conventions and dividend/carry inputs require market-specific validation.
- No profitable strategy, 75% win rate, or live-trading readiness is claimed.
- Live order placement is not implemented.

## Development documents

- docs/ARCHITECTURE.md
- docs/DATA_CONTRACT.md
- docs/KITE_DATA_INTEGRATION.md
- docs/ONE_WEEK_MVP.md
- docs/ROADMAP.md
