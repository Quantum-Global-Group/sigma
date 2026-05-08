-- 005_trading_and_asset_class.sql
--
-- Adds:
--   * asset_class column (nullable, backfilled to 'equity') on signal_history,
--     signal_cache, users (default user trading scope).
--   * internal flag on usage_logs for service-to-service worker traffic.
--   * Trading tables for the live loop: positions, orders, exit_state, candles.
--
-- Migration 006 will set asset_class NOT NULL after backfill verification.

-- ---------------------------------------------------------------------------
-- asset_class on existing tables (nullable, backfilled)
-- ---------------------------------------------------------------------------

ALTER TABLE signal_history
  ADD COLUMN IF NOT EXISTS asset_class VARCHAR(16);

ALTER TABLE signal_cache
  ADD COLUMN IF NOT EXISTS asset_class VARCHAR(16);

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS default_asset_class VARCHAR(16) DEFAULT 'equity';

UPDATE signal_history SET asset_class = 'equity' WHERE asset_class IS NULL;
UPDATE signal_cache   SET asset_class = 'equity' WHERE asset_class IS NULL;

-- signal_cache PK currently (ticker, timeframe). Crypto and equity tickers
-- collide (e.g. ETH on equities vs ETH-USD on crypto), so widen the PK.
ALTER TABLE signal_cache DROP CONSTRAINT IF EXISTS signal_cache_pkey;
ALTER TABLE signal_cache
  ALTER COLUMN asset_class SET DEFAULT 'equity',
  ALTER COLUMN asset_class SET NOT NULL;
ALTER TABLE signal_cache
  ADD CONSTRAINT signal_cache_pkey PRIMARY KEY (asset_class, ticker, timeframe);

CREATE INDEX IF NOT EXISTS idx_signal_history_asset_class
  ON signal_history(asset_class, ticker, created_at DESC);

-- Component-weight breakdown (model / sentiment / regime) used by the
-- razorBill-derived combiner. Stored as JSONB so the combiner stays free
-- to evolve without further migrations.
ALTER TABLE signal_history
  ADD COLUMN IF NOT EXISTS component_weights JSONB;

-- ---------------------------------------------------------------------------
-- Internal-traffic flag on usage_logs + seeded system user
-- ---------------------------------------------------------------------------
--
-- The worker uses an INTERNAL_SECRET header (see middleware/auth.py) to call
-- /signals on its own schedule. usage_logs.user_id is NOT NULL, so we seed a
-- single deterministic "system" user that owns all internal traffic. That
-- keeps every billing/usage query untouched (just filter `internal = false`
-- for paid traffic).

ALTER TABLE usage_logs
  ADD COLUMN IF NOT EXISTS internal BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_usage_logs_internal
  ON usage_logs(internal, created_at DESC) WHERE internal = TRUE;

-- Deterministic UUID so settings.system_user_id matches across environments.
INSERT INTO users (id, clerk_id, email, plan, default_asset_class)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'system:worker',
  'worker@sigma.internal',
  'enterprise',
  'crypto'
)
ON CONFLICT (clerk_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Candles (Timescale hypertable) — raw OHLCV per (asset_class, symbol, ts)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS candles (
  asset_class VARCHAR(16) NOT NULL,
  symbol      VARCHAR(32) NOT NULL,
  ts          TIMESTAMPTZ NOT NULL,
  timeframe   VARCHAR(10) NOT NULL,
  open        NUMERIC(20,8) NOT NULL,
  high        NUMERIC(20,8) NOT NULL,
  low         NUMERIC(20,8) NOT NULL,
  close       NUMERIC(20,8) NOT NULL,
  volume      NUMERIC(28,8) NOT NULL,
  source      VARCHAR(32),
  PRIMARY KEY (asset_class, symbol, timeframe, ts)
);

SELECT create_hypertable('candles', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts
  ON candles(asset_class, symbol, ts DESC);

-- ---------------------------------------------------------------------------
-- Positions — current open positions per house book (worker-managed)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS positions (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  asset_class     VARCHAR(16) NOT NULL,
  symbol          VARCHAR(32) NOT NULL,
  qty             NUMERIC(28,8) NOT NULL,
  entry_px        NUMERIC(20,8) NOT NULL,
  entry_ts        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  current_px      NUMERIC(20,8),
  unrealized_pnl  NUMERIC(20,8),
  realized_pnl    NUMERIC(20,8) NOT NULL DEFAULT 0,
  closed          BOOLEAN       NOT NULL DEFAULT FALSE,
  closed_at       TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_positions_open
  ON positions(asset_class, symbol) WHERE closed = FALSE;

-- ---------------------------------------------------------------------------
-- Orders — order/fill log (paper or live)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS orders (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  asset_class   VARCHAR(16) NOT NULL,
  symbol        VARCHAR(32) NOT NULL,
  ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  side          VARCHAR(8)  NOT NULL,           -- buy | sell
  qty           NUMERIC(28,8) NOT NULL,
  px            NUMERIC(20,8) NOT NULL,
  fee           NUMERIC(20,8) NOT NULL DEFAULT 0,
  slippage_bps  NUMERIC(10,4),
  executor      VARCHAR(32) NOT NULL,           -- paper | coinbase | ...
  external_id   VARCHAR(128),                   -- broker order id, if any
  status        VARCHAR(16) NOT NULL DEFAULT 'filled',
  raw           JSONB
);

CREATE INDEX IF NOT EXISTS idx_orders_symbol_ts
  ON orders(asset_class, symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_orders_external_id
  ON orders(external_id) WHERE external_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Exit state — per-position trailing stop / partial-TP bookkeeping
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS exit_state (
  position_id        UUID PRIMARY KEY REFERENCES positions(id) ON DELETE CASCADE,
  partial_tp_done    BOOLEAN NOT NULL DEFAULT FALSE,
  breakeven_px       NUMERIC(20,8),
  trailing_stop_px   NUMERIC(20,8),
  high_water_px      NUMERIC(20,8),
  last_evaluated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
