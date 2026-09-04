# @dramaclip/protocol

三端契约唯一真相源。

## 结构

- `schemas/*.json` —— **权威定义**：RPC 信封（common.json）、各命名空间方法登记（`x-methods`）；
- `ts/index.ts` —— TS 类型与 `METHOD_NAMES` 常量，与 schema 手写对齐。

## 规则

1. 修改契约必须**先改 schema**，再同步 TS 类型与 Python 侧（`service/dramaclip/transport/rpc.py`、各 api 模型）；
2. CI 双侧契约测试强制：TS `METHOD_NAMES` 与 Python `Router.method_names` 分别同 schemas `x-methods` 做集合相等校验；
3. 中期目标：quicktype 类 codegen 直接生成两侧类型，消灭手写对齐（见路线图 backlog）。

线协议规范（分帧/握手/错误码/通知）见 `docs/03-IPC协议规范.md`。
