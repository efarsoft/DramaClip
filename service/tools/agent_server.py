"""Agent 网关独立 CLI（源码部署、不起桌面时用）。

网关的权威实现与端点契约在 dramaclip/api/agent_gateway.py；桌面客户端由
service_app 按 agent_gateway.* 设置键自动管理同一个网关。本 CLI 覆盖的场景：
源码部署但不启动桌面，或想临时起一个独立端口。

端点面分两档（agent_gateway 的 `router_provider` 注入决定）：
  · 文本工具面（audit_script / audit_copy / draft_titles / retell_check）——
    库函数零转发，本 CLI 独立起即可全功能；
  · 生产链面（produce_chain / export_status / job_status，B3-14）——
    复用服务内 RPC Router 的库函数，需要 AppContext/job_store 等生产运行时。
    本 CLI 不构造 AppContext，生产链端点**如实回 501**
    （`reason: not_implemented_in_this_gateway`），不静默假绿。
    要跑全链生产，起桌面内建网关（偏好设置 → Agent 网关），或扩展本 CLI
    注入 router_provider（见 agent_gateway.AgentGateway 签名）。

用法：
    uv run python tools/agent_server.py [--port 8340] [--token xxx]
llm.* 配置直读本机数据库（DramaClip/data/data.db，DRAMACLIP_DATA 可指目录；
库缺表时自动迁移建表）。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dramaclip.api.agent_gateway import AgentGateway, make_handler  # noqa: E402,F401
from dramaclip.engines.narration import titles as titles_engine  # noqa: E402,F401
from dramaclip.infra.storage import db as db_mod  # noqa: E402

DEFAULT_PORT = 8340


def load_llm_settings() -> dict[str, str]:
    """llm.* 配置直读本机数据库；缺表自举（与 --from-db、服务内网关同一容错口径）。"""
    data_dir = os.environ.get("DRAMACLIP_DATA")
    db_path = (
        Path(data_dir) / "data.db"
        if data_dir
        else Path(__file__).resolve().parents[2] / "data" / "data.db"
    )
    conn = sqlite3.connect(db_path)
    try:
        try:
            rows = conn.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'llm%'"
            ).fetchall()
        except sqlite3.OperationalError:
            db_mod.migrate(conn)
            rows = conn.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'llm%'"
            ).fetchall()
    finally:
        conn.close()
    return {key: value for key, value in rows if value}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("DRAMACLIP_AGENT_PORT", DEFAULT_PORT))
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("DRAMACLIP_AGENT_TOKEN", ""),
        help="鉴权 token；缺省随机生成并打印",
    )
    args = parser.parse_args(argv)

    settings = load_llm_settings()
    settings.update({"agent_gateway.enabled": "true", "agent_gateway.port": str(args.port)})
    if args.token:
        settings["agent_gateway.token"] = args.token

    conn = sqlite3.connect(
        Path(os.environ.get("DRAMACLIP_DATA") or Path(__file__).resolve().parents[2] / "data")
        / "data.db"
    )
    data_root = (
        Path(os.environ["DRAMACLIP_DATA"])
        if os.environ.get("DRAMACLIP_DATA")
        else Path(__file__).resolve().parents[2] / "data"
    )
    gateway = AgentGateway(conn, trace_dir=data_root / "logs" / "llm")
    gateway.sync(settings)  # token 留空时此处生成并写回 settings
    token = settings.get("agent_gateway.token") or ""
    print(f"dramaclip-agent 网关: http://127.0.0.1:{args.port}")
    print(f"AGENT_TOKEN={token}")
    print("Ctrl+C 停止")
    stop = threading.Event()
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        gateway.stop()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
