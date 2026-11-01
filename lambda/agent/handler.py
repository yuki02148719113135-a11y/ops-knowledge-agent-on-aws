"""運用ナレッジエージェント（Lambda）

入力:  {"session_id": "任意の文字列", "message": "質問"}
出力:  {"session_id": ..., "answer": ..., "tool_calls": [{"name": ..., "input": ...}, ...]}

Bedrock Converse API のツール呼び出しで、次の 2 つを使い分けて答える。
  - search_runbooks : Knowledge Bases（Aurora pgvector）から手順書を検索
  - query_incidents : Aurora の障害履歴を読み取り専用ユーザーで SQL 検索
会話履歴は DynamoDB に保存し、同じ session_id なら前の会話を踏まえて答える。

依存ライブラリは Lambda ランタイム同梱の boto3 のみ。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-pro-v1:0")
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "")
CLUSTER_ARN = os.environ.get("CLUSTER_ARN", "")
DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN", "")
DB_NAME = os.environ.get("DB_NAME", "opsdb")
MEMORY_TABLE = os.environ.get("MEMORY_TABLE", "")
HISTORY_TURNS = int(os.environ.get("HISTORY_TURNS", "6"))
MEMORY_TTL_DAYS = int(os.environ.get("MEMORY_TTL_DAYS", "7"))
SEARCH_TYPE = os.environ.get("SEARCH_TYPE", "HYBRID")

MAX_TOOL_ROUNDS = 5
MAX_ROWS = 50

SYSTEM_PROMPT = """あなたは社内の運用チーム向けアシスタントです。
- 障害の対処手順・確認ポイントは search_runbooks で手順書を検索してから答えてください。
- 障害の件数・傾向・復旧時間などの事実は query_incidents で障害履歴を集計してから答えてください。
- 回答には根拠（参照した手順書のファイル名、または集計した数値）を添えてください。
- 手順書や履歴で確認できないことは推測で補わず、「確認できなかった」と伝えてください。
- 日本語で、簡潔に答えてください。"""

TOOLS = [
    {
        "toolSpec": {
            "name": "search_runbooks",
            "description": "社内の障害対応手順書（runbook）を意味検索する。対処方法・確認手順・再発防止策を調べるときに使う。",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "検索したい内容（例: DB の接続数が上限に達したときの対処）"}
                    },
                    "required": ["query"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "query_incidents",
            "description": (
                "障害履歴データベース（PostgreSQL）に読み取り専用の SELECT 文を 1 つ実行する。"
                "使えるのは次の 2 つだけ。\n"
                "incidents(id integer, occurred_at timestamptz, service text, "
                "severity text ['SEV1','SEV2','SEV3'], title text, root_cause text, "
                "resolution_minutes integer, runbook text)\n"
                "incident_summary(service text, incident_count bigint, sev1_count bigint, "
                "avg_resolution_minutes numeric, last_occurred_at timestamptz)\n"
                "service の値: order-api, auth-service, batch-worker, web-frontend"
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"sql": {"type": "string", "description": "実行する SELECT 文（1 文のみ）"}},
                    "required": ["sql"],
                }
            },
        }
    },
]

_clients: dict = {}


def client(name: str):
    if name not in _clients:
        _clients[name] = boto3.client(name)
    return _clients[name]


# ---------------------------------------------------------------------------
# リトライ（Aurora が自動一時停止から復帰する間のエラーを吸収）
# ---------------------------------------------------------------------------
def _is_resuming(err: Exception) -> bool:
    if not isinstance(err, ClientError):
        return False
    code = err.response.get("Error", {}).get("Code", "")
    return code in {"DatabaseResumingException", "DatabaseUnavailableException"} or "resum" in str(err).lower()


def with_resume_retry(fn, *, attempts: int = 8, wait: float = 5.0):
    for i in range(attempts):
        try:
            return fn()
        except ClientError as e:
            if not _is_resuming(e) or i == attempts - 1:
                raise
            logger.info("Aurora resuming, retry %s/%s", i + 1, attempts)
            time.sleep(wait)


# ---------------------------------------------------------------------------
# ツール
# ---------------------------------------------------------------------------
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def is_read_only_sql(sql: str) -> bool:
    """1 文だけの SELECT / WITH か。最終的な防御は DB ユーザーの権限（agent_readonly）。"""
    body = sql.strip().rstrip(";").strip()
    return bool(_READ_ONLY.match(body)) and ";" not in body


def search_runbooks(query: str) -> dict:
    def _retrieve(search_type: str | None):
        vector_cfg: dict = {"numberOfResults": 4}
        if search_type:
            vector_cfg["overrideSearchType"] = search_type
        return client("bedrock-agent-runtime").retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": vector_cfg},
        )

    try:
        resp = with_resume_retry(lambda: _retrieve(SEARCH_TYPE or None))
    except ClientError as e:
        # ハイブリッド検索が使えない構成なら、既定の検索でやり直す
        if SEARCH_TYPE and e.response.get("Error", {}).get("Code") == "ValidationException":
            logger.warning("search type %s rejected, falling back: %s", SEARCH_TYPE, e)
            resp = with_resume_retry(lambda: _retrieve(None))
        else:
            raise

    results = []
    for r in resp.get("retrievalResults", []):
        uri = r.get("location", {}).get("s3Location", {}).get("uri", "")
        results.append({
            "source": uri.rsplit("/", 1)[-1] if uri else "",
            "score": round(r.get("score", 0.0), 4),
            "text": r.get("content", {}).get("text", "")[:1500],
        })
    return {"results": results}


def query_incidents(sql: str) -> dict:
    if not is_read_only_sql(sql):
        return {"error": "SELECT 文（1 文のみ）だけ実行できます"}
    resp = with_resume_retry(lambda: client("rds-data").execute_statement(
        resourceArn=CLUSTER_ARN,
        secretArn=DB_SECRET_ARN,
        database=DB_NAME,
        sql=sql,
        formatRecordsAs="JSON",
    ))
    rows = json.loads(resp.get("formattedRecords") or "[]")
    return {"row_count": len(rows), "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


TOOL_IMPL = {
    "search_runbooks": lambda args: search_runbooks(str(args.get("query", ""))),
    "query_incidents": lambda args: query_incidents(str(args.get("sql", ""))),
}


def run_tool(name: str, args: dict) -> dict:
    impl = TOOL_IMPL.get(name)
    if impl is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return impl(args)
    except ClientError as e:
        logger.exception("tool %s failed", name)
        return {"error": e.response.get("Error", {}).get("Message", str(e))}


# ---------------------------------------------------------------------------
# 会話履歴（DynamoDB）
#   PK: session_id / SK: created_at（ミリ秒）/ TTL: expires_at
# ---------------------------------------------------------------------------
def load_history(session_id: str) -> list[dict]:
    if not MEMORY_TABLE:
        return []
    resp = client("dynamodb").query(
        TableName=MEMORY_TABLE,
        KeyConditionExpression="session_id = :s",
        ExpressionAttributeValues={":s": {"S": session_id}},
        ScanIndexForward=False,
        Limit=HISTORY_TURNS * 2,
    )
    items = list(reversed(resp.get("Items", [])))
    messages = [{"role": i["role"]["S"], "content": [{"text": i["text"]["S"]}]} for i in items]
    # Converse は user から始まり user / assistant が交互である必要がある
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def save_turn(session_id: str, user_text: str, answer: str) -> None:
    if not MEMORY_TABLE:
        return
    now_ms = int(time.time() * 1000)
    expires_at = int(time.time()) + MEMORY_TTL_DAYS * 86400

    def item(offset: int, role: str, text: str) -> dict:
        return {"PutRequest": {"Item": {
            "session_id": {"S": session_id},
            "created_at": {"N": str(now_ms + offset)},
            "role": {"S": role},
            "text": {"S": text},
            "expires_at": {"N": str(expires_at)},
        }}}

    client("dynamodb").batch_write_item(RequestItems={
        MEMORY_TABLE: [item(0, "user", user_text), item(1, "assistant", answer or "(回答なし)")]
    })


# ---------------------------------------------------------------------------
# エージェント本体
# ---------------------------------------------------------------------------
def run_agent(user_text: str, history: list[dict]) -> tuple[str, list[dict]]:
    messages = history + [{"role": "user", "content": [{"text": user_text}]}]
    tool_calls: list[dict] = []
    output: dict = {}

    for _ in range(MAX_TOOL_ROUNDS + 1):
        resp = client("bedrock-runtime").converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            toolConfig={"tools": TOOLS},
            inferenceConfig={"maxTokens": 1500, "temperature": 0.2},
        )
        output = resp["output"]["message"]
        messages.append(output)
        if resp.get("stopReason") != "tool_use":
            break

        results = []
        for block in output.get("content", []):
            use = block.get("toolUse")
            if not use:
                continue
            tool_calls.append({"name": use["name"], "input": use.get("input", {})})
            result = run_tool(use["name"], use.get("input", {}))
            logger.info("tool=%s input=%s result_keys=%s", use["name"], use.get("input"), list(result))
            results.append({"toolResult": {"toolUseId": use["toolUseId"], "content": [{"json": result}]}})
        messages.append({"role": "user", "content": results})

    answer = "".join(b.get("text", "") for b in output.get("content", [])).strip()
    # Nova が出力する思考タグを取り除く
    answer = re.sub(r"<thinking>.*?</thinking>", "", answer, flags=re.DOTALL).strip()
    return answer, tool_calls


def lambda_handler(event, context):
    if isinstance(event.get("body"), str):  # Function URL / API Gateway 経由にも対応
        event = json.loads(event["body"] or "{}")

    message = str(event.get("message", "")).strip()
    if not message:
        return {"error": "message は必須です"}
    session_id = str(event.get("session_id") or uuid.uuid4())

    history = load_history(session_id)
    answer, tool_calls = run_agent(message, history)
    save_turn(session_id, message, answer)

    return {"session_id": session_id, "answer": answer, "tool_calls": tool_calls}
