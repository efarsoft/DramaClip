# 03 · IPC 协议规范

> Electron 主进程 ↔ Python 服务之间的线协议。schema 权威定义在 `protocol/schemas/`，本文是其人读版说明。
> 任何协议变更：先改 schema 与本文 → 再改两端实现（ADR 纪律）。

## 1. 传输层

| 项 | 规格 |
|----|------|
| 地址（Windows） | 命名管道 `\\.\pipe\dramaclip-<hex8>`（随机后缀，防多实例冲突与残留管道抢占） |
| 地址（非 Windows） | Unix domain socket `<tmp>/dramaclip-<hex8>.sock`（CI 与跨平台开发用） |
| 服务端 | Electron 主进程（Node `net` 原生监听） |
| 客户端 | Python 服务进程（stdlib：win 下文件句柄 / 其他 AF_UNIX） |
| 连接数 | 单连接（Python 重启即重连；旧连接出现时主动断开） |
| 消息大小上限 | 单行 ≤ 16MB（超限视为协议错误，断开连接） |

## 2. 分帧：NDJSON

- 每条消息 = 一行 UTF-8 JSON，以 `\n` 结尾；
- 读侧自行缓冲拼接（跨 chunk 半行处理）；
- 写侧以锁保证**行原子性**（一行必须一次性完整写入，禁止交错）。

## 3. 握手（hello）

```
Electron spawn Python:
  env DRAMACLIP_PIPE_ADDRESS = <地址>
  env DRAMACLIP_AUTH_TOKEN  = <64 hex 随机 token>
  env DRAMACLIP_DATA_DIR    = <数据目录>

Python 连接成功后【首条消息】:
  {"type":"hello","token":"<token>","service_version":"2.0.0","protocol_version":1}

Electron 校验:
  token 匹配 → 回 {"type":"hello-ack","app_version":"<x.y.z>"} → 连接就绪
  token 不匹配 / 10s 内未收到 hello → 断开并重启 Python（计入重启策略）
```

## 4. 消息类型

| type | 方向 | 说明 | 信封字段 |
|------|------|------|---------|
| `hello` / `hello-ack` | 双向 | 连接控制 | type, token*, service_version*, app_version*, protocol_version |
| `request` | E→P | JSON-RPC 2.0 请求 | jsonrpc:"2.0", id, method, params |
| `response` | P→E | 请求响应（成功二选一） | jsonrpc:"2.0", id, result \| error |
| `notification` | P→E | 服务端主动推送（无 id） | jsonrpc:"2.0", method, params |

- `id`：字符串（hex 自增），请求-响应按 id 关联；
- 心跳复用 `request/response`（`system.ping`）。

## 5. 错误码

| 码 | 含义 |
|----|------|
| -32700 | 消息解析失败（非法 JSON / 不符合信封） |
| -32600 | 无效请求 |
| -32601 | 方法不存在 |
| -32602 | 参数无效 |
| -32603 | 内部错误（handler 异常兜底） |
| -32000 ~ -32099 | 系统级业务错误（进程/资源） |
| -32100 ~ -32199 | 项目域（项目不存在、重复导入等） |
| -32200 ~ -32299 | 分析域（ASR 失败、格式不支持等） |
| -32300 ~ -32399 | 剪辑域（片段不足、编排失败等） |
| -32400 ~ -32499 | 导出域（FFmpeg 失败、磁盘不足等） |

## 6. 方法命名空间

方法名 = `<namespace>.<method>`。全部方法登记于 `protocol/schemas/<ns>.json` 的 `x-methods`；TS 侧 `METHOD_NAMES` 常量与 Python 侧 `Router.method_names` 必须与之一致（两侧测试做集合相等校验，CI 强制）。

### W1 落地

| 方法 | 参数 | 返回 |
|------|------|------|
| `system.ping` | `{}` | `{service_version, protocol_version}` |
| `system.health` | `{}` | `{status:"ok", uptime_s, gpu?, vram_free_mb?, disk_free_gb?, models_ok?}`（扩展字段供侧边栏/工作台系统状态） |
| `system.shutdown` | `{}` | `{ok:true}`（Python 优雅退出） |

### 后续阶段按需新增（登记于各命名空间 schema）

- `project.*`：create / open / list / delete / rename / duplicate / scan_episodes（导入=扫描目录，返回逐文件时长/大小）/ dashboard_summary（工作台统计4卡）
- `analysis.*`：prescreen（阶段一预筛）/ start（阶段二全量）/ status / cancel / results
- `narration.*`：generate_plans（LLM 一次生成各模式文案与编排）/ synthesize_tts / get_plan
- `export.*`：start / cancel / status / list
- `subtitle.*`：list_presets（内置+用户合并视图，ADR-008）/ preview
- `tts.*`：list_voices / preview
- `models.*`：list / download / cancel / delete / import_local
- `settings.*`：get / update

## 7. 通知事件

| method | params | 说明 |
|--------|--------|------|
| `progress.update` | `{job_id, percent: 0-100, message, detail?}` | 长任务进度（jobs 表 job_id） |
| `log.append` | `{level: info\|warn\|error, message}` | 服务端日志 |
| `models.download_progress` | `{model_id, percent, speed?, eta?}` | 模型下载进度 |

## 8. 心跳与失联

- Electron 每 5s 发 `system.ping`（4s 超时）；
- 连续 3 次失败 → kill Python → 交 restart-policy 处置（≤3 次退避重启，稳定 60s 清零）；
- Python 侧连接断开 → 进程自行退出（由 Electron 负责拉起，不做客户端重连逻辑，简化状态机）。

## 9. 版本协商

`protocol_version` 为整数（当前 1）。hello 时 Electron 校验，不匹配则拒绝启动并提示（防止 sidecar 与主程序版本错配）。
