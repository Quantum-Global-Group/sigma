# SIGMA — Models, Features & Training

How signals are produced, how models are trained and resolved, and how the
worker uses them. Reflects the equity-alpha state (post tradeFlux merge).

## Two feature builders — don't mix them

| Builder | File | Columns | Used by |
|---|---|---|---|
| `build_features` | `ml/features.py` | `rsi_14, roc_10, ema_20, ema_50, ema_ratio, bb_width, atr_14, volume_ratio, ret_1d, ret_5d` | **Trained models** (ensemble/LSTM/quantum), the API signal pipeline (`ml/pipeline.py`), the heuristic fallback |
| `FeatureEngineer.compute` | `ml/sequences.py` | `rsi, atr, ema_fast, ema_slow, mom_1/3/12, vol_realized, rolling_vol_50, v_spike, breakout_20, …` | The **RankingModel** (crypto) and the **technical strategy combiner** (momentum, mean-reversion, MACD, SDE, ICT, …) |

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

> The equity ensemble currently ships as `ensemble_v1.0.pkl` (legacy name) and
> loads via the fallback path. `equity_ensemble_v1.0.pkl` would also work.

## Training

Data for all equity training flows through the unified adapter
(`markets.equity` → Tiingo → Alpaca → yfinance), so **training and serving use
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
- Open backlog: Optuna hyperparameter search, rank-IC regression gate in CI,
  online/incremental refit, object-storage delivery instead of image-baked.
