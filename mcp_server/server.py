"""Aurora を調べるためのローカル MCP サーバー（stdio）。

Claude Code / Claude Desktop などの AI ツールから、エージェントと「同じ読み取り専用ユーザー」で
DB を調べられるようにする。管理者権限で調べると、エージェント側で起きる権限エラーが再現できないため。

ツール
  list_tables    : 見えるテーブル・ビューの一覧
  describe_table : 列の一覧
  query          : SELECT 文の実行（1 文のみ、最大 100 行）
  explain_query  : 実行計画（EXPLAIN）の表示

必要な環境変数: OPS_REGION, OPS_CLUSTER_ARN, OPS_SECRET_ARN, OPS_DB_NAME
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import boto3
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _common import execute  # noqa: E402

REGION = os.environ.get("OPS_REGION", "us-east-1")
CLUSTER_ARN = os.environ.get("OPS_CLUSTER_ARN", "")
SECRET_ARN = os.environ.get("OPS_SECRET_ARN", "")
DB_NAME = os.environ.get("OPS_DB_NAME", "opsdb")
MAX_ROWS = 100

mcp = FastMCP("ops-aurora")
_rds = boto3.client("rds-data", region_name=REGION)
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _run(sql: str, parameters: list | None = None) -> list[dict]:
    kwargs = {"formatRecordsAs": "JSON"}
    if parameters:
        kwargs["parameters"] = parameters
    resp = execute(_rds, cluster_arn=CLUSTER_ARN, secret_arn=SECRET_ARN, database=DB_NAME,
                   sql=sql, max_wait_seconds=120, **kwargs)
    return json.loads(resp.get("formattedRecords") or "[]")


def _check_read_only(sql: str) -> str:
    body = sql.strip().rstrip(";").strip()
    if not _READ_ONLY.match(body) or ";" in body:
        raise ValueError("SELECT / WITH で始まる 1 文だけ実行できます")
    return body


@mcp.tool()
def list_tables() -> list[dict]:
    """このユーザーが参照できるテーブルとビューの一覧を返す。"""
    return _run(
        "SELECT table_schema, table_name, table_type FROM information_schema.tables "
        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
        "AND has_table_privilege(quote_ident(table_schema) || '.' || quote_ident(table_name), 'SELECT') "
        "ORDER BY 1, 2"
    )


@mcp.tool()
def describe_table(table_name: str) -> list[dict]:
    """public スキーマのテーブル／ビューの列（名前・型・NULL 可否）を返す。"""
    return _run(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position",
        [{"name": "t", "value": {"stringValue": table_name}}],
    )


@mcp.tool()
def query(sql: str) -> dict:
    """読み取り専用の SELECT 文を 1 つ実行して結果を返す（最大 100 行）。"""
    rows = _run(_check_read_only(sql))
    return {"row_count": len(rows), "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


@mcp.tool()
def explain_query(sql: str) -> str:
    """SELECT 文の実行計画（EXPLAIN）を返す。インデックスが使われているかの確認に使う。"""
    body = _check_read_only(sql)
    resp = execute(_rds, cluster_arn=CLUSTER_ARN, secret_arn=SECRET_ARN, database=DB_NAME,
                   sql=f"EXPLAIN {body}", max_wait_seconds=120)
    return "\n".join(r[0]["stringValue"] for r in resp["records"])


if __name__ == "__main__":
    missing = [k for k in ("OPS_CLUSTER_ARN", "OPS_SECRET_ARN") if not os.environ.get(k)]
    if missing:
        sys.exit(f"環境変数が足りません: {', '.join(missing)}")
    mcp.run()
