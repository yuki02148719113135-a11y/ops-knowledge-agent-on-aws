"""MCP サーバーの登録コマンド／設定を、terraform output の値を埋めて表示する。

  python3 scripts/mcp_config.py
"""

from __future__ import annotations

import json
import sys

from _common import ROOT, tf_outputs


def main() -> None:
    out = tf_outputs()
    server = str(ROOT / "mcp_server" / "server.py")
    env = {
        "OPS_REGION": out["region"],
        "OPS_CLUSTER_ARN": out["cluster_arn"],
        "OPS_SECRET_ARN": out["agent_secret_arn"],  # エージェントと同じ読み取り専用ユーザー
        "OPS_DB_NAME": out["db_name"],
    }
    python = sys.executable

    print("■ Claude Code に登録する場合（このリポジトリのディレクトリで実行）\n")
    env_flags = " ".join(f"-e {k}={v}" for k, v in env.items())
    print(f"claude mcp add ops-aurora {env_flags} -- {python} {server}\n")

    print("■ Claude Desktop の場合（claude_desktop_config.json の mcpServers に追記）\n")
    print(json.dumps({"ops-aurora": {"command": python, "args": [server], "env": env}}, indent=2))


if __name__ == "__main__":
    main()
