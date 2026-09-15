"""服务入口。由 Electron 主进程 spawn（连接信息经环境变量注入，ADR-002）。"""

from __future__ import annotations

import argparse
import os
import sys

# 模型已本地化 data/models（faster-whisper 为 HF 缓存布局），禁止 huggingface_hub
# 在每次模型加载时同步 GET huggingface.co 校验更新（国内网络有分钟级挂起风险）。
# 必须先于任何可能传递 import huggingface_hub 的模块；setdefault 保留显式调试覆盖。
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from dramaclip.service_app import ServiceApp  # noqa: E402 - 须在 env 设置之后 import

_EXIT_ENV_MISSING = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dramaclip-service", description="DramaClip 本地服务")
    parser.add_argument(
        "--address",
        default=None,
        help="套接字地址（缺省读环境变量 DRAMACLIP_SERVICE_ADDRESS）",
    )
    args = parser.parse_args(argv)

    address = args.address or os.environ.get("DRAMACLIP_SERVICE_ADDRESS", "")
    token = os.environ.get("DRAMACLIP_AUTH_TOKEN", "")
    if not address or not token:
        print(
            "缺少 DRAMACLIP_SERVICE_ADDRESS / DRAMACLIP_AUTH_TOKEN 环境变量（应由主进程注入）",
            file=sys.stderr,
        )
        return _EXIT_ENV_MISSING

    return ServiceApp(address, token).run()


if __name__ == "__main__":
    raise SystemExit(main())
