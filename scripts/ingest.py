"""S3 の手順書を Knowledge Base に取り込む（同期する）。

  python3 scripts/ingest.py

文書を追加・変更したら、terraform apply（S3 へアップロード）→ このスクリプト、の順で再実行する。
"""

from __future__ import annotations

import time

from _common import execute, session, tf_outputs


def main() -> None:
    out = tf_outputs()
    s = session(out["region"])
    rds_data = s.client("rds-data")
    agent = s.client("bedrock-agent")

    def count_chunks() -> int:
        resp = execute(rds_data, cluster_arn=out["cluster_arn"], secret_arn=out["admin_secret_arn"],
                       database=out["db_name"], sql="SELECT COUNT(*) FROM bedrock_integration.document_chunks")
        return resp["records"][0][0]["longValue"]

    # 取り込み中に Aurora が一時停止から復帰中だと失敗するので、先に起こしておく
    print("Aurora の状態を確認しています...")
    print(f"  取り込み前のチャンク数: {count_chunks()}")

    job = agent.start_ingestion_job(knowledgeBaseId=out["knowledge_base_id"],
                                    dataSourceId=out["data_source_id"])["ingestionJob"]
    job_id = job["ingestionJobId"]
    print(f"取り込みジョブを開始しました: {job_id}")

    while True:
        job = agent.get_ingestion_job(knowledgeBaseId=out["knowledge_base_id"],
                                      dataSourceId=out["data_source_id"],
                                      ingestionJobId=job_id)["ingestionJob"]
        status = job["status"]
        print(f"  status = {status}")
        if status in ("COMPLETE", "FAILED", "STOPPED"):
            break
        time.sleep(10)

    stats = job.get("statistics", {})
    print("結果:")
    for key in ("numberOfDocumentsScanned", "numberOfNewDocumentsIndexed",
                "numberOfModifiedDocumentsIndexed", "numberOfDocumentsDeleted", "numberOfDocumentsFailed"):
        print(f"  {key}: {stats.get(key, 0)}")
    for reason in job.get("failureReasons", []):
        print(f"  失敗理由: {reason}")

    print(f"取り込み後のチャンク数: {count_chunks()}")
    if status != "COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
