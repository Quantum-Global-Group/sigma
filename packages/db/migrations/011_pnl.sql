-- 011_pnl.sql
--
-- Equity curve: a periodic snapshot of total account value + P&L so the
-- dashboard can chart account growth/drawdown over time. Written by the
-- worker-internal scheduler's daily equity_snapshot_job (and on demand).

CREATE TABLE IF NOT EXISTS equity_snapshots (
  ts                TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  base_equity       NUMERIC(20,2) NOT NULL,   -- starting/contributed capital
  total_realized    NUMERIC(20,2) NOT NULL DEFAULT 0,
  total_unrealized  NUMERIC(20,2) NOT NULL DEFAULT 0,
  total_value       NUMERIC(20,2) NOT NULL,   -- base + realized + unrealized
  by_asset_class    JSONB,                     -- {equity: {...}, forex: {...}, ...}
  PRIMARY KEY (ts)
);

SELECT create_hypertable('equity_snapshots', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_equity_snapshots_ts
  ON equity_snapshots(ts DESC);
