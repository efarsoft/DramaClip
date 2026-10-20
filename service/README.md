# DramaClip Python 服务

包名 `dramaclip`。由 Electron 主进程 spawn，经本地套接字（Windows 命名管道 / Unix socket）
以 NDJSON + JSON-RPC 2.0 通信。设计文档见 `docs/service/`。

## 开发环境

依赖真相源是 `service/.venv`（uv 管理，与 `pyproject.toml`/`uv.lock` 同源）——桌面端 dev
启动时优先解析它，仓库根 `.venv` 仅是历史回退（缺失新依赖会让 OCR 等通道静默降级，
2026-10-20 实锤，勿再往根 venv 装东西）。

```bash
cd service
uv sync --all-extras
```

## 常用命令

```bash
cd service
uv run python -m ruff check .
uv run python -m mypy dramaclip
uv run python -m pytest
```

## 手动运行（调试）

```bash
# 先起一个回声服务端（模拟 Electron，如 nc -l 127.0.0.1 51801），然后：
DRAMACLIP_SERVICE_ADDRESS=127.0.0.1:51801 DRAMACLIP_AUTH_TOKEN=dev   uv run python -m dramaclip
```

退出码：0 正常；2 环境变量缺失；3 迁移失败。
