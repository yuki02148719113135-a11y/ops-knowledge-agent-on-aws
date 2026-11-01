-- RDS クエリエディタで確認するときのクエリ集
-- 接続: データベース認証情報 = Secrets Manager の ARN / データベース名 = opsdb

-- ===== 管理者シークレット（admin_secret_arn）で接続して実行 =====

-- 取り込まれたチャンク数（ingest 後に 0 より大きくなる）
SELECT COUNT(*) FROM bedrock_integration.document_chunks;

-- どの文書から何チャンク作られたか（drafts/ が含まれていないこと）
SELECT metadata->>'sourceUrl' AS source, COUNT(*)
FROM bedrock_integration.document_chunks
GROUP BY 1 ORDER BY 1;

-- インデックスの確認（HNSW と GIN）
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'bedrock_integration';

-- ロールごとの権限
SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee IN ('bedrock_kb', 'agent_readonly')
ORDER BY grantee, table_schema, table_name;

-- ===== 読み取り専用シークレット（agent_secret_arn）で接続して実行 =====

-- 読める
SELECT * FROM incident_summary ORDER BY incident_count DESC;

-- 読めない（permission denied になれば最小権限が効いている）
SELECT COUNT(*) FROM bedrock_integration.document_chunks;

-- 書けない（permission denied）
DELETE FROM incidents WHERE id = 1;
