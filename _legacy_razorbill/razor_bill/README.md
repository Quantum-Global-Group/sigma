razorBill – ML + Sentiment Trading System (MVP)

Overview
This repository contains an end-to-end, modular trading research and execution stack:

- Live data and sentiment ingestion
- Preprocessing and feature/sequence generation
- ML model inference producing trend + confidence
- Strategy layer combining ML and sentiment into a weighted signal
- Risk/position sizing and a paper trade executor
- PostgreSQL persistence for prices, sentiment, signals, orders, trades, positions
- FastAPI service and Streamlit dashboard

Quickstart (local, without Docker)
1) Python 3.11 recommended
2) Create a virtual environment and install requirements:
   - python -m venv .venv && source .venv/bin/activate
   - pip install -r requirements.txt
3) Optionally create a `.env` and set overrides (see example below).
4) Start the API:
   - uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
5) Start the dashboard:
   - streamlit run dashboard/app.py
6) Run the paper trading loop:
   - python main.py paper-live

Dynamic universe (optional)
- Enable automatic selection of trending Coinbase USD pairs by volatility and liquidity.
- Environment variables:
  - `DYNAMIC_UNIVERSE=true`
  - `UNIVERSE_QUOTE=USD` (also considers USDC-quoted pairs)
  - `UNIVERSE_TOP_N=6`
  - `UNIVERSE_REFRESH_MIN=30`
  - `VOL_TIMEFRAME=1m`, `VOL_LOOKBACK=600`
  - `MIN_QUOTE_VOLUME_24H=1000000`
Example:
```
export DYNAMIC_UNIVERSE=true
export UNIVERSE_QUOTE=USD
export UNIVERSE_TOP_N=6
export UNIVERSE_REFRESH_MIN=30
python main.py paper-live
```

Quickstart (Docker)
- docker compose up -d --build

Project layout
- razor_bill/: core Python package (config, db, models, pipeline, strategy, etc.)
- api/: FastAPI service
- dashboard/: Streamlit app


Notes
- This is an MVP with clear seams to extend (backtesting, real execution, scheduling, etc.).
- Uses async SQLAlchemy (asyncpg) for PostgreSQL access.


