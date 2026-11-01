"""スクリプト共通の処理（Terraform の出力の読み込み、Data API 呼び出し、SQL ファイルの分割）。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent

# Aurora が一時停止中・起動直後のときに返るエラー。少し待てば成功する
_RETRYABLE_CODES = {"DatabaseResumingException", "DatabaseUnavailableException"}
_RETRYABLE_HINTS = ("resum", "communications link failure", "httpendpoint", "is not available", "not enabled")


def tf_outputs() -> dict:
    """infra/ の terraform output を辞書で返す。"""
    try:
        raw = subprocess.run(
            ["terraform", f"-chdir={ROOT / 'infra'}", "output", "-json"],
            check=True, capture_output=True, text=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        sys.exit(f"terraform output を読めませんでした。先に infra/ で terraform apply してください。\n{e}")
    outputs = {k: v["value"] for k, v in json.loads(raw).items()}
    if not outputs:
        sys.exit("terraform output が空です。先に infra/ で terraform apply してください。")
    return outputs


def is_retryable(err: Exception) -> bool:
    if isinstance(err, ClientError):
        code = err.response.get("Error", {}).get("Code", "")
        msg = str(err).lower()
        if code in _RETRYABLE_CODES:
            return True
        if code == "BadRequestException" and any(h in msg for h in _RETRYABLE_HINTS):
            return True
    return False


def execute(client, *, cluster_arn: str, secret_arn: str, database: str, sql: str,
            transaction_id: str | None = None, max_wait_seconds: int = 300, **kwargs) -> dict:
    """Data API で 1 文実行する。Aurora が起動中なら最大 max_wait_seconds 待って再試行する。"""
    params = dict(resourceArn=cluster_arn, secretArn=secret_arn, database=database, sql=sql, **kwargs)
    if transaction_id:
        params["transactionId"] = transaction_id
    deadline = time.monotonic() + max_wait_seconds
    notified = False
    while True:
        try:
            return client.execute_statement(**params)
        except ClientError as e:
            if not is_retryable(e) or time.monotonic() > deadline:
                raise
            if not notified:
                # stdout は MCP サーバーの通信に使うので、メッセージは stderr に出す
                print("  Aurora を起動中です。待機しています...", file=sys.stderr, flush=True)
                notified = True
            time.sleep(10)


def split_sql(text: str) -> list[str]:
    """SQL ファイルを文ごとに分ける。行頭の「--」コメントは捨て、行末の「;」で区切る。"""
    statements, buf = [], []
    for line in text.splitlines():
        if line.strip().startswith("--") or not line.strip() and not buf:
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            statements.append("\n".join(buf).strip().rstrip(";"))
            buf = []
    if "".join(buf).strip():
        statements.append("\n".join(buf).strip())
    return statements


def session(region: str):
    return boto3.session.Session(region_name=region)
