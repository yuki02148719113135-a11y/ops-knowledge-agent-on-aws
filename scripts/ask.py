"""エージェント Lambda に質問する。

  python3 scripts/ask.py "order-api で一番多い障害は？"
  python3 scripts/ask.py --session demo1 "その対処手順を教えて"   # 同じセッションなら前の会話を覚えている
"""

from __future__ import annotations

import argparse
import json

from _common import session, tf_outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("message", help="質問")
    parser.add_argument("--session", default="demo", help="会話セッション ID（既定: demo）")
    parser.add_argument("--raw", action="store_true", help="レスポンスの JSON をそのまま表示")
    args = parser.parse_args()

    out = tf_outputs()
    lam = session(out["region"]).client("lambda")
    resp = lam.invoke(
        FunctionName=out["agent_function_name"],
        Payload=json.dumps({"session_id": args.session, "message": args.message}).encode("utf-8"),
    )
    body = json.loads(resp["Payload"].read())

    if args.raw or "FunctionError" in resp:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return

    print(f"[session: {body.get('session_id')}]")
    for call in body.get("tool_calls", []):
        print(f"  🔧 {call['name']}: {json.dumps(call['input'], ensure_ascii=False)}")
    print()
    print(body.get("answer") or body.get("error"))


if __name__ == "__main__":
    main()
