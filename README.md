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

## Collect live option quotes (read-only)

Set these values in your local .env after creating a Kite Connect app and generating an access token:

```dotenv
KITE_API_KEY=your_api_key
KITE_ACCESS_TOKEN=your_daily_access_token
KITE_UNDERLYING_SPOT_INSTRUMENTS=NIFTY=NSE:NIFTY 50;BANKNIFTY=NSE:NIFTY BANK
```

Add one mapping per underlying. For stock options, the mapping usually uses the NSE cash symbol, for example `RELIANCE=NSE:RELIANCE`. For stock options, the underlying name must match the `name` field in Kite's NFO instrument master. Index underlyings with a blank name are resolved from known NFO symbol prefixes. Confirm exact spot symbols and exchanges in your Kite instrument master before use.

Start collection:

```powershell
tradinggpt-options collect-options --underlyings NIFTY,BANKNIFTY --strikes-each-side 3
```

The collector fetches the daily NFO master, obtains fresh underlying spot quotes, selects the nearest non-expired expiry and the configured strike window around ATM, then subscribes to those CE/PE contracts in full WebSocket mode. It persists every received quote, including full bid/ask depth, and prints a 30-second health summary. Press Ctrl+C to stop.

The collector is read-only: it does not submit, modify or cancel broker orders. It requires a valid daily Kite access token. Do not share credentials in chat or commit .env.

Backfill historical underlying candles (use timezone-aware timestamps):

```powershell
tradinggpt-options backfill-underlying --underlyings NIFTY,BANKNIFTY --from-date "2026-11-03T09:15:00+05:30" --to-date "2026-11-04T15:30:00+05:30" --interval 5minute
```

This stores underlying OHLCV/OI candles in a separate table. It does not create historical option premiums. Kite's continuous-history feature is for futures; do not treat it as an expired-options archive.


Run one read-only analysis pass:

```powershell
tradinggpt-options analyze-options --underlyings NIFTY,BANKNIFTY --strikes-each-side 3 --risk-free-rate 0.065 --interval 5minute
```

The command fetches current spot and option quotes, resolves the nearest NFO futures contract for volume-backed VWAP candles, downloads its recent history,
builds a quality-checked CE/PE chain view using spot for option moneyness/IV, and evaluates the explainable EMA9/EMA21,
session-VWAP, RSI14 and volume baseline. It prints CE, PE or NO_TRADE with the
selected contract and rationale. The risk-free rate is an explicit model assumption;
it is not fetched or silently guessed. The score is heuristic, not a win probability.
News, scheduled events and broad market regime are not yet integrated. This command
does not submit an order.

The CLI runs continuously until stopped. It does not yet provide a Windows service/task scheduler wrapper or automatic daily token generation.

## Run the API

```powershell
uvicorn tradinggpt_options.api.main:app --reload
```

Open http://127.0.0.1:8000/docs.

- GET /health — application and paper/live-mode status
- GET /api/v1/paper/account — persistent paper-account summary
- GET /api/v1/paper/trades?status=all|open|closed — trade history
- GET /api/v1/market/instruments?underlying=NIFTY — latest persisted option contracts
- GET /api/v1/market/quotes?limit=100 — latest persisted quote per contract, including full depth

There is no HTTP order-placement endpoint. The paper account is initialized by the CLI or local paper broker, not by a read-only API request.

## Implemented foundations

- Defensive parser for Kite's daily NFO option instrument master
- Read-only Kite REST adapter for instrument master and full quote snapshots
- Quote endpoint pacing and full-quote 500-instrument batch validation
- Full-depth WebSocket subscription helper (3,000 token guard) and lifecycle state callbacks
- Validated option contract, quote and order-book data models
- CE/PE strike pairing, nearest-expiry and ATM selection
- European Black–Scholes Greeks, implied-volatility bisection solver, quality-aware CE/PE chain view and explainable EMA/VWAP/RSI/volume baseline analysis CLI
- SQLite models/repository for instrument snapshots, quote snapshots, paper accounts and trades
- Premium-risk lot sizing
- Local long-option paper broker with depth-aware VWAP entries/exits, insufficient-depth rejection and effective-dated Zerodha/NSE option charges
- Bid-side mark-to-market equity, stale/missing quote rejection and duplicate-open-trade protection
- Read-only paper account, trade-history, instrument-master and latest-quote API endpoints
- GitHub Actions lint/test matrix for Python 3.12 and 3.13

## Known limitations

- Kite credentials have not yet been supplied or used to test the adapter against a real account.
- Live quote ingestion is available through the foreground `collect-options` CLI; Windows service/task scheduling, automatic token generation and robust process supervision remain future work.
- Quote snapshots preserve all available bid/ask depth levels; historical OHLCV candles have a separate validated adapter and idempotent storage. A quality-aware chain view calculates mid-price IV and European BSM Greeks; scheduled chain persistence, OI-change history and signal integration remain future work.
- The current Zerodha/NSE options charge schedule is effective from 1 April 2026 and is an estimate; reconcile against actual contract notes. Earlier effective-dated schedules, partial fills and physical settlement charges are not yet modelled. Paper fills require displayed depth for the full requested quantity; they do not simulate partial fills.
- Kite historical candles are supported for available instrument tokens, but its continuous-history feature is for futures, not expired options. Historical CE/PE contract data must be independently sourced or captured before expiry and validated before backtesting expired-option strategies.
- Greeks use European Black–Scholes assumptions; expiry calendar/time conventions and dividend/carry inputs require market-specific validation.
- No profitable strategy, 75% win rate, or live-trading readiness is claimed.
- Live order placement is not implemented.

## Development documents

- docs/CHARGES.md

- docs/ARCHITECTURE.md
- docs/DATA_CONTRACT.md
- docs/KITE_DATA_INTEGRATION.md
- docs/ONE_WEEK_MVP.md
- docs/ROADMAP.md
