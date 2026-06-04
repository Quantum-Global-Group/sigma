-- 012_pgvector_embeddings.sql
--
-- pgvector foundation for DGX research: store fixed-dim embeddings of labeled
-- signal_history rows for similarity search. Embeddings are built offline by
-- apps/api/scripts/embed_signals.py (simple numeric vector — no GPU model required).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS signal_embeddings (
  id                 UUID         NOT NULL DEFAULT uuid_generate_v4(),
  signal_history_id  BIGINT,
  asset_class        VARCHAR(16)  NOT NULL,
  symbol             VARCHAR(32)  NOT NULL,
  ts                 TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  features           JSONB,
  component_signals  JSONB,
  outcome            VARCHAR(8),
  embedding          vector(64)   NOT NULL,
  PRIMARY KEY (id, ts)
);

SELECT create_hypertable('signal_embeddings', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_signal_embeddings_asset_ts
  ON signal_embeddings(asset_class, ts DESC);

CREATE INDEX IF NOT EXISTS idx_signal_embeddings_history
  ON signal_embeddings(signal_history_id)
  WHERE signal_history_id IS NOT NULL;

-- IVFFlat index for cosine similarity (requires ANALYZE after bulk load).
CREATE INDEX IF NOT EXISTS idx_signal_embeddings_cosine
  ON signal_embeddings USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 32);
