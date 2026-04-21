-- 003_billing_events.sql

-- Stripe event log (idempotency — avoid double-processing webhooks)
CREATE TABLE IF NOT EXISTS stripe_events (
  stripe_event_id VARCHAR(255) PRIMARY KEY,
  event_type      VARCHAR(100) NOT NULL,
  processed       BOOLEAN      NOT NULL DEFAULT FALSE,
  processed_at    TIMESTAMPTZ,
  raw_payload     JSONB,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Billing period summary (pre-aggregated for dashboard display)
CREATE TABLE IF NOT EXISTS billing_summaries (
  id           BIGSERIAL PRIMARY KEY,
  user_id      UUID    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  period_start DATE    NOT NULL,
  period_end   DATE    NOT NULL,
  api_calls    INTEGER NOT NULL DEFAULT 0,
  signals_count INTEGER NOT NULL DEFAULT 0,
  amount_cents INTEGER NOT NULL DEFAULT 0,
  invoice_id   VARCHAR(255),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, period_start)
);

CREATE INDEX IF NOT EXISTS idx_billing_summaries_user
  ON billing_summaries(user_id, period_start DESC);
