-- 001_initial_schema.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users (managed by Clerk, mirrored here for FK integrity)
CREATE TABLE IF NOT EXISTS users (
  id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  clerk_id               VARCHAR(255) UNIQUE NOT NULL,
  email                  VARCHAR(255) UNIQUE NOT NULL,
  plan                   VARCHAR(50)  NOT NULL DEFAULT 'free',
  stripe_customer_id     VARCHAR(255) UNIQUE,
  stripe_subscription_id VARCHAR(255) UNIQUE,
  created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- API keys
CREATE TABLE IF NOT EXISTS api_keys (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key_hash     VARCHAR(255) UNIQUE NOT NULL,
  key_prefix   VARCHAR(12)  NOT NULL,
  name         VARCHAR(100),
  last_used_at TIMESTAMPTZ,
  expires_at   TIMESTAMPTZ,
  revoked      BOOLEAN      NOT NULL DEFAULT FALSE,
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Per-request usage log
CREATE TABLE IF NOT EXISTS usage_logs (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  api_key_id  UUID        REFERENCES api_keys(id) ON DELETE SET NULL,
  endpoint    VARCHAR(100) NOT NULL,
  ticker      VARCHAR(20),
  response_ms INTEGER,
  status_code SMALLINT    NOT NULL,
  error_msg   TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user_id      ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash     ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id    ON usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at DESC);
