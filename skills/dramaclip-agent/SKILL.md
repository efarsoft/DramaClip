---
name: dramaclip-agent
description: 短剧解说成片的文案工具网关——指导你部署 DramaClip（下载客户端或 clone 项目两种路线），起本机 Agent 网关后通过 HTTP 调用解说文案审查（audit）、候选标题与发布物料生成（draft）。需要审查短剧解说文案质量、生成六句式标题/发布文案标签，或集成 DramaClip 文案能力到其他 agent 流程时使用。
---

# DramaClip Agent

短剧解说文案能力的远程调用网关：**部署本项目 → 起网关 → HTTP 调用**，用完即停。

能力面（三个工具端点，全部无状态）：

| 端点 | 作用 | 需要 LLM |
|------|------|---------|
| `POST /tools/audit_script` | 审查解说剧本（空钩/编造锚点/跨集因果/集号缺失等硬软检查） | 否 |
| `POST /tools/audit_copy` | 审查逐槽文案（槽位覆盖/行长/元叙述等） | 否 |
| `POST /tools/draft_titles` | 六类句式候选标题 ×8 + 发布文案 + 话题标签 | 是 |

审查能力零配置开箱即用；出稿能力需要 llm.* 配置（两条路线的差异主要就在这一步怎么来）。

## 安装引导：先选路线

| | 路线一：已用桌面客户端 | 路线二：源码部署 |
|---|---|---|
| 适合 | 已装/想要桌面产品（GUI 全流程出片） | 只想要 agent 工具面，不要 GUI |
| 额外前置 | 无（网关内置于客户端） | git + Python 3.12+ + uv |
| LLM 配置来源 | 客户端「引擎中心」配一次 | 命令行写入本机库（见下） |
| clone 仓库 | **不需要** | 需要（完整） |

### 路线一：已装（或准备装）桌面客户端（零 clone、零 Python）

客户端内置了网关——打开桌面应用的「偏好设置 → Agent 网关」：

1. 打开「启用 Agent 网关」开关，保存（端口默认 8340；token 首次启用自动生成并回填显示）。
2. 之后即可调用：`curl http://127.0.0.1:8340/health` 应返回 ok；`/tools/*` 调用携带
   `Authorization: Bearer <设置页显示的 token>`。
3. 前提：客户端「引擎中心」已配置文本模型（出稿需要；审查端点无此要求）。

设置改动即热生效（无需重启客户端）。

### 路线二：源码部署

前置：git、Python 3.12+、uv（`pip install uv` 或官方安装脚本）。

```bash
git clone https://github.com/efarsoft/DramaClip.git
cd DramaClip/service
uv sync --extra dev          # 文案/审查/标题只需 dev；--extra ml 仅整条分析管线才要
```

配置 llm.*（仅出稿能力需要；审查可跳过），两种方式任选：

```bash
# 方式 A：命令行直接写（把 sk-xxx 换成你的 key；DeepSeek 官方端点实测可用）
uv run python -c "
import sqlite3
from pathlib import Path
from dramaclip.infra.storage import db
from dramaclip.infra.storage.repos import settings as repo
conn = db.connect(Path('../data/data.db'))
db.migrate(conn)
for k, v in {'llm.base_url': 'https://api.deepseek.com', 'llm.model': 'deepseek-chat', 'llm.api_key': 'sk-xxx'}.items():
    repo.set_value(conn, k, v)
print('llm 配置完成')
"

# 方式 B：起一次桌面应用，在「引擎」页配置（会写入同一个库）
```

## 启动网关（两路线共用）

```bash
uv run python tools/agent_server.py          # 默认 127.0.0.1:8340
# 输出两行：网关地址 + AGENT_TOKEN=xxx（token 每次启动随机生成，记下来；Ctrl+C 停止）
```

健康检查（无需 token）：`curl http://127.0.0.1:8340/health`

## 调用

所有 `/tools/*` 端点须带 `Authorization: Bearer <AGENT_TOKEN>`。端点详情与字段契约见
[references/api.md](references/api.md)。

```bash
# 审查逐槽文案（零配置即用）
curl -s -X POST http://127.0.0.1:8340/tools/audit_copy \
  -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json" \
  -d '{"lines": [{"id": "s1", "text": "开场文案"}], "slots": [{"id": "s1", "task": "开场抛反差", "start": 0, "end": 12.5, "lines": "区间内台词"}]}'

# 生成候选标题 + 发布物料（需 llm 配置；中文 body 建议 UTF-8 文件体：--data-binary @body.json）
curl -s -X POST http://127.0.0.1:8340/tools/draft_titles \
  -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json" \
  -d '{"narration_texts": ["把这条片的解说文案整段贴在这里。"]}'
```

出稿（整条解说文案）走 CLI 更顺手（读同一个库的配置）：`uv run python tools/run_prompts.py run --mode copy --slots 槽位.json --from-db`。

## 注意事项

- 网关只绑 127.0.0.1 回环 + Bearer token；token 不要写进任何文件或提交。
- 端口被占换端口：`--port 8341`。Git Bash 下 curl 发中文 body 是本地码页编码，服务端会
  拒绝非 UTF-8——中文请求体写成 UTF-8 文件用 `--data-binary @file` 发送。
- 文案规则的单一真相源在引擎常量；`skills/dramaclip-narration/` 是给本项目内 agent 的
  方法论 skill（规则快照自动导出，漂移有测试守卫）。改规则改常量，勿改文档。
- 仅供学习研究；遵守目标平台条款，控制请求频率。
