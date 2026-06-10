# SIGMA — Strategy Reference & Testing

How signals are generated per asset class, what each strategy does, how the
options pipeline validates trades, and what commands to run for verification.

---

## Signal Combiner Architecture

Each asset class maintains a list of strategy functions. At tick time the
worker computes all strategies, blends them into a single score
(`−1.0` … `+1.0`), and converts that score to an `OrderIntent`:

```
Bar (OHLCV) ─┬─ momentum ─────┐
              ├─ mean_reversion │
              ├─ breakout       │
              ├─ regime         │
              ├─ ml             ├──→ [−1..+1] ═══ OrderIntent
              ├─ macd           │    (vote-weighted  (BUY/SELL/HOLD
              └─ … (per class) ─┘     average)      + size)
```

**Voting model:** Each strategy returns `+1` (BUY), `−1` (SELL), or `0` (HOLD).
The combiner average-weights them (every strategy has equal vote). A threshold
(default `±0.15`) controls whether a lean becomes an actual `OrderIntent`.

---

## Per-Asset-Class Strategy Lists

| Asset | Strategies | Bar Period | Data Source | Execution |
|---|---|---|---|---|
| **Equities** | 11: momentum, mean_reversion, breakout, regime, ml, macd, fourier, gbm, ou, heston, ict | Daily | Alpaca → Tiingo | Alpaca (fractional) |
| **ETFs** | Same 11 as equities | Daily | Alpaca → Tiingo | Alpaca (fractional) |
| **Forex** | 7: momentum, mean_reversion, breakout, regime, ml, macd, fourier | 4H | MT5 bridge → OANDA | MT5 bridge → OANDA |
| **Options** | Underlying equity strategies + 5 validation gates | Daily (signal) | Moomoo/OpenD | Moomoo/OpenD (paper) |
| **Crypto** | 7: momentum, mean_reversion, breakout, regime, ml, macd, fourier | 5m | Coinbase | Paper (Coinbase when ready) |

**Implementation:** `apps/api/ml/strategies.py::compute_strategies()` dispatches
to per-asset-class functions `equity_strategies()`, `forex_strategies()`,
etc. The combiner lives in `compute_signal()` in the same file.

---

## Equity & ETF Strategies

Equities and ETFs share the same 11-strategy set. ETFs are treated as equity
symbols (part of `EQUITY_UNIVERSE` or `OPTION_UNIVERSE`) and trade via the same
Alpaca executor with fractional shares.

### Strategy Descriptions (Equity / ETF)

| # | Strategy | Category | What It Does |
|---|---|---|---|
| 1 | **momentum** | Trend | Compares `roc_10` and `mom_12` to a rolling mean; leans BUY when ROC > 1σ above mean, SELL when < 1σ below |
| 2 | **mean_reversion** | Mean-reverting | Z-score of `rsi_14` relative to rolling 63-day mean/std; leans BUY when oversold (z < −1.5), SELL when overbought (z > +1.5) |
| 3 | **breakout** | Volatility | Detects when price breaks above/below Bollinger Bands (2σ, 20d) with confirmation from `bb_width` expansion |
| 4 | **regime** | Macro | Combines 20d vs 50d EMA slope with `atr_14` normalized to 63d ATR; assigns bull/bear/crab regime |
| 5 | **ml** | ML | Calls the registry's first-loaded model (ensemble → LSTM → quantum_hybrid) via `predict()`. Falls to HOLD if no model loads |
| 6 | **macd** | Trend | MACD histogram cross (12/26/9); signal line cross direction |
| 7 | **fourier** | Cycle | FFT-based dominant cycle detection (top 5 frequencies); BUY when price is at cycle trough, SELL at crest |
| 8 | **gbm** | SDE | Geometric Brownian Motion drift (μ − σ²/2) over 63-day lookback; BUY on positive drift, SELL on negative |
| 9 | **ou** | SDE | Ornstein-Uhlenbeck mean-reversion speed θ; BUY when speed > threshold (fast reversion upward), SELL when below |
| 10 | **heston** | SDE | Heston stochastic-vol drift (same formula as GBM but with vega-weighted vol estimate); BUY/SELL on drift sign |
| 11 | **ict** | Discretionary | ICT "killzone" / time-based pattern detection (simplified); checks intraday candle patterns and session timing relative to NY open |

SDE strategies (gbm, ou, heston) assume `dt = 1/252` (daily bars).

### Equity & ETF Universe

- **Equity universe (live):** `EMERGING_TECH_16` — 16 tickers (AAPL, MSFT, NVDA,
  AMZN, GOOGL, META, TSLA, AVGO, AMD, SNAP, PLTR, SHOP, CRWD, DDOG, SNOW,
  TSM). Defined in `docs/universes/EMERGING_TECH_16.md`.
- **ETF universe:** Symbols are part of `EQUITY_UNIVERSE`; currently includes
  `SPY`, `QQQ` (also listed in `OPTION_UNIVERSE` for the options pipeline).

---

## Forex Strategies

7 strategies for forex. No SDE strategies (gbm, ou, heston) — the 4H bar period
is too short for their parameterization (they assume daily data and `dt = 1/252`).
No ICT strategy (time-based patterns are equity-only).

| # | Strategy | Notes |
|---|---|---|
| 1–7 | momentum, mean_reversion, breakout, regime, ml, macd, fourier | Same logic as equity, parameterized for 4H bars |

### Forex Universe

| Symbol | Description |
|--------|-------------|
| `EUR/USD` → `EUR_USD` | Euro vs USD |
| `GBP/USD` → `GBP_USD` | Pound vs USD |
| `AUD/USD` → `AUD_USD` | Aussie vs USD |
| `USD/JPY` → `USD_JPY` | Dollar vs Yen |
| `USD/CAD` → `USD_CAD` | Dollar vs Canadian Dollar |
| `XAUUSD` | Gold vs USD |

All route through the MT5 bridge when `FOREX_EXECUTOR=mt5`.

---

## Options Pipeline

The options worker (`apps/worker/options_tick.py`) runs on a separate tick cycle
from equities/forex. It starts with the underlying equity signal and applies five
validation gates:

```
Underlying signal ─→ G1: Chain health ─→ G2: Liquidity ─→ G3: Spread ─→ G4: Greeks ─→ G5: Sizing ─→ Option order
                      (is chain fresh)   (volume >           (bid/ask            (delta /         (max notional
                                           minContracts)       spread <           gamma /          per structure)
                                                                maxSpread)         theta OK)
```

| Gate | Check | Threshold |
|---|---|---|
| G1 | Chain available + timestamps < 60s old | Fail → skip symbol |
| G2 | Volume > minimum contracts | `min_contracts=10` |
| G3 | Bid/ask spread ratio | `max_spread=0.15` |
| G4 | Greeks within bounds | delta `[0.3, 0.7]`, gamma < 0.1, theta > −0.05 |
| G5 | Notional < account_limit | `max_notional=50_000` per structure |

When all gates pass, the pipeline constructs a multi-leg structure:

| Structure | Legs | Use Case |
|---|---|---|
| **Covered call** | Buy 100 shares + sell 1 call | Mildly bullish |
| **Cash-secured put** | Sell 1 put + hold cash collateral | Mildly bullish / neutral |
| **Vertical spread** | Buy 1 OTM call + sell 1 further OTM call | Directional with capped risk |
| **Iron condor** | Buy put spread + buy call spread | Low volatility |

### Options Universe

| Ticker | Description |
|---|---|
| `AAPL` | Apple |
| `MSFT` | Microsoft |
| `NVDA` | NVIDIA |
| `SPY` | SPDR S&P 500 ETF |
| `QQQ` | Invesco QQQ Trust |

---

## Crypto Strategies

7 strategies (same as forex). Not yet triggering live orders (`CRYPTO_EXECUTOR=paper`).

### Crypto Universe

| Symbol | Description |
|---|---|
| `BTC-USD` | Bitcoin |
| `ETH-USD` | Ethereum |
| `SOL-USD` | Solana |
| `LINK-USD` | Chainlink |
| `AVAX-USD` | Avalanche |

---

## Testing Guide

### Per-Broker Connectivity

| Command | What It Checks |
|---|---|
| `scripts/check_mt5_bridge.py --symbol XAUUSD` | MT5 bridge reachable, symbol pricing good |
| `scripts/check_moomoo_opend.py` | OpenD gateway reachable, options chains loaded |
| `scripts/check_alpaca.py` (if exists) | Alpaca account + data feed |
| `scripts/check_oanda.py` (if exists) | OANDA account + pricing |

Run from `apps/api/` with the venv active.

### Offline Smoke Test

```bash
make e2e
```

Runs 8 checks: lint (ts + py), build (web + api), imports, schema export.
Does not start containers or hit external APIs. Quick pre-commit validation.

### Strategy Comparison

```bash
cd apps/api
.venv/bin/python scripts/compare_universe_strategies.py
```

Produces a table comparing the 11 equity strategies across the EMERGING_TECH_16
universe (buy/sell/hold counts per strategy, signal score distribution).

### Manual Signal Generation

```bash
curl -s -X POST http://localhost:8001/signals \
  -H "Content-Type: application/json" \
  -d '{"symbols":["AAPL","MSFT","NVDA"], "asset_class":"equity"}' \
  | python3 -m json.tool
```

Returns per-symbol vote breakdown, combined score, and resulting `OrderIntent`.

### Weekly Performance Review

```bash
curl -s http://localhost:8001/strategies/performance/report | python3 -m json.tool
```

Returns strategy-level win rates, average PnL per vote, and a per-strategy
summary for the trailing 7 days.

### Execution Status

```bash
curl -s http://localhost:8001/execution/status | python3 -m json.tool
```

Shows per-pair paused/resumed state, current position, and broker connection
health.

### Worker Health

```bash
curl -s http://localhost:8001/health/worker | python3 -m json.tool
```

Returns per-asset-class heartbeat timestamps, lock status, and last tick time.

### Manual Debug Tick

```bash
curl -s -X POST http://localhost:8001/execution/run_cycle \
  -H "Content-Type: application/json" \
  -d '{"asset_class":"equity"}' \
  | python3 -m json.tool
```

Triggers a single tick cycle (fetch → signal → order → reconcile). Useful for
debugging without waiting for the scheduler.

### Top-Level Endpoint Smoke Test

```bash
# Core health
curl -s http://localhost:8001/health
curl -s http://localhost:8001/ready

# Positions & orders
curl -s http://localhost:8001/positions | python3 -c "import sys,json; print(len(json.load(sys.stdin)), 'positions')"
curl -s http://localhost:8001/orders | python3 -c "import sys,json; print(len(json.load(sys.stdin)), 'orders')"

# Portfolio
curl -s http://localhost:8001/portfolio/pnl

# Model registry
curl -s http://localhost:8001/models/champions
curl -s http://localhost:8001/models/evaluations

# Web UI (Next.js)
curl -so /dev/null -w "%{http_code}" http://localhost:3001
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `POST /signals` returns 500 after pipeline runs | SQLAlchemy async session cleanup race | Races are harmless; signal + orders still saved. Add `await asyncio.sleep(0.1)` after commit as workaround |
| Worker heartbeats stale | Redis connection lost or tick cycle blocked | Check `REDIS_URL`, restart worker: `make restart-worker` |
| MT5 bridge errors | Bridge process not running on EvoX2 | SSH to EvoX2, check `services/mt5-bridge/` logs, restart subprocess |
| OpenD not connecting | Gateway not launched or wrong host/port | On EvoX2 verify `OpenD.exe LoginUid=<account>` is running; check firewall port 11111 |
| Alpaca data stale | API key expired or paper account balance low | Verify at https://app.alpaca.markets/paper; reload `.env` |
| OANDA connection failure | Token rotated or account ID changed | Regenerate token at OANDA practice dashboard; update `.env` |
| Missing forex bars for EUR_USD | Symbol not mapped to MT5 bridge + bridge down | Verify MT5 bridge health; symbol is routed via MT5 when `FOREX_EXECUTOR=mt5` |
