# 03 · IPC 协议规范

> Electron 主进程 ↔ Python 服务之间的线协议。schema 权威定义在 `protocol/schemas/`，本文是其人读版说明。
> 任何协议变更：先改 schema 与本文 → 再改两端实现（ADR 纪律）。

## 1. 传输层

| 项 | 规格 |
|----|------|
| 传输 | **127.0.0.1 环回 TCP**（ADR-002 修订版：Windows 命名管道因 Python CRT 句柄并发读写死锁被实测否决） |
| 地址 | `127.0.0.1:<随机端口>`（Electron 监听端口 0 由系统分配；仅环回绑定，无防火墙弹窗） |
| 服务端 | Electron 主进程（Node `net`） |
| 客户端 | Python 服务进程（stdlib `socket.create_connection`；读写为 `makefile` 的两个独立对象） |
| 连接数 | 单连接（Python 重启即重连同一端口；新连接到达时旧连接销毁） |
| 消息大小上限 | 单行 ≤ 16MB（超限视为协议错误，断开连接） |

## 2. 分帧：NDJSON

- 每条消息 = 一行 UTF-8 JSON，以 `\n` 结尾；
- 读侧自行缓冲拼接（跨 chunk 半行处理）；
- 写侧以锁保证**行原子性**（一行必须一次性完整写入，禁止交错）。

## 3. 握手（hello）

```
Electron spawn Python:
  env DRAMACLIP_SERVICE_ADDRESS = <127.0.0.1:port>
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
| **-32500 ~ -32599** | **任务域（任务不存在、不可取消等）—— P-1 新立** |

分段表本身登记于 `protocol/schemas/common.json` 的 `x-error-codes`，**以该文件为权威**，本文是其中
文说明；新增分段两处同改。
其中 `-32600 / -32602` 仅在 `transport/rpc.py` 里定义为常量、**当前没有任何抛出路径**：
Router 不做 schema 校验，参数问题一律由各 handler 抛业务域码（如 `-32102` 目录非法、
`-32104` settings 不是对象）。客户端按「保留码」处理即可，不要指望收到它们。

**已注册的具体码**（`service/dramaclip/api/*.py` 的 `_ERR_*` 常量实测）：

| 码 | 出处 | 语义 |
|----|------|------|
| -32001 / -32002 | settings | 未知键 / 值非法 |
| -32003 / -32004 | settings | LLM 未配置 / 不可达 |
| -32010 / -32011 / -32012 | models | 模型未知 / 状态不符（已安装、未安装、越界删除、导入体检不通过、撤销登记指向库内路径） / 导入缺 `path` |
| -32101 | project / analysis / narration | 项目不存在 |
| -32102 / -32103 | project | 目录非法 / 项目无集 |
| -32104 | project | `project.update_settings` 的 settings 不是对象 |
| -32201 ~ -32204 | analysis | 任务不存在 / 无集 / 无分析结果 / 段非法 |
| -32301 / -32302 | narration | 无分析结果 / 模式不支持 |
| -32310 / -32311 | engine_configs | 参数或状态非法（含「启用中的配置不可删」） / 配置不存在 |
| -32320 / -32321 | tts | 试听参数非法（引擎未接入工厂 / 文案空或超 60 字 / 音色会被引擎静默换掉 / 本地模型未下载） / 试听合成失败（含 0 字节产物、时长探不出来） |
| -32401 | export | 编排方案不存在 |
| -32406 | export | plan_ids 必须为非空数组 |
| -32407 | export | 方案不可渲染（状态非 ready / 时间轴为空 / 旁白段缺配音或音频丢失） |
| -32404 / -32405 | export | 导出记录不存在 / **不可重试**（非 failed 态、或已被并发重试抢先复位） |
| -32501 | jobs | 任务不存在 |

两处已知偏差（P-1 收口时如实登记，未擅自改动）：

1. **「任务不存在」有两个码**：`jobs.*` 用新立的任务域 `-32501`，而早于任务域的
   `analysis.cancel` 仍回分析域 `-32201`。客户端若要统一提示，需同时认这两个码；
   后续应把 `analysis.cancel` 迁到 `-32501`（属行为变更，需与前端同批）。
2. **engine_configs 借了剪辑域段**：`-32310/-32311` 落在 `-32300~-32399` 内，
   而该段语义是「剪辑」，与引擎配置无关。engine_configs 未获配自己的分段。

## 6. 方法命名空间

方法名 = `<namespace>.<method>`。全部方法登记于 `protocol/schemas/<ns>.json` 的 `x-methods`；TS 侧 `METHOD_NAMES` 常量与 Python 侧 `Router.method_names` 必须与之一致（两侧测试做集合相等校验，CI 强制）。
文件与命名空间**不是一一对应**：`analysis.prescreen` 单独登记在 `prescreen.json`（按阶段分文件，命名空间仍是 analysis），
`common.json` 只有共享信封定义与错误码/通知表、不含 `x-methods`。校验按「所有 `*.json` 的 x-methods 并集」做，故分文件不影响契约。

### W1 落地

| 方法 | 参数 | 返回 |
|------|------|------|
| `system.ping` | `{}` | `{service_version, protocol_version}` |
| `system.health` | `{}` | `{status:"ok", uptime_s, gpu?, vram_free_mb?, disk_free_gb?, models_ok?}`（扩展字段供侧边栏/工作台系统状态） |
| `system.shutdown` | `{}` | `{ok:true}`（Python 优雅退出） |

### 已落地全集（P-1 收口实测：**46 个方法 / 10 个命名空间**；2026-09-19 按工作树复测 **58 / 11**，较前次复测 +4 = D-P3 导入面，含他人未提交改动）

以 `Router.method_names` 与 `protocol/schemas/*.json` 的 `x-methods` 双向集合相等为准（两侧契约测试强制）。

- `project.*`（11）：create / list / get / delete / rename / duplicate / scan_episodes（导入=扫描目录，返回逐文件时长/大小）/ dashboard_summary（工作台统计4卡）/ ensure_covers / reorder_episodes / **update_settings**（P-1 新增：项目级参数覆盖，键级合并，`null` 值=恢复该项默认）
- `analysis.*`（7）：prescreen（阶段一预筛）/ start（阶段二全量）/ status / cancel / results / resync_semantic（语义增量刷新）/ update_asr（手工改写）
- `narration.*`（6）：plan_variants（阶段③：为选中模式各产出 K 条方案，只规划不渲染）/ list_plans / get_plan（单条方案详情+成本账）/ list_styles / generate_titles（LLM 生成候选标题）/ update_titles（整表保存候选标题）
- `export.*`（6）：submit（把已规划好的方案排队渲染，一条方案一个 job）/ **retry**（P-1 新增：复用原 export_id 覆盖写，仅 failed 可重试）/ list / list_works（跨项目作品库）/ get（单条导出记录）/ ensure_covers（补拍历史成片封面，幂等）
- `jobs.*`（3，**P-1 新建命名空间**）：list（跨类型任务列表，`limit`/`active_only`，队列页数据源）/ get（单任务详情，含 error）/ cancel（统一取消入口，不可中断时如实回 `cancelling:false + reason`）
- `models.*`（11）：list / download / scan_local（**只是重探测 `models/`**，不搬文件；登记本坏了回 `import_error`）/ delete（库内的删目录，登记在库外的那份只撤登记）/ **verify**（D-P1 新增：资产体检报告，不给 model_id 时报全部已落盘项）/ **import_inspect**、**import_commit**、**import_records**、**import_forget**（D-P3 导入向导：第 ② 步只读实测体检，第 ③ 步落位是作业 `model_import`，登记本全文与撤销入口。落位作业**故意不挂取消事件**：复制半途撤手只会留下一份比原状更糟的资产，所以 `jobs.cancel` 对它如实回 `cancelling:false + 任务不可中断`）/ runtime_status（CUDA 运行库安装态）/ install_runtime（下载并启用 CUDA 运行库，作业模式）
- `engine_configs.*`（6）：list / create / update / delete / enable / test（按能力域多实例，单启用）
- `settings.*`（3）：get / update / test_llm
- `subtitle.*`（1）：list_presets（内置+用户合并视图，ADR-008）
- `tts.*`（1，**D-P2 新建命名空间**）：preview（配音试听：用所选引擎+音色合成一句 ≤60 字短句，回本机音频路径；内容寻址缓存，不改设置、不下载模型、失败不换引擎）
- `system.*`（3）：见上表

**原案里规划但从未实现的方法**（不要按它们写客户端）：`project.open`（改为直接 `project.get`）、
`subtitle.preview`、`tts.list_voices`（音色目录在前端 `ttsVoices.ts`，未走 RPC）、
`export.status` / `export.cancel`（状态与取消统一走 `jobs.get` / `jobs.cancel` + `progress.update`）、
`models.cancel` / `models.import_local`（下载取消走 `jobs.cancel`；本地导入是 D-P3 的
`models.import_inspect` + `models.import_commit` 两步，`scan_local` 只是重探测）、
`narration.synthesize_tts`（配音是 `export.submit` 渲染链路的一环，不再单独开方法）。

## 7. 通知事件

| method | params | 说明 |
|--------|--------|------|
| `progress.update` | `{job_id, percent: 0-100, message, detail?}` | 长任务进度（jobs 表 job_id） |
| `log.append` | `{level: info\|warn\|error, message}` | 服务端日志 |
| `models.download_progress` | `{model_id, percent, status: downloading\|done\|failed}` | 模型下载进度（两端实际字段即此三项；原案的 `speed`/`eta` **从未实现**）。下载中 `percent` 钳在 99，只有 `status:"done"` 那条为 100 |

## 8. 心跳与失联

- Electron 每 5s 发 `system.ping`（4s 超时）；
- 连续 3 次失败 → kill Python → 交 restart-policy 处置（≤3 次退避重启，稳定 60s 清零）；
- Python 侧连接断开 → 进程自行退出（由 Electron 负责拉起，不做客户端重连逻辑，简化状态机）。

## 9. 版本协商

`protocol_version` 为整数（当前 1）。hello 时 Electron 校验，不匹配则拒绝启动并提示（防止 sidecar 与主程序版本错配）。
