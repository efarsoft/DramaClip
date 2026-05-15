# Ollama 集成方案

> 保存日期：2026-05-12
> 状态：**待实施**（当前采用 API 方式）

## 目标

让 DramaClip 通过 Ollama 实现**完全本地化 LLM 推理**，无需任何外部 API Key 即可完成文案生成、画面分析、脚本撰写等任务。

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        Electron 主进程                             │
│  ┌──────────────────────┐    ┌────────────────────────────┐      │
│  │   ollama/manager.ts  │◄──►│        BackendManager      │      │
│  │  （新建）              │    │       （已有，管理 Python）   │      │
│  │──────────────────────│    └────────────────────────────┘      │
│  │ • 检测 Ollama 是否已装  │                                      │
│  │ • 下载/安装/启动/停止   │                                      │
│  │ • 进程守护             │                                      │
│  └────────┬─────────────┘                                       │
│           │ subprocess                                          │
│           ▼                                                     │
│    ollama serve → http://localhost:11434                          │
├──────────────────────────────────────────────────────────────────┤
│                        Python 后端                                 │
│  ┌──────────────────────────────┐                                │
│  │   services/ollama_manager.py │  ← 新建                        │
│  │──────────────────────────────│                                │
│  │ • status()                   │  运行状态/GPU/模型列表           │
│  │ • list_models()              │  列出已下载模型                  │
│  │ • pull_model(name)           │  下载模型（含进度推送）           │
│  │ • delete_model(name)         │  删除模型                      │
│  │ • search_models(query)       │  搜索模型库                     │
│  │ • llm.py 增加 OllamaProvider  │  OpenAI 兼容协议直接对接         │
│  └────────┬─────────────────────┘                                │
│           │ subprocess → ollama CLI                               │
│           ▼                                                      │
│    ollama pull / list / rm / search ...                           │
├──────────────────────────────────────────────────────────────────┤
│                        Vue 前端                                    │
│  ┌──────────────────────────────────────────────┐                │
│  │  SettingsPage → 🦙 Ollama 管理标签页           │  ← 修改       │
│  │──────────────────────────────────────────────│                │
│  │ 状态卡片：未安装 / 已安装(版本) / 运行中(GPU/CPU)│               │
│  │ 已下载模型列表 + 删除按钮                       │               │
│  │ 模型搜索框 + 一键下载（含进度条）                 │               │
│  │ （未安装时）「安装 Ollama」按钮 + 下载进度         │               │
│  └──────────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────────┘
```

## 文件改动

| # | 操作 | 文件 | 说明 |
|---|---|---|---|
| 1 | 新建 | `docs/Plan_Ollama_Integration.md` | 本方案文档 |
| 2 | 新建 | `app/services/ollama_manager.py` | Ollama CLI 封装模块 |
| 3 | 新增 | `app/ipc/handlers.py` | +6 个 `ollama.*` RPC 方法 |
| 4 | 新增 | `app/ipc/router.py` | 注册新路由 |
| 5 | 新建 | `main/backend/ollama.ts` | Electron 侧管理类 |
| 6 | 修改 | `main/app.ts` | 启动时初始化 Ollama 管理 |
| 7 | 修改 | `src/services/ipc.ts` | 新增 `ollamaApi` 类型定义 |
| 8 | 修改 | `src/pages/SettingsPage.tsx` | 新增 🦙 Ollama 管理标签页 |
| 9 | 修改 | `app/services/llm.py` | 新增 `OllamaProvider` 类 |

## 关键流程

### 首次启动
```
用户打开 DramaClip → 设置页 → 🦙 标签
  状态：未安装 Ollama
  [安装 Ollama] 按钮

用户点击安装 →
  1. Electron 从 GitHub 下载 OllamaSetup.exe (~2-3MB，非 600MB)
  2. 显示下载进度条
  3. 静默安装：OllamaSetup.exe /S
  4. 自动启动 ollama serve
  5. 建议用户拉取模型（qwen2.5:7b ~4.5GB / qwen2.5:1.5b ~1GB）
```

### 日常使用
```
启动 DramaClip
  ├─ Electron 检测 ollama serve 是否运行
  │   ├─ 已运行 → 连接 → 查询状态
  │   └─ 未运行 → 启动 ollama serve → 等待就绪
  │
  ├─ 用户在 LLM provider 中选择 "Ollama"
  │   自动填充 http://localhost:11434/v1 + 选择模型
  │
  └─ 关闭 DramaClip
       └─ 可选：退出时关闭 / 后台保持
```

### 模型管理
```
Python 后端通过 subprocess 调用 ollama CLI：
  列出:     ollama list
  下载:     ollama pull <name>    ← 解析 stdout 获得 % 进度
  删除:     ollama rm <name>
  详情:     GET /api/tags
```

## 推荐默认模型

| 模型 | 大小 | 适用场景 |
|---|---|---|
| `qwen2.5:7b` | ~4.5GB | 文案生成 / 分析（⭐ 默认推荐） |
| `qwen2.5:1.5b` | ~1GB | 快速验证/低配机器 |
| `deepseek-r1:7b` | ~4.5GB | 推理/分析备选 |
| `llama3.2:3b` | ~2GB | 通用备选 |

## 技术要点

| 要点 | 处理方式 |
|---|---|
| 端口冲突 | 启动前检测 `localhost:11434`，被占用则跳过 |
| 用户已自装 | 直接连接，不重复安装 |
| GPU 检测 | `ollama ps` 输出判断是否有 GPU 加速 |
| 下载进度 | 解析 `ollama pull` stdout 百分比 → IPC 推送前端 |
| 进程守护 | ollama serve 异常退出时自动重启（最多 3 次） |
| 小模型推荐 | 安装完成后推荐用户下载 `qwen2.5:1.5b`（1GB，快速验证） |

## 不做的事

| ❌ 不做 | 原因 |
|---|---|
| 捆绑 ollama.exe 进安装包 | OllamaSetup.exe 本身会从 CDN 下载真实二进制 |
| 替换现有 TTS/ASR | Ollama 不支持语音，已有 faster-whisper / Edge-TTS 方案 |
| 管理 Docker / 其他引擎 | 只做 Ollama，保持单一入口 |
| 云端/远程 Ollama | 仅本地管理，远程连接走通用 OpenAI 兼容协议即可 |
