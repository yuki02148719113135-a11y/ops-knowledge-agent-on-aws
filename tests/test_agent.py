"""エージェント Lambda のロジックを、AWS を呼ばずに確かめるテスト。

  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path

from botocore.exceptions import ClientError

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.update({"MEMORY_TABLE": "memory", "KNOWLEDGE_BASE_ID": "KB123", "CLUSTER_ARN": "arn:cluster",
                   "DB_SECRET_ARN": "arn:secret"})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda" / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import handler  # noqa: E402
from _common import split_sql  # noqa: E402


class FakeBedrock:
    """1 回目はツールを 2 つ呼び、2 回目で回答する会話モデルの代わり。"""

    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        if len(self.calls) == 1:
            return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "t1", "name": "query_incidents",
                             "input": {"sql": "SELECT * FROM incident_summary"}}},
                {"toolUse": {"toolUseId": "t2", "name": "search_runbooks",
                             "input": {"query": "DB 接続数"}}},
            ]}}}
        return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [
            {"text": "<thinking>考え中</thinking>order-api が最多です（db-connection-exhaustion.md）。"}]}}}


class FakeRdsData:
    def __init__(self):
        self.sql = []

    def execute_statement(self, **kwargs):
        self.sql.append(kwargs["sql"])
        return {"formattedRecords": json.dumps([{"service": "order-api", "incident_count": 6}])}


class FakeAgentRuntime:
    def __init__(self, reject_hybrid=False):
        self.reject_hybrid = reject_hybrid
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        cfg = kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]
        if self.reject_hybrid and "overrideSearchType" in cfg:
            raise ClientError({"Error": {"Code": "ValidationException", "Message": "HYBRID not supported"}},
                              "Retrieve")
        return {"retrievalResults": [{
            "content": {"text": "pg_stat_activity を確認する"},
            "location": {"s3Location": {"uri": "s3://b/runbooks/db-connection-exhaustion.md"}},
            "score": 0.81234,
        }]}


class FakeDynamo:
    def __init__(self, items=None):
        self.items = items or []
        self.written = []

    def query(self, **kwargs):
        return {"Items": list(reversed(self.items))[: kwargs["Limit"]]}

    def batch_write_item(self, RequestItems):
        self.written.extend(RequestItems["memory"])


def item(role, text, ts):
    return {"role": {"S": role}, "text": {"S": text}, "created_at": {"N": str(ts)}}


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.bedrock, self.rds, self.kb, self.ddb = FakeBedrock(), FakeRdsData(), FakeAgentRuntime(), FakeDynamo()
        handler._clients.clear()
        handler._clients.update({"bedrock-runtime": self.bedrock, "rds-data": self.rds,
                                 "bedrock-agent-runtime": self.kb, "dynamodb": self.ddb})

    def test_tool_loop_and_memory(self):
        res = handler.lambda_handler({"session_id": "s1", "message": "一番多い障害は？"}, None)
        self.assertEqual(res["answer"], "order-api が最多です（db-connection-exhaustion.md）。")
        self.assertEqual([c["name"] for c in res["tool_calls"]], ["query_incidents", "search_runbooks"])
        self.assertEqual(self.rds.sql, ["SELECT * FROM incident_summary"])
        # 2 回目の converse にツール結果が渡っている
        tool_results = self.bedrock.calls[1]["messages"][-1]["content"]
        self.assertEqual(tool_results[0]["toolResult"]["content"][0]["json"]["row_count"], 1)
        self.assertEqual(tool_results[1]["toolResult"]["content"][0]["json"]["results"][0]["source"],
                         "db-connection-exhaustion.md")
        # 質問と回答のペアが保存される
        roles = [w["PutRequest"]["Item"]["role"]["S"] for w in self.ddb.written]
        self.assertEqual(roles, ["user", "assistant"])

    def test_history_starts_with_user(self):
        self.ddb.items = [item("assistant", "古い回答", 1), item("user", "前の質問", 2), item("assistant", "前の回答", 3)]
        handler.lambda_handler({"session_id": "s1", "message": "続きの質問"}, None)
        sent = self.bedrock.calls[0]["messages"]
        self.assertEqual([m["role"] for m in sent], ["user", "assistant", "user"])
        self.assertEqual(sent[0]["content"][0]["text"], "前の質問")

    def test_rejects_non_select(self):
        for sql in ["DELETE FROM incidents", "SELECT 1; DROP TABLE incidents", "update incidents set id=1"]:
            self.assertIn("error", handler.query_incidents(sql), sql)
        self.assertEqual(self.rds.sql, [])
        self.assertTrue(handler.is_read_only_sql("WITH x AS (SELECT 1) SELECT * FROM x;"))

    def test_hybrid_fallback(self):
        handler._clients["bedrock-agent-runtime"] = kb = FakeAgentRuntime(reject_hybrid=True)
        res = handler.search_runbooks("証明書")
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(len(kb.calls), 2)
        self.assertNotIn("overrideSearchType", kb.calls[1]["retrievalConfiguration"]["vectorSearchConfiguration"])

    def test_empty_message(self):
        self.assertIn("error", handler.lambda_handler({"message": "  "}, None))


class SplitSqlTest(unittest.TestCase):
    def test_repo_sql_files_split(self):
        root = Path(__file__).resolve().parent.parent / "sql"
        schema = split_sql((root / "schema.sql").read_text(encoding="utf-8"))
        self.assertTrue(schema[0].startswith("CREATE EXTENSION"))
        self.assertTrue(all(";" not in s.rstrip()[-1:] for s in schema))
        self.assertEqual(len(split_sql((root / "sample_data.sql").read_text(encoding="utf-8"))), 1)


if __name__ == "__main__":
    unittest.main()
