-- 010_model_evolution.sql
--
-- The self-evolving model loop: evaluate → propose → human-approve → promote.
--   * model_evaluations — measured performance of a (asset_class, model_type,
--     model_version) against labeled signals (and optional backtest).
--   * model_promotions  — a proposed champion change, pending human approval.
--   * model_champions   — the active model version per (asset_class, model_type);
--     the worker resolves this each tick. DB-backed (not a file) so the Fly
--     worker and the local options worker share one source of truth.

-- ---------------------------------------------------------------------------
-- model_evaluations
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS model_evaluations (
  id                   UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
  asset_class          VARCHAR(16)  NOT NULL,
  model_type           VARCHAR(32)  NOT NULL,
  model_version        VARCHAR(40)  NOT NULL,
  eval_date            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  n_samples            INTEGER      NOT NULL DEFAULT 0,
  directional_accuracy NUMERIC(6,4),
  signal_accuracy      NUMERIC(6,4),
  mean_abs_error       NUMERIC(12,6),
  backtest_sharpe      NUMERIC(10,4),
  backtest_win_rate    NUMERIC(6,4),
  metrics              JSONB,
  notes                TEXT
);

CREATE INDEX IF NOT EXISTS idx_model_evaluations_lookup
  ON model_evaluations(asset_class, model_type, model_version, eval_date DESC);

-- ---------------------------------------------------------------------------
-- model_promotions — proposed champion changes (human-approval gate)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS model_promotions (
  id            UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
  asset_class   VARCHAR(16)  NOT NULL,
  model_type    VARCHAR(32)  NOT NULL,
  from_version  VARCHAR(40),
  to_version    VARCHAR(40)  NOT NULL,
  status        VARCHAR(10)  NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
  proposed_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  decided_at    TIMESTAMPTZ,
  decided_by    VARCHAR(64),
  rationale     JSONB
);

CREATE INDEX IF NOT EXISTS idx_model_promotions_pending
  ON model_promotions(asset_class, model_type, proposed_at DESC)
  WHERE status = 'pending';

-- ---------------------------------------------------------------------------
-- model_champions — the active model per (asset_class, model_type)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS model_champions (
  asset_class  VARCHAR(16)  NOT NULL,
  model_type   VARCHAR(32)  NOT NULL,
  version      VARCHAR(40)  NOT NULL,
  updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (asset_class, model_type)
);
