# SIGMA — MT5 / BlackBull bridge deploy

MT5 does not run cleanly on the ARM DGX because the official Python package
expects a local MetaTrader terminal. Run the terminal and bridge on EvoX2
Windows; keep the SIGMA worker, DB writes, scheduler, and training on DGX.

## Architecture

- EvoX2 Windows: BlackBull demo MT5 terminal + `services/mt5-bridge` on `:8787`
- DGX: normal `apps/worker` process; forex symbols route per symbol
- Postgres/Redis: unchanged shared state for candles, orders, audit, labels

OANDA remains the default forex adapter/executor. Symbols listed in
`FOREX_MT5_SYMBOLS` route through the MT5 bridge.

## EvoX2 setup

1. Install MetaTrader 5 and log into the BlackBull demo account.
2. Copy the exact server name from the MT5 login dialog.
3. Create a Python 3.12 venv in `services/mt5-bridge`.
4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Create `.env` from `.env.example`:

```env
MT5_BRIDGE_SECRET=change-me
MT5_LOGIN=123456
MT5_PASSWORD=...
MT5_SERVER=BlackBullMarkets-Demo
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
MT5_PAPER=true
```

6. Start the bridge:

```bash
uvicorn main:app --host 0.0.0.0 --port 8787
```

Restrict Windows Firewall inbound `8787` to the DGX LAN IP.

## DGX env

```env
FOREX_EXECUTOR=oanda
FOREX_UNIVERSE=EUR_USD,GBP_USD,XAUUSD
FOREX_MT5_SYMBOLS=XAUUSD
MT5_BRIDGE_URL=http://<EvoX2-LAN-IP>:8787
MT5_BRIDGE_SECRET=<same-secret>
MT5_PAPER=true
MT5_ALLOW_LIVE=false
```

`FOREX_EXECUTOR=mt5` is also supported for an all-MT5 forex worker, but mixed
routing is safer: OANDA symbols keep using OANDA while only `FOREX_MT5_SYMBOLS`
use the bridge.

## Verify

On EvoX2:

```bash
curl -H "X-MT5-Bridge-Secret: $MT5_BRIDGE_SECRET" http://localhost:8787/health
```

On DGX:

```bash
cd apps/api
PYTHONPATH=. python scripts/check_mt5_bridge.py --symbol XAUUSD
```

Then run one forex tick during FX market hours and confirm:

- `/health/worker` includes `mt5_bridge`
- `candles` stores MT5-routed OHLCV
- `audit_records` and `signal_history` include the routed symbol
- `orders.executor = 'mt5_bridge'` when an order is placed

## Safety

- Keep `MT5_PAPER=true` and `MT5_ALLOW_LIVE=false` until the paper run is clean.
- The worker skips MT5-routed symbols when the bridge health probe fails; OANDA
  symbols continue.
- MT5 order volume is lots. By default SIGMA converts base units to lots with
  `MT5_UNITS_PER_LOT=100000`. Set `MT5_QTY_IS_LOTS=true` only if worker sizing is
  already emitting lots.
