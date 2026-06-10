-- 008_options.sql
--
-- Adds option-specific metadata to orders + positions so a single table holds
-- all asset classes without per-class tables:
--   underlying  — the equity ticker driving the contract (e.g. "AAPL")
--   expiry      — contract expiry date (NULL for non-option rows)
--   strike      — strike price (NULL for non-option rows)
--   right       — "call" | "put" (NULL for non-option rows)
--   multiplier  — 100 for standard US equity options (NULL = default 100)
--   meta        — catch-all JSONB for entry IV, Greeks snapshot, audit refs
--
-- Also creates `option_quotes` for forward-collecting live chain snapshots
-- (feeds Phase 3 backtests once enough history accumulates).

-- ---------------------------------------------------------------------------
-- orders: option columns
-- ---------------------------------------------------------------------------

-- NOTE: "right" is a reserved SQL keyword — it must be double-quoted in raw SQL.
-- (SQLAlchemy auto-quotes it in the ORM, which is why mocked tests never caught it.)
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS underlying   VARCHAR(20),
  ADD COLUMN IF NOT EXISTS expiry       DATE,
  ADD COLUMN IF NOT EXISTS strike       NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS "right"      VARCHAR(4),
  ADD COLUMN IF NOT EXISTS multiplier   SMALLINT,
  ADD COLUMN IF NOT EXISTS meta         JSONB;

CREATE INDEX IF NOT EXISTS idx_orders_option_underlying
  ON orders(underlying, expiry)
  WHERE underlying IS NOT NULL;

-- ---------------------------------------------------------------------------
-- positions: option columns
-- ---------------------------------------------------------------------------

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS underlying   VARCHAR(20),
  ADD COLUMN IF NOT EXISTS expiry       DATE,
  ADD COLUMN IF NOT EXISTS strike       NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS "right"      VARCHAR(4),
  ADD COLUMN IF NOT EXISTS multiplier   SMALLINT,
  ADD COLUMN IF NOT EXISTS meta         JSONB;

CREATE INDEX IF NOT EXISTS idx_positions_option_underlying
  ON positions(underlying, expiry)
  WHERE underlying IS NOT NULL AND closed = FALSE;

-- ---------------------------------------------------------------------------
-- option_quotes — forward chain capture for backtest data accumulation
-- ---------------------------------------------------------------------------
-- One row per (underlying, expiry, strike, right, snapshot_ts).
-- TimescaleDB hypertable on snapshot_ts so old rows compress automatically.

CREATE TABLE IF NOT EXISTS option_quotes (
  underlying      VARCHAR(20)       NOT NULL,
  expiry          DATE              NOT NULL,
  strike          NUMERIC(12,4)     NOT NULL,
  "right"         VARCHAR(4)        NOT NULL,   -- "call" | "put"
  snapshot_ts     TIMESTAMPTZ       NOT NULL,
  bid             NUMERIC(12,4),
  ask             NUMERIC(12,4),
  last            NUMERIC(12,4),
  volume          INTEGER,
  open_interest   INTEGER,
  implied_vol     NUMERIC(8,4),
  delta           NUMERIC(8,4),
  gamma           NUMERIC(8,4),
  theta           NUMERIC(8,4),
  vega            NUMERIC(8,4),
  source          VARCHAR(32)       NOT NULL DEFAULT 'moomoo',
  PRIMARY KEY (underlying, expiry, strike, "right", snapshot_ts)
);

SELECT create_hypertable('option_quotes', 'snapshot_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_option_quotes_underlying
  ON option_quotes(underlying, expiry, snapshot_ts DESC);
