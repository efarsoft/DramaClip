# DramaClip Python 服务

包名 `dramaclip`。由 Electron 主进程 spawn，经本地套接字（Windows 命名管道 / Unix socket）
以 NDJSON + JSON-RPC 2.0 通信。设计文档见 `docs/service/`。

## 开发环境

```bash
# 仓库根目录
python -m venv .venv
.venv/Scripts/pip install -e "service[dev]"    # Windows
# .venv/bin/pip install -e "service[dev]"      # macOS/Linux
```

## 常用命令

```bash
cd service
../.venv/Scripts/python -m ruff check .
../.venv/Scripts/python -m mypy dramaclip
../.venv/Scripts/python -m pytest
```

## 手动运行（调试）

```bash
# 先起一个回声服务端（模拟 Electron，如 nc -l 127.0.0.1 51801），然后：
DRAMACLIP_SERVICE_ADDRESS=127.0.0.1:51801 DRAMACLIP_AUTH_TOKEN=dev \
  ../.venv/Scripts/python -m dramaclip
```

退出码：0 正常；2 环境变量缺失；3 迁移失败。
