# TradingGPT Options

Independent NSE index/stock-options research and paper-trading platform using Zerodha Kite Connect market data.

> **Safety:** This application is paper-only. It has no Kite order-placement path. Do not add live execution without separate architecture review, current broker/exchange compliance checks, explicit user approval and dedicated controls.

## Principles

- The existing cash-equity `tradinggpt` repository is an engineering reference only; this repository has no code, database, configuration or runtime dependency on it.
- Start with long CE/PE paper trades only.
- Preserve market-data provenance and contract identity.
- Distinguish actual observations, calculations, estimates and model predictions.
- No fabricated option history, fills, Greeks, news or returns.
- `NO_TRADE` is a valid system decision.
- Confidence scores are not calibrated probabilities.

## Configuration

- NSE F&O
- ₹1,00,000 virtual capital by default
- SQLite local database
- FastAPI backend
- Kite Connect read-only market-data integration
- Python 3.12/3.13 supported by CI

Create a local environment file from `.env.example`. Never commit `.env`, API secrets or access tokens.

## Windows 11 setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
pytest
```

## Run

```powershell
uvicorn tradinggpt_options.api.main:app --reload
```

Open `http://127.0.0.1:8000/docs`.

- `GET /health` — app and paper/live mode status
- `GET /api/v1/paper/account` — paper-account summary (404 until account is initialized)
- `GET /api/v1/paper/trades?status=all|open|closed` — paper trade journal

The account is initialized by the local paper broker, not by the read-only API. No HTTP endpoint places or modifies an order.

## Current implementation

- Kite NFO instrument-master adapter and parser
- Full-quote REST adapter with batch and request pacing
- Full-depth WebSocket subscription helper and connection-state callbacks
- Option-contract, depth and quote data models with validation
- CE/PE chain pairing, nearest-expiry and ATM strike selection
- European Black–Scholes Greeks and bisection implied-volatility solver
- SQLite persistence for dated contracts, quotes, paper accounts and paper trades
- Long-option risk sizing and local paper broker (ask-side entry / bid-side exit)
- Bid-side mark-to-market equity
- Paper account and trade-history read APIs
- Unit tests and GitHub Actions CI on Python 3.12 and 3.13

## Known limitations

- Kite adapter has not yet been run against the user's real API credentials.
- The API does not yet schedule live collection or run the WebSocket stream as a background service.
- Paper charge configuration is a placeholder; statutory charges must be implemented with effective-dated rules before performance reporting.
- Historical expired-option prices are not supplied by the Kite historical-candle endpoint. Do not backtest strategies without a verified historical contract-level dataset.
- No strategy is claimed profitable; no 75% win-rate guarantee is made.
- No live order-placement capability is implemented.

## Development and validation

See `docs/ONE_WEEK_MVP.md`, `docs/DATA_CONTRACT.md`, `docs/KITE_DATA_INTEGRATION.md`, and `docs/ROADMAP.md`.
