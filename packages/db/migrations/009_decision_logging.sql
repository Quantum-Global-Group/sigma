-- 009_decision_logging.sql
--
-- Persistent decision logging — the data foundation for the self-evolving loop.
--   * signal_history: realized_return / outcome / labeled_at — backfilled by the
--     outcome-labeling job (apps/api/ml/labeling.py) which compares each past
--     prediction to the actual forward move from the candles table.
--   * audit_records: durable copy of the per-tick options decision audit log
--     (previously in-memory only in apps/api/risk/audit_log.py).

-- ---------------------------------------------------------------------------
-- signal_history: outcome labels (nullable — filled later by the labeler)
-- ---------------------------------------------------------------------------

ALTER TABLE signal_history
  ADD COLUMN IF NOT EXISTS realized_return NUMERIC(12,6),
  ADD COLUMN IF NOT EXISTS outcome         VARCHAR(8),    -- win | loss | flat
  ADD COLUMN IF NOT EXISTS labeled_at      TIMESTAMPTZ;

-- Find unlabeled rows efficiently (the labeler scans WHERE labeled_at IS NULL).
CREATE INDEX IF NOT EXISTS idx_signal_history_unlabeled
  ON signal_history(asset_class, created_at)
  WHERE labeled_at IS NULL;

-- ---------------------------------------------------------------------------
-- audit_records — full decision provenance per trade evaluation
-- ---------------------------------------------------------------------------
-- Mirrors apps/api/risk/audit_log.py::AuditRecord. `order_info` (not `order`,
-- which is reserved). Hypertable on ts so old rows compress automatically.

CREATE TABLE IF NOT EXISTS audit_records (
  id           UUID         NOT NULL DEFAULT uuid_generate_v4(),
  ts           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  asset_class  VARCHAR(16)  NOT NULL DEFAULT 'option',
  symbol       VARCHAR(32)  NOT NULL,
  strategy     VARCHAR(40),
  decision     VARCHAR(16)  NOT NULL DEFAULT 'pending',  -- placed|submitted|skipped|rejected
  data         JSONB,
  features     JSONB,
  signal       JSONB,
  risk         JSONB,
  gates        JSONB,
  order_info   JSONB,
  notes        TEXT,
  PRIMARY KEY (id, ts)
);

SELECT create_hypertable('audit_records', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_audit_records_symbol_ts
  ON audit_records(asset_class, symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_records_decision
  ON audit_records(decision, ts DESC);
