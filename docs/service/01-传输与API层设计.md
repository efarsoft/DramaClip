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
    def log(level, message)                                # log.append
    def model_download(model_id, percent, ...)             # models.download_progress
```

engines 不直接持有 Notifier——api 层包装为 `ProgressReporter` 注入（保持 engines 与 transport 解耦）。

## 4. api/ —— 方法注册层

**文件 = 命名空间**（04 规约：单文件红线，禁止 routes.py 大杂烩）：

```
api/__init__.py     build_router() 组装全部命名空间（唯一 import 点）
api/system.py       ping / health / shutdown        （W1）
api/project.py      create/open/list/delete/scan_episodes   （W3）
api/analysis.py     prescreen/start/status/cancel/results   （W2-W10 逐步）
api/narration.py    generate_plans/synthesize_tts/get_plan  （W4-W9）
api/export.py       start/cancel/status/list                （W4）
api/subtitle.py     list_presets/preview                    （W7）
api/tts.py          list_voices/preview                     （W5）
api/models.py       list/download/cancel/delete/import_local（W10）
api/settings.py     get/update                              （W3）
```

**handler 签名约定**：`(params: dict[str, Any]) -> JSON 可序列化对象`；参数校验用 Pydantic 模型（每命名空间一个 `models.py` 或就近定义）。

**长任务模式（标准时序）**：

```
request: analysis.start {project_id, episode_ids}
  1. 校验参数与项目状态
  2. jobs.create(type='analysis', ref=...) → job_id
  3. executor.submit(执行函数, job_id, ...)   # 执行函数内经 ProgressReporter 推进度
  4. return {job_id}                          # 立即返回，绝不同步等待

后续：progress.update 事件推送；
查询：analysis.status {job_id} / analysis.results {project_id}
取消：analysis.cancel {job_id} → 取消执行池 future + 状态 cancelled
```

## 5. `__main__.py` —— 入口

| 项 | 约定 |
|----|------|
| 参数 | `--address <host:port>`（缺省读 env `DRAMACLIP_SERVICE_ADDRESS`） |
| 环境 | `DRAMACLIP_AUTH_TOKEN`（必填，缺失退出码 2）、`DRAMACLIP_DATA_DIR` |
| 启动 | 按 `00-服务总体设计` 第 3 节时序 |
| 退出码 | 0 正常退出；2 配置/环境错误；3 迁移失败 |
| 打包 | PyInstaller 入口（`dramaclip.__main__:main`），P2 |
