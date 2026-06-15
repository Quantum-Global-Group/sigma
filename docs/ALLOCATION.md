# SIGMA — Trend-Filtered Allocation (the deployable strategy)

> The one strategy that cleared the cross-regime, cost-aware bar. It is
> **risk-managed beta, not alpha** — read that twice before deploying.

## What it is

Hold a diversified book of ETF sleeves, but only the sleeves **currently above
their 10-month moving average**; the rest sits in cash. Rebalance **monthly**.
That's the whole strategy. It replaces the directional equity signals the worker
used to run, which were [measured edgeless](MODELS.md).

```
Once a month, for each sleeve:  price > 10-month average ?
    yes → hold its target weight
    no  → move that weight to cash
```

## One Alpaca account — no OANDA, no Coinbase

Every sleeve is an Alpaca-tradeable ETF, so a single brokerage covers all asset
classes. Currency and crypto exposure come through ETF "wrappers" instead of
separate forex/crypto accounts:

| Exposure | Sleeve(s) |
|---|---|
| US / foreign / EM equity | SPY · EFA · EEM |
| Bonds | TLT · IEF |
| Gold / commodities | GLD · DBC |
| Real estate | VNQ |
| **Currencies** (no OANDA) | **UUP** (USD) · **FXE** (euro) |
| **Bitcoin** (no Coinbase) | **IBIT** |

(The backtest validates the Bitcoin sleeve with `BTC-USD` as the price proxy —
`IBIT` only lists from 2024 but tracks the same asset.) Same one-question method
applies to every sleeve.

## Why this and nothing else

After a research program where every market-neutral / directional alpha candidate
rejected out of sample (the full scoreboard is in [`MODELS.md`](MODELS.md)), this
was the only thing that survived a backtest across **2005–2026 incl. 2008 / 2020 /
2022** (`scripts/retail_portfolio_backtest.py`):

| Strategy | CAGR | Sharpe | maxDD | 2008 |
|---|---|---|---|---|
| SPY buy & hold | 11.0% | 0.78 | −50.8% | −36.8% |
| 60/40 | 8.3% | 0.84 | −28.5% | −13.4% |
| **Diversified + Trend** | 8.3% | **1.25** | **−12.5%** | **+8.0%** |
| Equal-wt + Trend | 9.8% | 1.22 | −10.3% | +3.5% |

It does **not** beat the market on raw return — it gives up ~2–3%/yr of CAGR for
~⅓ the drawdown and half the volatility. Its value is **crisis protection +
behavioral discipline**: a −12.5% worst case is a path you can actually hold,
versus panic-selling a −51% crash. It robustly cleared the same cross-regime bar
that killed every alpha candidate (Sharpe stable across both halves; positive in
2008). It will *underperform* buy & hold in a relentless bull.

## How it's wired

| Piece | File |
|---|---|
| Strategy core (pure, tested) | `apps/api/ml/allocation.py` — `target_weights` (trend filter) + `rebalance_orders` |
| Worker path | `apps/worker/allocation_tick.py` — monthly rebalance via the equity executor, reusing the tick's idempotent persist |
| Dispatch | `apps/worker/main.py` — `allocation` asset-class routes to the rebalancer |
| Backtest / evidence | `apps/api/scripts/retail_portfolio_backtest.py` |

It runs on the worker cadence (default 6h check) but **acts once per calendar
month** (Redis-guarded + a monthly idempotency key on the order id), faithful to
the backtest. Trades the equity executor (Alpaca paper); positions live in the
house book.

## Enabling it

```toml
# apps/worker/fly.toml [env] (or secrets)
WORKER_ASSET_CLASSES = "allocation"     # instead of "equity" — don't run both on
                                        # the same book; they'd fight over positions
ALLOCATION_ENABLED   = "true"
# defaults (override if desired):
# ALLOCATION_WEIGHTS = "SPY:0.30,EFA:0.10,EEM:0.05,TLT:0.15,IEF:0.10,GLD:0.10,DBC:0.05,VNQ:0.05"
# ALLOCATION_MA_MONTHS = 10
# ALLOCATION_MIN_TRADE_USD = 50
```

**Acceptance:** during US market hours, on the first tick of a new month, the
worker logs `[allocation] YYYY-MM ... orders=N` and `orders` rows appear with the
sleeve symbols; `select symbol, qty from positions where closed=false` matches the
in-trend sleeves.

## The income add-on — options premium (defined-risk)

On top of the core, a small **options sleeve** harvests the one *structural* edge
that survives in the options asset class: the volatility risk premium. People
overpay for crash insurance, so *selling* it pays — but only if your loss is
**capped** (naked short vol drew down −92% in the research, `vol_premium_experiment.py`).

The strategy brain is built (`ml/options_income.py`, `select_put_credit_spread`):
given the underlying and a small risk budget (≈10% of equity), it picks a
**put credit spread** — sell a put ~5% below the market, buy a further put that
**caps the max loss** — and sizes contracts so the worst case can't exceed the
budget. Settings: `options_income_*` in config. Collect a premium most months;
a crash costs the bounded spread width, never more.

**Not yet wired for live trading.** Execution needs an Alpaca *options* path
(multi-leg orders + chain quotes); the current options executor is Moomoo/OpenD
(local), which would break the one-account goal. That executor + a monthly
options-income tick is the next build. It also can't be cross-regime backtested
(Alpaca options history is ~2y) — the VXX vol-premium test is the evidence; it
runs paper-first.

## Honest limits / follow-ups

- **Smart beta, not alpha.** Don't market the drawdown reduction as outperformance.
- **One book.** Allocation and the directional equity tick must not both run —
  they'd both manage equity positions in the house account.
- **Bitcoin sleeve uses `IBIT`** live (Alpaca ETF); the backtest proxies it with
  `BTC-USD` since IBIT only lists from 2024.
- **Options income execution** is built as the brain only; the Alpaca multi-leg
  options executor is the next step.
- Same as the rest of the system: **paper until the cross-regime bar is honored
  in production**; the allocation is the only strategy that has cleared it.
