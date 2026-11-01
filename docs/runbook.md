# 手順書：構築 → 動作確認 → 削除

所要時間の目安は **1〜2 時間**です（うち 15〜20 分は Aurora の作成待ち）。
各ステップの最後にある「📸」は、`evidence/` に保存するスクリーンショットです。

---

## 0. 事前準備（初回だけ）

### 0-1. 必要なもの
| ツール | 確認コマンド | 備考 |
|---|---|---|
| AWS CLI v2 | `aws sts get-caller-identity` | 自分のアカウント ID が出れば OK |
| Terraform 1.6 以上 | `terraform version` | Mac なら `brew install terraform` |
| Python 3.11 以上 | `python3 --version` | |
| Git | `git --version` | |

AWS の認証情報は、管理者相当の権限がある IAM ユーザー（または IAM Identity Center のプロファイル）を想定しています。
プロファイルを使う場合は、以降のコマンドを打つターミナルで `export AWS_PROFILE=プロファイル名` しておきます。

### 0-2. Bedrock のモデルを確認
コンソール → Amazon Bedrock（**リージョン：バージニア北部 us-east-1**）→ 左メニューの「モデルアクセス」で、次の 2 つが使える状態か確認します。使えない場合は有効化します。

- Amazon **Nova Pro**（エージェントの会話モデル）
- Amazon **Titan Text Embeddings V2**（文書の埋め込み）

### 0-3. デフォルト VPC があるか確認
```bash
aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[].VpcId' --region us-east-1
```
空（`[]`）なら作成します：`aws ec2 create-default-vpc --region us-east-1`

### 0-4. リポジトリの準備
zip を展開したフォルダに移動します。
```bash
cd ops-knowledge-agent-on-aws

python3 -m venv .venv
source .venv/bin/activate          # 以降、新しいターミナルを開いたら毎回これを実行
pip install -r requirements.txt

# AWS を使わないテスト（数秒で終わる）
python3 -m unittest discover -s tests
```
`OK` と出れば準備完了です。

---

## 1. デプロイ（約 20 分）

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan        # 作成されるリソースを確認（40 個前後）
terraform apply       # yes と入力
```

apply の途中で `scripts/setup_db.py` が自動で動き、次のログが出ます。

```
[1/3] DB ユーザーを作成
[2/3] スキーマと権限 (sql/schema.sql)
[3/3] サンプルデータ (sql/sample_data.sql)
DB の初期化が完了しました
```

完了したら出力を確認します。
```bash
terraform output
cd ..
```

📸 `01-terraform-apply.png`：`Apply complete!` と output が見える画面

---

## 2. 手順書を Knowledge Base に取り込む（約 3 分）

```bash
python3 scripts/ingest.py
```

期待する結果：
- `numberOfDocumentsScanned: 4`（runbooks/ の 4 ファイルだけ。drafts/ は数えられない）
- `status = COMPLETE`
- 取り込み後のチャンク数が 0 より大きい

📸 `02-ingest.png`：上の実行結果
📸 `03-kb-console.png`：Bedrock コンソール → ナレッジベース → 作成した KB → ベクトルストアが Aurora、データソースが同期済みの画面

---

## 3. エージェントに質問する

### 3-1. 障害履歴（SQL）を使う質問
```bash
python3 scripts/ask.py "障害が一番多いサービスはどれ？平均の復旧時間も教えて"
```
期待：`🔧 query_incidents` が呼ばれ、**order-api（6 件）** と答える

### 3-2. 手順書（Knowledge Base）を使う質問
```bash
python3 scripts/ask.py "DB の接続数が上限に達したら、まず何を確認すればいい？"
```
期待：`🔧 search_runbooks` が呼ばれ、`pg_stat_activity` の確認などを `db-connection-exhaustion.md` を根拠に答える

### 3-3. 両方を組み合わせる質問
```bash
python3 scripts/ask.py --session demo2 "batch-worker で多い障害の原因と、その対処手順をまとめて"
```
期待：`query_incidents` と `search_runbooks` の両方が呼ばれ、スロットリングと `lambda-throttling.md` の対処を答える

### 3-4. 会話の記憶（DynamoDB）
```bash
python3 scripts/ask.py --session demo2 "それの再発防止策だけ、もう一度箇条書きで"
```
期待：「それ」が前の質問（batch-worker のスロットリング）を指していると理解して答える

### 3-5. 下書きが取り込まれていないこと
```bash
python3 scripts/ask.py "ペンギン作戦について教えて"
```
期待：「確認できなかった」と答える（`drafts/` を取り込んでいない証拠）

📸 `04-ask-sql.png` / `05-ask-runbook.png` / `06-ask-both.png` / `07-ask-memory.png`

> 💡 Aurora が一時停止していると、最初の 1 回は 30 秒ほど待つことがあります（自動で再試行します）。

---

## 4. 中身を確認する（コンソール）

### 4-1. DynamoDB（会話履歴）
DynamoDB → テーブル → `ops-agent-xxxxxx-conversations` → 項目を探索
`session_id = demo2` で、user と assistant の項目が交互に入っていること

📸 `08-dynamodb.png`

### 4-2. Aurora（RDS クエリエディタ）
RDS → クエリエディタ →
- データベースインスタンス：`ops-agent-xxxxxx`
- データベースユーザー名：「Secrets Manager ARN を使用して接続する」→ `terraform output -raw admin_secret_arn` の値
- データベース名：`opsdb`

`sql/explore.sql` の上半分を実行します。
- チャンク数、文書ごとのチャンク数（`drafts/` が無いこと）
- `bedrock_integration` に HNSW と GIN のインデックスがあること

次に、接続先を **`terraform output -raw agent_secret_arn`（読み取り専用）** に切り替えて、下半分を実行します。
- `incident_summary` は読める
- `document_chunks` は `permission denied for schema bedrock_integration`
- `DELETE` は `permission denied for table incidents`

📸 `09-query-editor-admin.png` / `10-query-editor-readonly-denied.png`

### 4-3. CloudWatch Logs（エージェントの動き）
CloudWatch → ロググループ → `/aws/lambda/ops-agent-xxxxxx-agent`
`tool=query_incidents input=...` のように、どのツールをどんな入力で呼んだかが残っていること

📸 `11-cloudwatch-logs.png`

---

## 5. ベクトル検索の実行計画を比べる

```bash
python3 scripts/explain_vector_search.py "DB の接続数が足りない"
```

期待：
- A（`<=>` コサイン距離）→ `Index Scan using document_chunks_embedding_hnsw`
- B（`<->` L2 距離）→ `Seq Scan`

インデックスを `vector_cosine_ops` で作っているので、`<=>` でないとインデックスが使われないことが確認できます。

📸 `12-explain.png`

---

## 6. MCP サーバーで AI ツールから DB を調べる（任意）

```bash
python3 scripts/mcp_config.py
```
表示された `claude mcp add ...` をそのまま実行すると、Claude Code に登録されます（Claude Desktop の場合は表示された JSON を設定ファイルに追記）。

登録後、Claude Code で次のように頼みます。
- 「ops-aurora の list_tables で見えるテーブルを教えて」→ `incidents` と `incident_summary` だけ見える
- 「incidents から order-api の SEV1 を取って、その実行計画も見せて」→ `query` と `explain_query` が使われる

MCP サーバーはエージェントと**同じ読み取り専用ユーザー**で接続しているので、`document_chunks` は見えません。

📸 `13-mcp.png`

---

## 7. 削除（必ず実行）

```bash
cd infra
terraform destroy     # yes と入力（約 10 分）
cd ..
```

削除後の確認：
- RDS のデータベース一覧に `ops-agent-xxxxxx` が無い
- Bedrock のナレッジベース一覧に `ops-agent-xxxxxx-runbooks` が無い
- Secrets Manager に `ops-agent-xxxxxx/...` が無い（`rds!cluster-...` という RDS 管理のシークレットも、クラスター削除と一緒に消える）

📸 `14-destroy.png`：`Destroy complete!`

### 費用の目安
Aurora は最小 0 ACU（10 分アイドルで自動一時停止）なので、**当日中に削除すれば数十〜数百円程度**の想定です。
翌日以降に「請求」→「Cost Explorer」で実際の金額を確認してください。

---

## 8. GitHub に公開する

### 8-1. スクリーンショットを整理
`evidence/` に 📸 の画像を置きます。**アカウント ID（12 桁）や ARN はモザイク**をかけてください。

### 8-2. README の「検証結果」を記入
`README.md` の「検証結果」のチェックボックスを、実際に確認できたものだけ `[x]` にします。
`docs/troubleshooting.md` の「実際にハマったこと」に、自分で詰まった点を書きます（無ければ削除）。

### 8-3. コミットして公開
```bash
git init -b main

# コミットの作者を自分にする
git config user.name  "Yuki Fujiwara"
git config user.email "GitHub に登録しているメールアドレス"

git add .
git status            # *.tfstate や terraform.tfvars が含まれていないことを確認
git commit -m "Add ops knowledge agent on AWS (Aurora pgvector + Bedrock KB + DynamoDB + MCP)"

# GitHub CLI を使う場合
gh repo create ops-knowledge-agent-on-aws --public --source=. --push
```
GitHub CLI を使わない場合は、GitHub の画面で空のリポジトリを作り、表示される `git remote add origin ...` と `git push -u origin main` を実行します。

> ⚠️ `terraform.tfstate` には DB ユーザーのパスワードが入っています。`.gitignore` で除外していますが、`git status` で必ず確認してください。
