# SIGMA — Models, Features & Training

How signals are produced, how models are trained and resolved, and how the
worker uses them. Reflects the equity-alpha state (post tradeFlux merge).

---

## Lifecycle at a Glance

```mermaid
flowchart LR
  subgraph train [Train]
    D[Unified market adapter: Tiingo → Alpaca → yfinance] --> BF["build_features(df)"]
    BF --> FIT[scripts/train_models.py] --> ART["{asset}_{type}_{version}.pkl"]
  end
  subgraph serve [Serve]
    ART --> REG["registry.resolve(asset_class)"]
    REG -->|hit| MODEL[Trained model]
    REG -->|miss| HEUR[_heuristic_predict]
  end
  subgraph worker [Worker tick]
    MODEL --> MP["_model_pred → {symbol: predicted_return}"]
    MP --> COMB["combiner.combine_signals(model_predictions=…)"]
  end
```

**Resolution order:** equity → `ensemble` → `lstm` → `quantum_hybrid`; crypto → `ranking` → `ensemble`. Trained registry models **always** consume `build_features(df)` — never `FeatureEngineer` output.

---

## Two feature builders — don't mix them

| Builder | File | Columns | Used by | Roadmap |
|---|---|---|---|---|
| `build_features` | `ml/features.py` | `rsi_14, roc_10, ema_20, ema_50, ema_ratio, bb_width, atr_14, volume_ratio, ret_1d, ret_5d` | **Trained models** (ensemble/LSTM/quantum), `ml/pipeline.py`, heuristic fallback | Unified feature store (backlog) |
| `FeatureEngineer.compute` | `ml/sequences.py` | `rsi, atr, ema_fast, ema_slow, mom_1/3/12, vol_realized, rolling_vol_50, v_spike, breakout_20, …` | **RankingModel** (crypto), **technical strategy combiner** (momentum, ICT, SDE, …) | Converge on shared column registry |

The two column sets are **disjoint**. A model trained on `build_features` will
`KeyError` if fed `FeatureEngineer` output. This bit us once (see "Worker model
wiring"); the rule is: **trained registry models always consume
`build_features(df)`**.

## Registry — resolution & artifact naming

`ml/models/registry.py::resolve(asset_class)` returns the first model that loads,
else `None` (callers fall back to `_heuristic_predict`).

Load order:
- **equity** → `ensemble` → `lstm` → `quantum_hybrid`
- **crypto** → `ranking` → `ensemble`

Artifact path: `{MODEL_DIR}/{asset_class}_{model_type}_{version}.{pkl|pt}`, with a
legacy fallback `{MODEL_DIR}/{model_type}_{version}.{ext}`. `MODEL_DIR` defaults
to `./ml/saved_models`; `version` defaults to `settings.model_version` (`v1.0`).

> **No equity model currently ships.** The legacy `ensemble_v1.0.pkl` was pulled
> on 2026-06-10 after the train gate (`ml/train_gate.py`) measured it edgeless —
> val_accuracy 0.348 vs majority baseline 0.377 with train_accuracy 0.90 (pure
> overfit). The registry resolves equity → None and the worker trades the
> technical-only blend. A replacement ships as `equity_ensemble_{version}.pkl`
> only when `train_models.py --ensemble` passes the gate.
>
> **Measured rejection (2026-06-12, `scripts/equity_feature_experiment.py`):**
> the obvious fixes don't rescue it. Across 5 purged+embargoed CV folds
> (`ml/cv.py`), normalizing the last raw price feature (atr_pct), extending
> history to 7y (14k rows), regularizing the trees (train_acc 0.93→0.42), and
> widening to a 30-name universe (43k rows) moved the edge from −2.9% to
> +0.3% — inside fold noise, with rank-IC ≈ 0 everywhere. **The current
> 19-feature technical set on daily bars has no measurable next-day
> directional signal.** Future attempts should change the *problem*, not the
> tuning: triple-barrier labels (`ml/triple_barrier.py`), return regression,
> intraday bars, or non-price features. (Equity meta-labeling and
> cross-sectional ranking were already measured REJECTs.)

## Measured-edge scoreboard (start here before proposing a model)

Every alpha candidate tried in this program, with its honest out-of-sample
verdict. The pattern is consistent: **price-only signals on liquid instruments
have no edge after cost.** Do not re-litigate a REJECT without changing the
*kind* of signal — re-running the same idea reproduces the same result.

| Candidate | Method | Verdict |
|---|---|---|
| Equity ML ensemble | `train_gate.py` chronological holdout | **REJECT** — val 0.348 < majority 0.377 (overfit) |
| Equity feature/model variants | `equity_feature_experiment.py`, purged CV | **REJECT** — edge ≈ 0, rank-IC ≈ 0 across atr_pct / 7y / regularized / 30-name |
| 11 technical strategies (per-strategy) | `strategy_edge_experiment.py`, net of cost | **REJECT** — coin-flip hit rates; only equity *beta* (buy & hold) is positive |
| Strategy reweighting / selection | `strategy_weight_fit.py`, train/test split | **REJECT** — edge-weighting fit on past data is *worse* than equal-weight OOS, on equity and forex |
| Forex mean-reversion family | `strategy_weight_fit.py` OOS | **REJECT** — in-sample only; −1.14 Sharpe on the hold-out |
| Crypto meta-labeling | `crypto_meta_revalidate.py`, 75d/80k bets, OOS | **REJECT** — base win 48.1%; meta gating gives zero lift at any tau; net −8 to −11 bps/trade. The earlier "win" was trained on ~1 day of data (the 5m adapter caps history at 24h) |
| Equity meta-labeling · cross-sectional ranking · funding rate | earlier alpha-research harnesses | **REJECT** (measured) |
| Stat-arb (pairs mean-reversion) | `statarb_experiment.py`, 28 pairs / 2798 held-out trades | **REJECT** — net −6.45 bps/trade after 4bps 2-leg cost. (A first pass showed a fake 100%-win/+1292bps — survivorship bug: non-reverting losers were never booked. Stop-loss + forced-close fixed it.) |
| Less-liquid technical | `illiquid_experiment.py`, 16 small/mid-caps @ 25bps | **REJECT** — blend net −25.5 bps/bar; wider spreads eat it, only beta positive |
| Event-driven news drift | `event_drift_experiment.py`, Alpaca news + FinBERT, per-name β, two regimes | **REJECT (regime-dependent)** — looked like a lead, failed the acid test. 2023–2025 bull: market-neutral strong +20 bps/trade (53% win). **2018–2021 (incl. the 2020 bear): −7.4 bps/trade, 46% win** — below a coin flip. Bull-regime momentum, not durable alpha. |
| **Trend-filtered diversified beta** | `cross_asset_experiment.py`, 26 ETFs/crypto, 2005–2026 monthly | **PASS (smart beta, not alpha)** — long each asset only above its N-month MA, else cash. Sharpe **0.98 vs 0.72 buy&hold**; robust across MA 7–12m; **stable both halves (0.85 → 1.05, no decay)**; 2008 −4% vs −25%, maxDD **9% vs 43%**. The ONLY result to clear the cross-regime bar. It is *timing of market exposure* (risk-managed beta), not market-neutral alpha. |

**Net position (2026-06-16): no market-neutral ALPHA exists in anything tested —
but risk-managed BETA does, robustly.** Every market-neutral / directional alpha
candidate rejects out of sample after cost (ML, all technical, reweighting,
stat-arb, illiquid, news drift). The one thing that survives the cross-regime bar
is *smart beta*: a broadly-diversified long book (buy&hold Sharpe 0.72) overlaid
with a simple trend filter to sidestep crashes (Sharpe ~0.98, maxDD 9% vs 43%) —
robust to the MA length and across both halves incl. 2008/2020/2022. Its value is
**drawdown/crisis protection + behavioral discipline, not excess return** (it
slightly underperforms buy&hold in relentless bulls). For a retail operator this
is the realistic edge: diversify, don't overtrade, trend-filter exposure. Any
*alpha* candidate must still be different in *kind* AND clear the market-neutral
cross-regime bar (codified in `ml/edge_eval.py` + the protocols here); the
remaining untested ones (earnings-surprise drift, intraday reaction, less-covered
universes, options structure) have lower priors.

**Operational consequence:** the nightly `fit_strategy_weights` job fits weights
from in-sample `signal_history`; the OOS test above shows that overfits, so it
should keep equal weights (or be gated by a holdout) rather than ship fitted
ones. And the worker should not trade the equity blend live as an alpha source —
it is beta-minus.

## The one deployable conclusion (`retail_portfolio_backtest.py`)

The four surviving ideas combined into one monthly-rebalanced portfolio
(diversified sleeves + 10-month trend filter to cash), 2005–2026 incl. 2008/2020/2022:

| Strategy | CAGR | Sharpe | maxDD | 2008 |
|---|---|---|---|---|
| SPY buy & hold | **11.0%** | 0.78 | **−50.8%** | −36.8% |
| 60/40 | 8.3% | 0.84 | −28.5% | −13.4% |
| **Diversified + Trend** | 8.3% | **1.25** | **−12.5%** | **+8.0%** |
| Equal-wt + Trend | 9.8% | 1.22 | −10.3% | +3.5% |

**Verdict: a real, deployable, retail-implementable strategy — but it is
risk-managed beta, not alpha.** Sharpe 1.25 vs 0.78 (SPY); max drawdown −12.5%
vs −51%; *positive* in 2008. The honest trade-off: it gives up ~2–3%/yr of raw
CAGR for ~⅓ the drawdown and half the volatility — a path most investors can
actually stick with (vs panic-selling a −51% drawdown). It does not beat the
market on raw return; it makes beta survivable. This is the realistic edge for a
retail operator, and the only strategy in the program cleared for deployment.

## Training

Data for all equity training flows through the unified adapter
(`markets.equity` → Alpaca → Tiingo), so **training and serving use
identical bars**.

```bash
cd apps/api
# Equity ensemble (RandomForest + XGBoost soft-vote) on daily bars:
PYTHONPATH=. python scripts/train_models.py --ensemble       # -> ensemble_v1.0.pkl
#   --lstm / --quantum-hybrid / --all  also available (slower)

# Crypto RankingModel (LightGBM) on Coinbase 5m candles:
PYTHONPATH=. python scripts/train_ranking.py                 # -> crypto_ranking_v1.0.pkl
```

`scripts/train_models.py` labels next-day return at ±0.5% into BUY/HOLD/SELL and
trains on `DEFAULT_TICKERS` (AAPL, MSFT, GOOG, AMZN, META, NVDA, TSLA, JPM, V,
WMT). Override with `--tickers ...` / `--version ...`.

### Verify a freshly trained artifact
```bash
PYTHONPATH=. python -c "
from ml.models.registry import resolve, clear_cache
clear_cache(); m = resolve('equity'); print(type(m).__name__, m.feature_names)"
```

## Worker model wiring

Each tick (`apps/worker/tick.py`):
1. `model = _resolve_model(asset_class)` — once per tick (registry is cached).
2. Per symbol, `_model_pred(model, symbol, df)` builds `build_features(df)` and
   calls `model.predict(...)`, returning `{symbol: predicted_return}` (or `{}`
   when no model / empty data — clean technical-only fallback).
3. That dict is passed to `combiner.combine_signals(..., model_predictions=...)`
   so `MLStrategy` contributes the trained signal alongside the technical
   strategies.

## Shipping the model to production

The worker image bundles the artifact: `.dockerignore` excludes
`ml/saved_models/*.pkl` **except** `!apps/api/ml/saved_models/ensemble_v1.0.pkl`.
Because the worker image copies `apps/api` to `/app/api` (CMD runs from `/app`),
`apps/worker/fly.toml` sets `MODEL_DIR=/app/api/ml/saved_models` so the registry
finds it. (The API image copies `apps/api` to `/app`, so its default
`./ml/saved_models` is already correct.)

~3 MB binary in git is acceptable for the alpha; move to object storage if the
retrain cadence grows (see roadmap backlog).

## Retrain cadence (alpha guidance)

- Equity ensemble: retrain weekly or when rank-quality visibly drifts; commit the
  new `ensemble_v1.0.pkl` and redeploy the worker.
- Keep `version` bumps (`v1.1`, …) for breaking feature changes; the alpha
  overwrites `v1.0` in place for routine retrains.
- **Weekly strategy review:** after labeled outcomes accumulate, pull
  `GET /strategies/performance/report?period=7d` (or open `/strategies`) and paste
  the markdown `summary` into the sprint retro in `docs/ROADMAP.md`.
- Open backlog: Optuna hyperparameter search, rank-IC regression gate in CI,
  online/incremental refit, object-storage delivery instead of image-baked,
  unified feature store (`build_features` ↔ `FeatureEngineer`).

## MLflow experiment names

Training runs log to per-family MLflow experiments (see `ml/experiment.py`):

| asset_class | model_type | experiment |
|---|---|---|
| equity | ensemble | `sigma-equity-ensemble` |
| equity | lstm | `sigma-equity-lstm` |
| equity | quantum_hybrid | `sigma-equity-quantum-hybrid` |
| crypto | ranking | `sigma-crypto-ranking` |
| crypto | ensemble | `sigma-crypto-ensemble` |
| forex | ensemble | `sigma-forex-ensemble` |

`start_run(..., tags={"asset_class": "...", "model_type": "..."})` selects the
experiment automatically. Override the tracking URI with `MLFLOW_TRACKING_URI`; the
legacy `MLFLOW_EXPERIMENT` setting is the fallback when tags are absent.

## Signal embeddings (pgvector)

Migration `012_pgvector_embeddings.sql` adds `signal_embeddings` for similarity
search over labeled signals. Embed labeled rows:

```bash
make migrate   # applies 012 (requires pgvector extension on Postgres)
cd apps/api && PYTHONPATH=. python scripts/embed_signals.py --asset-class equity
```

Enable the nightly scheduler job with `EMBED_SIGNALS_ENABLED=true` (default off).

## Audit records & strategy reports

Migration `009_decision_logging.sql` created `audit_records`; equity/crypto/forex
ticks (`apps/worker/tick.py`) build an in-memory `AuditLog` per cycle and persist
every symbol evaluation via `db.audit_store.persist_audit_log`. Each row captures
data/features/signal JSON, gate chain (e.g. `G2_signal` with reasons like
`HOLD signal`), and final decision (`placed`, `skipped`, `rejected`). Options
ticks use the same store (`apps/worker/options_tick.py`).

Query examples: [`docs/E2E_VALIDATION.md`](E2E_VALIDATION.md) § Audit & strategy reports.

**Weekly strategy review** — aggregate labeled `signal_history` by component
strategy (`ml/strategy_performance.py`):

```bash
curl -s "http://localhost:8001/strategies/performance/report?asset_class=equity&period=7d" \
  -H "Authorization: Bearer <api-key>" | jq
```

Response includes per-strategy win rates above a strength threshold plus a
markdown `summary` field suitable for paste into a weekly retro. Use
`/strategies/performance?period=7d` for the same stats without forcing the
report defaults. Dashboard: `/strategies` (Next.js; equity + 7d default).

## Model promotion reports

When the self-evolving loop proposes a new artifact (`model_promotions` row),
compare candidate vs incumbent before approve/reject:

```bash
curl -s "http://localhost:8001/models/promotions/<promotion-id>/report" \
  -H "Authorization: Bearer <api-key>" | jq '.summary, .comparison, .recommendation'
```

Returns structured JSON: incumbent/candidate `ModelEvaluation` snapshots, metric
deltas, `recommendation` (`candidate_leads`, `review`, …), and markdown
`summary`. Approve/reject remain internal-only (`X-Internal-Secret` or internal auth).

## Strategy comparison CLI

Compare strategies across a ticker universe without placing orders:

```bash
cd apps/api
PYTHONPATH=. python scripts/compare_universe_strategies.py --asset-class equity --strategies momentum,ict,ml
```

**Emerging Tech 16 (report-only):** pass all 16 PDF tickers via `--symbols` (see
[`docs/universes/EMERGING_TECH_16.md`](universes/EMERGING_TECH_16.md) and the
example in [`EMERGING_TECH_WORK_PLAN.md`](universes/EMERGING_TECH_WORK_PLAN.md)).
Does not load ensemble predictions today (`model_predictions={}` in the script).
Live worker universe remains `EQUITY_UNIVERSE` mega-caps until the work plan
live-trading section is complete.
