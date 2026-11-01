-- 架空のサービス群の障害履歴（サンプルデータ）
-- 何度実行しても重複しないよう ON CONFLICT で無視する

INSERT INTO public.incidents (id, occurred_at, service, severity, title, root_cause, resolution_minutes, runbook) VALUES
  (1,  '2026-04-03 10:12+09', 'order-api',    'SEV2', '注文APIの5xxエラー率が上昇',               'デプロイ直後の設定ミス（タイムアウト値）',         35,  'api-5xx-spike.md'),
  (2,  '2026-04-18 21:40+09', 'auth-service', 'SEV1', 'ログイン不可',                             'TLS証明書の期限切れ',                             95,  'certificate-expiry.md'),
  (3,  '2026-05-02 09:05+09', 'order-api',    'SEV1', '注文確定が全件失敗',                       'DB接続数の上限到達',                              70,  'db-connection-exhaustion.md'),
  (4,  '2026-05-15 03:30+09', 'batch-worker', 'SEV3', '夜間バッチの遅延',                         'Lambdaの同時実行数上限によるスロットリング',      50,  'lambda-throttling.md'),
  (5,  '2026-05-29 14:22+09', 'web-frontend', 'SEV3', '一部画面の表示遅延',                       'CDNキャッシュの設定漏れ',                         40,  NULL),
  (6,  '2026-06-08 11:47+09', 'order-api',    'SEV2', '注文APIのレイテンシ悪化と5xx',             '外部決済APIの応答遅延',                           60,  'api-5xx-spike.md'),
  (7,  '2026-06-21 02:10+09', 'batch-worker', 'SEV2', '月次集計バッチが未完了',                   'Lambdaのスロットリングとリトライの積み上がり',    120, 'lambda-throttling.md'),
  (8,  '2026-07-04 18:33+09', 'auth-service', 'SEV2', 'トークン発行の失敗が断続的に発生',         'DB接続プールの枯渇',                              45,  'db-connection-exhaustion.md'),
  (9,  '2026-07-19 08:55+09', 'order-api',    'SEV3', '在庫照会APIの5xxが散発',                   '新バージョンのメモリ不足',                        25,  'api-5xx-spike.md'),
  (10, '2026-08-02 13:15+09', 'web-frontend', 'SEV2', 'トップページで証明書エラー',               'CDNに紐づく証明書の更新漏れ',                     55,  'certificate-expiry.md'),
  (11, '2026-08-16 04:02+09', 'batch-worker', 'SEV3', 'CSV取り込みバッチの遅延',                  'Lambdaの予約同時実行数の設定不足',                30,  'lambda-throttling.md'),
  (12, '2026-08-30 20:48+09', 'order-api',    'SEV1', 'セール開始直後に注文不可',                 'DB接続数の上限到達（スパイク時の接続急増）',      85,  'db-connection-exhaustion.md'),
  (13, '2026-09-11 10:30+09', 'auth-service', 'SEV3', 'パスワード再設定メールの遅延',             'メール送信キューの滞留',                          20,  NULL),
  (14, '2026-09-27 16:05+09', 'order-api',    'SEV2', '注文APIの5xxエラー率が上昇',               'ロールバック手順の未実施による長期化',            90,  'api-5xx-spike.md'),
  (15, '2026-10-09 01:20+09', 'batch-worker', 'SEV2', '日次バッチの失敗',                         'Lambdaのスロットリング',                          65,  'lambda-throttling.md'),
  (16, '2026-10-24 12:00+09', 'web-frontend', 'SEV3', '画像の表示崩れ',                           'ビルド成果物の配置ミス',                          15,  NULL)
ON CONFLICT (id) DO NOTHING;
