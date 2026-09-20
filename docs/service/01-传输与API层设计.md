# service/01 · 传输与 API 层设计

> 对应代码 `service/dramaclip/transport/` 与 `service/dramaclip/api/`。
> 信封字段、错误码、握手细节以全局 `03-IPC协议规范.md` 为准。

## 1. transport/rpc.py —— 信封与路由

**Pydantic 模型**（与 `protocol/schemas/common.json` 对齐）：

| 模型 | 字段 |
|------|------|
| `RpcRequest` | jsonrpc, id, method, params(dict) |
| `RpcResponse` | jsonrpc, id, result \| error |
| `RpcError` | code, message, data? |
| `RpcNotification` | jsonrpc, method, params |

**Router**：

```python
class Router:
    def register(method: str, handler: Handler) -> None   # 重复注册抛 ValueError
    def dispatch(request: RpcRequest) -> RpcResponse      # 方法缺失 -32601；handler 异常兜底 -32603
    @property
    def method_names(self) -> tuple[str, ...]             # 契约同步测试的锚点
```

解析失败（非法 JSON / 信封不符）→ 构造 `id=None, code=-32700` 的响应。

## 2. transport/connection.py —— 连接客户端

| 组件 | 职责 |
|------|------|
| `LineAssembler` | 字节流 → 完整行（跨 chunk 缓冲，纯函数，单测覆盖半行/多行/空行） |
| `parse_address` | `'127.0.0.1:port'` → `(host, port)`，非法即抛错 |
| `ServiceConnection(address, on_message)` | 环回 TCP 客户端（`socket.create_connection`）；读写为 `makefile` 的**两个独立对象**，支持读线程/写线程并发（命名管道方案因此并发死锁被否决，ADR-002） |

行为约定：
- `send(obj)`：`json.dumps(ensure_ascii=False) + '\n'`，**写锁保证行原子**，底层循环写至完成；
- 读线程：`read(65536)` 阻塞读 → assembler 切行 → `on_message(dict)`；
- **EOF / 连接断开 → 回调 `on_disconnect` → 主流程退出进程**（不做客户端重连，重启权在 Electron，见协议规范第 8 节）；
- 单行 > 16MB：记录协议错误并退出。

## 3. transport/notify.py —— 通知

```python
class Notifier:  # 持有 connection.send
    def progress(job_id, percent, message, detail=None)   # progress.update
    def log(level, message, *, job_id=None)                # log.append（同时镜像 <data>/logs/backend.log）
    def tracked(job_id, fn, *args)                         # 包任务体：作用域内 log() 自动带 job_id
    def model_download(model_id, percent, ...)             # models.download_progress
```

任务体一律经 `tracked()` 投池（五处 `executor.submit` 站点）：线程池会复用工作线程，绑定
必须随任务体开始/结束成对发生，否则上一条任务的 `job_id` 会漏进下一条的日志。

engines 不直接持有 Notifier——api 层包装为 `ProgressReporter` 注入（保持 engines 与 transport 解耦）。

## 4. api/ —— 方法注册层

**文件 = 命名空间**（04 规约：单文件红线，禁止 routes.py 大杂烩）：

```
api/__init__.py     build_router(context, shutdown) 组装全部命名空间（唯一 import 点）
api/system.py       ping / health / shutdown                              （3）
api/project.py      create / list / get / delete / rename / duplicate /
                    scan_episodes / dashboard_summary / ensure_covers /
                    reorder_episodes / update_settings                   （11）
api/analysis.py     prescreen / start / status / cancel / results /
                    resync_semantic / update_asr                          （7）
api/narration.py    generate_plans / list_plans / produce / list_styles   （4）
api/export.py       start / retry / list / list_works                     （4）
api/subtitle.py     list_presets                                          （1）
api/models.py       list / download / scan_local / delete                 （4）
api/settings.py     get / update / test_llm                               （3）
api/engine_configs.py  create / list / update / delete / enable / test    （6）
api/jobs.py         list / get / cancel                                   （3）
```

**实测合计 46 个方法**（P-1 收口时以 `Router.method_names` 数出，非估算）。
命名空间分布：`project` 11、`analysis` 7、`engine_configs` 6、`export` 4、`models` 4、
`narration` 4、`jobs` 3、`settings` 3、`system` 3、`subtitle` 1。

「文件 = 命名空间」**当前无例外**。历史上唯一的例外是 `api/timeline.py`——它的实现文件
注册的是 `narration.replace_timeline`；该端点与「阶段条只读、不做方案片段手动调整」的既定
非目标冲突且前端零调用者，已于正确性批次整条删除（实现文件 + schema + `METHOD_NAMES` 同删）。
方法名集合由 `tests/transport/test_contract_sync.py` 与 `protocol/schemas/*.json` 的 `x-methods`
做**集合相等**校验（桌面侧 `desktop/src/__tests__/contract.test.ts` 同校验），
新增/删除方法漏登记 schema 即 CI 红——上面的 46 因此不是手工统计。

**尚无 api 文件的既定命名空间**：`tts.*`（原案 list_voices / preview）从未实现，且**没有任何音色枚举
RPC**——音色只有 `tts.voice` 这一设置键可用；`prescreen` 也不是独立命名空间：方法名是
`analysis.prescreen`，但其 schema 条目单独放在 `protocol/schemas/prescreen.json`（按阶段分文件，
命名空间仍属 analysis，故 analysis 的 7 个方法分布在 analysis.json 6 条 + prescreen.json 1 条）。

**handler 签名约定**：`(params: dict[str, Any]) -> JSON 可序列化对象`；参数校验用 Pydantic 模型（每命名空间一个 `models.py` 或就近定义）。

**长任务模式（标准时序）**：

```
request: analysis.start {project_id, episode_ids}
  1. 校验参数与项目状态
  2. context.job_store.create(type, ref_id) → job_id     # jobs 表一行，status=pending
  3. cancel_events[job_id] = threading.Event()           # 注册才可中断
  4. executor.submit(执行函数, job_id, ...)
  5. return {job_id}                                     # 立即返回，绝不同步等待

执行函数（线程池内）：
  job_store.mark_running(job_id)                          # 【必须】漏掉则崩溃后清扫不到（只扫 running）
  ... 分段 job_store.set_progress(job_id, pct, label)     # label = 队列页显示的人读阶段
  try/except → mark_completed / mark_failed(error)
  finally → cancel_events.pop(job_id, None)               # 【必须】否则字典无界增长

后续：progress.update 事件推送；
查询：jobs.list {limit, active_only} / jobs.get {job_id}（队列页统一数据源）
      analysis.status {job_id} / analysis.results {project_id}（域内详情仍走各自方法）
取消：jobs.cancel {job_id} → 置已注册的取消事件，任务自己在下个检查点退出并标 cancelled；
      已终态回 {cancelling:false, reason:"任务已终态"}，无注册事件回 reason:"任务不可中断"
      （绝不谎报已取消；各域自己的 *.cancel 仍在，但只翻事件、不改状态）
```

## 5. `__main__.py` —— 入口

| 项 | 约定 |
|----|------|
| 参数 | `--address <host:port>`（缺省读 env `DRAMACLIP_SERVICE_ADDRESS`） |
| 环境 | `DRAMACLIP_AUTH_TOKEN`（必填，缺失退出码 2）、`DRAMACLIP_DATA_DIR` |
| 启动 | 按 `00-服务总体设计` 第 3 节时序 |
| 退出码 | 0 正常退出；2 缺 `DRAMACLIP_SERVICE_ADDRESS` / `DRAMACLIP_AUTH_TOKEN`（`__main__._EXIT_ENV_MISSING`）。<br>原案设想的「3 迁移失败」**未实现**：`db.migrate()` 抛错时异常直穿，解释器以 1 退出 |
| 打包 | PyInstaller 入口（`dramaclip.__main__:main`），P2 |

## 6. P-1 收口已知限制（读代码前先看这条，别把接口当成已完成功能）

- **5 个新方法在桌面端零调用者**：`jobs.list` / `jobs.get` / `jobs.cancel` / `export.retry` /
  `project.update_settings` 只在 `protocol/ts/index.ts` 的 `METHOD_NAMES` 里登记，`desktop/src` 里
  没有一处调用——队列页、失败记录上的「重试」按钮、项目参数面板**都还没做**。P-1 兑现的是服务端地基。
- **`projects.settings` 尚无消费端**：写入与合并（键级、`null` 删键）已就绪并有测试，
  但 `projects_repo.get_settings()` **零调用者**，渲染/分析读的是全局 `context.settings`；
  现在写覆盖值不会改变任何行为。接线的同时要把实际使用的覆盖键名登记进 `04-数据模型` §3。
- **`api/models.py` 零测试覆盖**：P-1 修掉了 `models.download` 的真 bug（漏 `mark_running`
  → 记录永停 `pending` 且重启清不掉），但**修复本身没有自动化守卫**——`tests/` 下没有任何打到
  `api/models.py` 的用例。回归风险敞口在「下载/删除/本地扫描」四条方法上，补测试前别改动该文件。
- **启动清扫的三条计数是齐的**（`service_app.run()` 实测）：`job_store.sweep_interrupted()`（jobs 的
  running）、`episodes_repo.reset_stale_analyzing()`（分析中集）、`exports_repo.reset_stale_pending()`
  （pending 导出）三者任一非零即打 stdout 并 `log.append` 一条 warn，文案含全部三项计数。
  注意 `sweep_interrupted` 只扫 `running`——这正是上面那条 `mark_running` 纪律必须守住的原因。
