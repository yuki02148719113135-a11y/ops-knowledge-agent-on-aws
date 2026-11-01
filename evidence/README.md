# 動作確認の証跡

2026-11-01 に us-east-1 へデプロイした環境から、**AWS API で取得した実データ**を画像にしたものです（コンソール画面のスクリーンショットではありません）。アカウント ID はマスクしています。

| ファイル | 内容 | データの取得元 |
|---|---|---|
| `02-ingest.png` | 取り込み結果（4 文書・失敗 0）と文書ごとのチャンク数。`drafts/` は含まれない | Bedrock `ListIngestionJobs` / Aurora |
| `03-kb-config.png` | Knowledge Base の構成（Titan V2・Aurora・フィールドマッピング） | Bedrock `GetKnowledgeBase` / RDS `DescribeDBClusters` |
| `04-ask-sql.png` | 障害履歴の質問 → `query_incidents` | CloudWatch Logs / DynamoDB |
| `05-ask-runbook.png` | 手順書の質問 → `search_runbooks` | CloudWatch Logs / DynamoDB |
| `06-ask-both.png` | 両方を組み合わせる質問 → ツール 2 つ | CloudWatch Logs / DynamoDB |
| `07-ask-memory.png` | 「それ」で前の会話を参照 | DynamoDB |
| `07b-ask-drafts-excluded.png` | 下書きの目印の言葉が回答に出ない | DynamoDB |
| `08-dynamodb.png` | 会話履歴の項目（10 件） | DynamoDB `Scan` |
| `09-db-indexes-grants.png` | HNSW / GIN インデックスとユーザーごとの権限 | Aurora（管理者） |
| `10-readonly-denied.png` | 読み取り専用ユーザーで `permission denied` | Aurora（agent_readonly） |
| `11-cloudwatch-logs.png` | エージェントのツール呼び出しログ | CloudWatch Logs |
| `12-explain.png` | `<=>` は Index Scan、`<->` は Seq Scan | Aurora（EXPLAIN） |
