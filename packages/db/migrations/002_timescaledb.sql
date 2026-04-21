-- 002_timescaledb.sql

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Signal history (time-series — converted to hypertable below)
CREATE TABLE IF NOT EXISTS signal_history (
  id               BIGSERIAL,
  user_id          UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ticker           VARCHAR(20)  NOT NULL,
  timeframe        VARCHAR(10)  NOT NULL DEFAULT 'daily',
  signal           VARCHAR(10)  NOT NULL,
  confidence       NUMERIC(5,4) NOT NULL,
  predicted_return NUMERIC(8,6),
  model_version    VARCHAR(20)  NOT NULL,
  features         JSONB,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (id, created_at)
);

SELECT create_hypertable('signal_history', 'created_at', if_not_exists => TRUE);

-- Signal cache — avoids redundant ML calls within the TTL window
CREATE TABLE IF NOT EXISTS signal_cache (
  ticker           VARCHAR(20)  NOT NULL,
  timeframe        VARCHAR(10)  NOT NULL DEFAULT 'daily',
  signal           VARCHAR(10)  NOT NULL,
  confidence       NUMERIC(5,4) NOT NULL,
  predicted_return NUMERIC(8,6),
  model_version    VARCHAR(20)  NOT NULL,
  expires_at       TIMESTAMPTZ  NOT NULL,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (ticker, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_signal_history_user_ticker
  ON signal_history(user_id, ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_history_ticker
  ON signal_history(ticker, created_at DESC);
