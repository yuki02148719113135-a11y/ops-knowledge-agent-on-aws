# トラブルシュート

## 実際にハマったこと
<!-- 構築・確認の途中で自分が詰まったことを書く。何も無ければこの節は削除してよい -->

| # | 症状 | 原因 | 対処 |
|---|---|---|---|
| 1 |  |  |  |

---

## 起きやすいエラーと対処（事前に想定しているもの）

| 症状 | 考えられる原因 | 対処 |
|---|---|---|
| `terraform plan` で `no matching EC2 VPC found` | デフォルト VPC が無い | `aws ec2 create-default-vpc --region us-east-1` |
| `terraform apply` で `Cannot find version 16.6 for aurora-postgresql` | そのマイナーバージョンが提供終了している | `aws rds describe-db-engine-versions --engine aurora-postgresql --region us-east-1 --query "DBEngineVersions[?starts_with(EngineVersion,'16')].EngineVersion"` で使える版を調べ、`terraform.tfvars` に `aurora_engine_version = "16.x"` を書く |
| apply 中に `setup_db.py` が `ModuleNotFoundError: boto3` | 仮想環境を有効化していない | `source .venv/bin/activate` してから `terraform apply` をやり直す |
| apply 中に `setup_db.py` が `Aurora を起動中です` のまま進まない | 作成直後で Data API の準備中 | 5 分待っても進まなければ Ctrl+C → `terraform apply` を再実行（スクリプトは何度実行しても安全） |
| Knowledge Base 作成で `not authorized to perform: secretsmanager:GetSecretValue` / ロールを引き受けられない | IAM ロールの反映待ち | 1〜2 分待って `terraform apply` を再実行 |
| Knowledge Base 作成で「テーブルが見つからない」系のエラー | DB 初期化が失敗している | `python3 scripts/setup_db.py` を手動実行してエラーを確認 |
| `ingest.py` が `FAILED` | Aurora の復帰待ち / 権限 | 失敗理由を確認し、もう一度 `python3 scripts/ingest.py` |
| `ask.py` で `AccessDeniedException ... InvokeModel` | Nova Pro が使えない | 0-2 の手順でモデルアクセスを確認 |
| `ask.py` で `ValidationException ... on-demand throughput isn't supported` | モデル ID に推論プロファイルの接頭辞（`us.`）が無い | `chat_model_id` を `us.amazon.nova-pro-v1:0` にする |
| 回答が「確認できなかった」ばかり | 取り込み前 / 取り込み失敗 | `python3 scripts/ingest.py` の結果でチャンク数を確認 |
| `terraform destroy` で Knowledge Base の削除が失敗 | 削除中に Aurora が一時停止から復帰中 | 少し待って `terraform destroy` を再実行 |

## 調べ方のコツ
- エージェントの動きは CloudWatch Logs の `tool=... input=...` の行で追える
- DB の権限まわりは、クエリエディタで**エージェントと同じシークレット**に切り替えて同じ SQL を流すと再現できる
- Terraform の途中で失敗しても、多くは `terraform apply` の再実行で続きから進む
