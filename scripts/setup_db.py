"""Aurora の初期化。terraform apply の途中で自動実行される（手動で再実行しても安全）。

やること
  1. 用途別の DB ユーザー（bedrock_kb / agent_readonly）を作り、Secrets Manager のパスワードを設定
  2. sql/schema.sql   … pgvector 拡張、Knowledge Bases 用テーブルとインデックス、障害履歴テーブル、権限
  3. sql/sample_data.sql … サンプルの障害履歴

手動で実行する場合は、infra/ の terraform output から値を読み込む:
  python3 scripts/setup_db.py
"""

from __future__ import annotations

import json
import os
import re
import sys

from _common import ROOT, execute, session, split_sql, tf_outputs


def load_config() -> dict:
    if os.environ.get("OPS_CLUSTER_ARN"):
        return {
            "region": os.environ["OPS_REGION"],
            "cluster_arn": os.environ["OPS_CLUSTER_ARN"],
            "admin_secret_arn": os.environ["OPS_ADMIN_SECRET_ARN"],
            "kb_secret_arn": os.environ["OPS_KB_SECRET_ARN"],
            "agent_secret_arn": os.environ["OPS_AGENT_SECRET_ARN"],
            "db_name": os.environ["OPS_DB_NAME"],
            "embedding_dim": int(os.environ.get("OPS_EMBEDDING_DIM", "1024")),
        }
    out = tf_outputs()
    return {
        "region": out["region"],
        "cluster_arn": out["cluster_arn"],
        "admin_secret_arn": out["admin_secret_arn"],
        "kb_secret_arn": out["kb_secret_arn"],
        "agent_secret_arn": out["agent_secret_arn"],
        "db_name": out["db_name"],
        "embedding_dim": 1024,
    }


def read_credentials(sm, secret_arn: str) -> tuple[str, str]:
    secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])
    user, password = secret["username"], secret["password"]
    # ロール名・パスワードを SQL に直接埋め込むので、想定外の文字は拒否する
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", user) or not re.fullmatch(r"[A-Za-z0-9]+", password):
        sys.exit(f"シークレット {secret_arn} のユーザー名またはパスワードに想定外の文字があります")
    return user, password


def role_statements(user: str, password: str) -> list[str]:
    return [
        f"""DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{user}') THEN
    CREATE ROLE {user} LOGIN;
  END IF;
END
$$""",
        f"ALTER ROLE {user} WITH LOGIN PASSWORD '{password}'",
    ]


def main() -> None:
    cfg = load_config()
    s = session(cfg["region"])
    rds_data = s.client("rds-data")
    sm = s.client("secretsmanager")

    def run(sql: str, label: str) -> None:
        print(f"  - {label}", flush=True)
        execute(rds_data, cluster_arn=cfg["cluster_arn"], secret_arn=cfg["admin_secret_arn"],
                database=cfg["db_name"], sql=sql)

    print("[1/3] DB ユーザーを作成")
    for secret_arn in (cfg["kb_secret_arn"], cfg["agent_secret_arn"]):
        user, password = read_credentials(sm, secret_arn)
        for i, stmt in enumerate(role_statements(user, password)):
            run(stmt, f"{user} ({'作成' if i == 0 else 'パスワード設定'})")

    print("[2/3] スキーマと権限 (sql/schema.sql)")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    schema = schema.replace("{{EMBEDDING_DIM}}", str(cfg["embedding_dim"]))
    for stmt in split_sql(schema):
        run(stmt, stmt.splitlines()[0][:70])

    print("[3/3] サンプルデータ (sql/sample_data.sql)")
    for stmt in split_sql((ROOT / "sql" / "sample_data.sql").read_text(encoding="utf-8")):
        run(stmt, stmt.splitlines()[0][:70])

    print("DB の初期化が完了しました")


if __name__ == "__main__":
    main()
