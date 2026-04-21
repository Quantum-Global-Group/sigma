-- 004_portfolio_snapshots.sql

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  id                   BIGSERIAL,
  user_id              UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  holdings             JSONB        NOT NULL,
  total_value          NUMERIC(15,2),
  optimization_method  VARCHAR(50),
  target_allocation    JSONB,
  recommended_trades   JSONB,
  sharpe_ratio         NUMERIC(8,4),
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (id, created_at)
);

SELECT create_hypertable('portfolio_snapshots', 'created_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_user
  ON portfolio_snapshots(user_id, created_at DESC);
