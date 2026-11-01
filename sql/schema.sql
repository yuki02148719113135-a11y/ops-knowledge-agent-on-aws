-- スキーマ定義（scripts/setup_db.py が管理者ユーザーで 1 文ずつ実行する）
-- ルール: 文の終わりは行末の「;」。行の途中にコメントを書かない。
-- {{EMBEDDING_DIM}} は実行時に埋め込みの次元数（既定 1024）に置き換わる。
-- ロール bedrock_kb / agent_readonly は、このファイルより前にスクリプトが作成済み。

CREATE EXTENSION IF NOT EXISTS vector;

-- =====================================================================
-- 1) Bedrock Knowledge Bases 用（bedrock_kb だけが触れるスキーマ）
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS bedrock_integration;

GRANT USAGE ON SCHEMA bedrock_integration TO bedrock_kb;

CREATE TABLE IF NOT EXISTS bedrock_integration.document_chunks (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  embedding vector({{EMBEDDING_DIM}}),
  chunks    text,
  metadata  json
);

GRANT SELECT, INSERT, UPDATE, DELETE ON bedrock_integration.document_chunks TO bedrock_kb;

-- 意味検索: Titan V2 の埋め込みはコサイン類似度で比べるので vector_cosine_ops（演算子は <=>）
CREATE INDEX IF NOT EXISTS document_chunks_embedding_hnsw
  ON bedrock_integration.document_chunks
  USING hnsw (embedding vector_cosine_ops);

-- キーワード検索（Knowledge Bases のハイブリッド検索で使われる）
CREATE INDEX IF NOT EXISTS document_chunks_chunks_gin
  ON bedrock_integration.document_chunks
  USING gin (to_tsvector('simple', chunks));

-- =====================================================================
-- 2) 業務データ（障害履歴）。エージェントは SELECT だけできる
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.incidents (
  id                 integer PRIMARY KEY,
  occurred_at        timestamptz NOT NULL,
  service            text NOT NULL,
  severity           text NOT NULL CHECK (severity IN ('SEV1', 'SEV2', 'SEV3')),
  title              text NOT NULL,
  root_cause         text,
  resolution_minutes integer,
  runbook            text
);

CREATE INDEX IF NOT EXISTS incidents_service_occurred_at_idx
  ON public.incidents (service, occurred_at DESC);

-- エージェントに全件を読ませず、サービス単位の集計だけで答えられるようにするビュー
CREATE OR REPLACE VIEW public.incident_summary AS
SELECT
  service,
  COUNT(*)                         AS incident_count,
  COUNT(*) FILTER (WHERE severity = 'SEV1') AS sev1_count,
  ROUND(AVG(resolution_minutes))   AS avg_resolution_minutes,
  MAX(occurred_at)                 AS last_occurred_at
FROM public.incidents
GROUP BY service;

-- =====================================================================
-- 3) 権限（最小権限）
-- =====================================================================
GRANT USAGE ON SCHEMA public TO agent_readonly;

GRANT SELECT ON public.incidents, public.incident_summary TO agent_readonly;

-- 念のため明示的に拒否（agent_readonly は KB の生データを読めない）
REVOKE ALL ON SCHEMA bedrock_integration FROM agent_readonly;
