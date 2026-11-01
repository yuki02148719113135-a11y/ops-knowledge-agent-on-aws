# 設計メモ（なぜこの構成にしたか）

## 1. Aurora への接続はすべて RDS Data API
Lambda・Bedrock Knowledge Bases・ローカルのスクリプト／MCP サーバーは、どれも Data API（HTTPS）で Aurora にアクセスします。

- Lambda を VPC に入れなくてよい → **NAT Gateway が不要**（検証環境の固定費をゼロにできる）
- Aurora のセキュリティグループは**受信ルールなし**（ポート 5432 をどこにも開けない）
- 認証は Secrets Manager のシークレット ARN と IAM で行う（接続文字列やパスワードをコードに持たない）

Bedrock Knowledge Bases で Aurora をベクトルストアにする場合、Data API の有効化は必須です。

## 2. 用途ごとに DB ユーザーとシークレットを分ける（最小権限）
| ユーザー | 使う人 | できること |
|---|---|---|
| `postgres_admin` | 構築スクリプト・調査 | すべて（パスワードは RDS が Secrets Manager で管理） |
| `bedrock_kb` | Bedrock Knowledge Bases | `bedrock_integration.document_chunks` の読み書きだけ |
| `agent_readonly` | エージェント Lambda・MCP サーバー | `incidents` と `incident_summary` の SELECT だけ |

- エージェントは KB の生データ（チャンク）を SQL で直接読めない。文書は必ず Knowledge Bases 経由で検索させる
- MCP サーバーもエージェントと**同じユーザー**で接続する。管理者で調べると、エージェントで起きる権限エラーが再現できないため
- エージェントの SQL は Lambda 側でも SELECT 1 文だけに制限しているが、本当の防御線は DB の権限

## 3. 集計ビューでエージェントに全件を読ませない
「サービスごとの障害件数」のような質問は、`incident_summary`（1 サービス 1 行）で答えられます。
ツールの説明にビューを書いておくことで、モデルが毎回 `incidents` を全件取得して数えるのを避けます（応答速度とトークン量の両方に効く）。

## 4. ベクトル検索のインデックス
| インデックス | 列 | 目的 |
|---|---|---|
| HNSW（`vector_cosine_ops`） | `embedding` | 意味が近いチャンクを近似最近傍で探す |
| GIN（`to_tsvector('simple', chunks)`） | `chunks` | キーワード検索（Knowledge Bases のハイブリッド検索） |

- Titan Text Embeddings V2 は正規化したベクトルをコサイン類似度で比べるので、演算子クラスは `vector_cosine_ops`
- pgvector は**演算子クラスと距離演算子が一致しないとインデックスを使わない**（`vector_cosine_ops` なら `<=>`）。`scripts/explain_vector_search.py` で実際に確かめられる
- 全文検索の辞書は `simple`。日本語は単語が空白で区切られないため、キーワード検索の精度は限定的（意味検索が主、キーワードは補助という位置づけ）
- エージェントはハイブリッド検索を指定し、使えない構成なら通常の検索に自動で切り替える

## 5. 取り込む文書を絞る
S3 には `runbooks/`（レビュー済みの手順書）と `drafts/`（下書き）の両方がありますが、データソースは `inclusion_prefixes = ["runbooks/"]` で手順書だけに絞っています。
「バケットにある＝エージェントに見せてよい」ではない、という前提で設計しています。下書きには目印の言葉を入れてあり、回答に出てこないことで確認できます。

## 6. 会話履歴（DynamoDB）
| 項目 | 値 | 理由 |
|---|---|---|
| パーティションキー | `session_id`（S） | 会話ごとにまとめて取得する |
| ソートキー | `created_at`（N、ミリ秒） | 新しい順に直近 N 往復だけ取る（`ScanIndexForward=false` + `Limit`） |
| TTL | `expires_at` | 7 日で自動削除（古い会話を溜めない） |
| 課金 | オンデマンド | 検証用でアクセスが少ない |

- 質問と回答は `BatchWriteItem` で**ペアで**保存する。片方だけ残ると、Converse API の「user と assistant が交互」の条件が崩れるため
- 念のため、読み込んだ履歴が assistant から始まっていたら先頭を捨てる

## 7. エージェントの実装
- LangChain などのフレームワークは使わず、Bedrock **Converse API のツール呼び出し**だけで実装（依存ライブラリなし、Lambda にそのまま載る）
- ツール呼び出しは最大 5 往復で打ち切る（無限ループ防止）
- ツールのエラーは例外で落とさず、エラー内容をモデルに返して判断させる

## 8. コスト
| リソース | 対策 |
|---|---|
| Aurora Serverless v2 | 最小 0 ACU。10 分アイドルで自動一時停止 |
| NAT Gateway | 使わない（Data API） |
| Lambda / DynamoDB / Bedrock | 従量課金のみ |
| CloudWatch Logs | 保持期間 7 日 |

一時停止からの復帰には数十秒かかるため、スクリプトとエージェントは `DatabaseResumingException` を待って再試行します。

## 9. 本番にするなら（今回はやっていないこと）
- エージェントの前に API Gateway + Cognito（認証）を置く
- Aurora を専用 VPC のプライベートサブネットに置き、最小 ACU を 0.5 以上にする（一時停止の待ちをなくす）
- Bedrock Guardrails で入出力をフィルタする
- DB ユーザーのパスワードを Secrets Manager のローテーションで定期変更する
- Terraform の state を S3 バックエンドに置く
