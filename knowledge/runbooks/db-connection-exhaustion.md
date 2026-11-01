# 手順書: DB の接続数が枯渇したとき

対象サービス: order-api, auth-service（Aurora PostgreSQL を使うサービス）
重要度の目安: 書き込みが全件失敗していれば SEV1

## 症状
- アプリのログに `too many connections` や `remaining connection slots are reserved` が出る
- 接続プールの取得待ちでタイムアウトする
- セール開始直後など、アクセスが急増したタイミングで起きやすい

## 確認すること
1. DB の接続数メトリクス（DatabaseConnections）が上限付近に張り付いていないか
2. どのアプリから接続が多いかを確認する
   ```sql
   SELECT usename, application_name, state, COUNT(*)
   FROM pg_stat_activity
   GROUP BY 1, 2, 3
   ORDER BY 4 DESC;
   ```
3. `idle in transaction` の接続が溜まっていないか（トランザクションの閉じ忘れ）

## 対処
1. 一時対応: 長時間 `idle in transaction` の接続を切断する
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle in transaction'
     AND state_change < now() - interval '5 minutes';
   ```
2. アプリのインスタンス数を急に増やしている場合は、増やしすぎを戻す（台数 × プールサイズが接続数になる）
3. 恒久対応として RDS Proxy の導入を検討する

## 再発防止
- 「インスタンス数 × 接続プールの最大数」が DB の上限を超えない設計にする
- セールなどアクセス急増が予想される日は事前に容量を確認する
