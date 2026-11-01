"""ベクトル検索の実行計画を比べる実験。

「インデックスの演算子クラス」と「クエリの距離演算子」が一致しないと、
HNSW インデックスが使われず全件スキャン（Seq Scan）になることを確かめる。

  python3 scripts/explain_vector_search.py "DB の接続数が足りない"

  ケース A: <=>（コサイン距離）… vector_cosine_ops と一致 → Index Scan のはず
  ケース B: <->（L2 距離）    … 一致しない            → Seq Scan のはず

データが少ないとプランナーは安い全件スキャンを選びがちなので、
「インデックスを使えるかどうか」だけを見るために enable_seqscan = off で比較する。
"""

from __future__ import annotations

import argparse
import json

from _common import execute, session, tf_outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="DB の接続数が上限に達したときの対処")
    args = parser.parse_args()

    out = tf_outputs()
    s = session(out["region"])
    rds_data = s.client("rds-data")
    bedrock = s.client("bedrock-runtime")

    body = bedrock.invoke_model(
        modelId=out["embedding_model_id"],
        body=json.dumps({"inputText": args.query, "dimensions": 1024, "normalize": True}),
    )
    embedding = json.loads(body["body"].read())["embedding"]
    vec = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"

    db = dict(cluster_arn=out["cluster_arn"], secret_arn=out["admin_secret_arn"], database=out["db_name"])
    execute(rds_data, **db, sql="SELECT 1")  # 一時停止中なら先に起こす

    cases = {
        "A: <=> コサイン距離（インデックスと一致）": "<=>",
        "B: <-> L2 距離（インデックスと不一致）": "<->",
    }
    for title, op in cases.items():
        sql = (
            "EXPLAIN SELECT id, left(chunks, 40) FROM bedrock_integration.document_chunks "
            f"ORDER BY embedding {op} '{vec}'::vector LIMIT 4"
        )
        # SET LOCAL を同じトランザクション内で効かせる
        tx = rds_data.begin_transaction(resourceArn=db["cluster_arn"], secretArn=db["secret_arn"],
                                        database=db["database"])["transactionId"]
        try:
            execute(rds_data, **db, sql="SET LOCAL enable_seqscan = off", transaction_id=tx)
            resp = execute(rds_data, **db, sql=sql, transaction_id=tx)
        finally:
            rds_data.commit_transaction(resourceArn=db["cluster_arn"], secretArn=db["secret_arn"],
                                        transactionId=tx)
        print(f"\n=== {title} ===")
        for row in resp["records"]:
            print(row[0]["stringValue"])

    print("\nA に 'Index Scan using document_chunks_embedding_hnsw'、B に 'Seq Scan' が出れば想定どおり。")


if __name__ == "__main__":
    main()
