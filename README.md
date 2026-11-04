# TradingGPT Options

An independent research and paper-trading platform for NSE index and stock options using Zerodha Kite Connect market data.

> **Safety:** This repository starts in paper-only mode. No live order placement is implemented. Do not add live execution without a separately reviewed design, broker/exchange compliance checks, explicit approval, and dedicated safety tests.

## Project principles

- Independent from `tradinggpt`; that repository is a reference only.
- No imports, shared database, shared runtime state, or shared configuration with the cash-equity project.
- Options-specific data model and accounting.
- Live market-data capture before claiming historical options backtest capability.
- No fabricated historical option prices, Greeks, news, fills, or performance.
- A model confidence score is not a calibrated probability.
- `NO_TRADE` is a valid and expected decision.

## Initial configuration

- Market: NSE F&O
- Instruments: eligible index and stock options
- Initial strategy scope: long CE / long PE only
- Default virtual capital: INR 100,000
- Execution: paper only
- Database: SQLite for development
- Backend: Python + FastAPI
- Dashboard: API-first; UI choice follows the first working data vertical slice

## Repository layout

```text
src/tradinggpt_options/
  api/                 FastAPI application
  config/              Typed settings and safety defaults
  data/                Broker adapters, instruments and market-data capture
  options/             Chain, IV, Greeks, expiry and strike selection
  research/            Signals, regime detection and probability calibration
  backtesting/         Historical option-contract backtesting
  execution/           Paper broker, fills and position lifecycle
  risk/                Independent capital and loss controls
  storage/             Database models and repositories
  reporting/           Session reports and decision journal
tests/
  unit/
  integration/
  contract/
```

## Windows 11 setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
pytest
```

Python 3.12 is the initial compatibility target. Validate any move to a newer Python version against the chosen broker SDK and numerical dependencies before upgrading.

## Run the API

```powershell
uvicorn tradinggpt_options.api.main:app --reload
```

Open `http://127.0.0.1:8000/health`.

## Configuration

Never commit `.env`, Zerodha API secrets, access tokens, or account credentials. `.env.example` contains placeholders only.

Paper trading must remain enabled. The application intentionally has no live-order endpoint in this initial scaffold.

## Development stages

1. Contract and market-data infrastructure.
2. Options-chain snapshots and data-quality controls.
3. Greeks and implied-volatility calculations.
4. Contract selection and explainable signals.
5. Historical options backtesting with documented data provenance.
6. Paper execution with realistic bid/ask and cost assumptions.
7. Dashboard, audit journal and session reports.
8. Forward validation and independent readiness review.

## Data integrity requirements

Every stored observation should retain:
- exchange and instrument identifiers
- trading date and exchange timestamp
- contract expiry, strike and option type
- source and retrieval timestamp
- price/quantity fields and their availability
- data-quality flags

Do not backfill missing option prices with underlying prices. Do not infer executable fills from LTP when bid/ask data is available. Clearly label OHLC-only simulations.

## Status

This is the clean project foundation, not a completed trading system. Broker integration, historical option-data procurement, strategy validation and paper execution are intentionally not represented as finished.
