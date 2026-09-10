# P-1 地基接口 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给全站补上"任务可查、可取消、可重试且重试不重复出片"的地基接口，并让项目级参数能存能读——这是队列页与后续一切产能工作的前提。

**Architecture:** 全部落在既有分层里，不新增抽象：`transport → api → engines → infra`。新增一个 `jobs` RPC 命名空间（文件=命名空间，与 `api/system.py` 同构），`JobStore` 加一个列表查询，`export` 侧把失败写进 `export_jobs` 并让重试绑定原 id 覆盖写。契约由 `tests/transport/test_contract_sync.py` 强制：每个新 RPC 必须同时出现在 `protocol/schemas/*.json` 的 `x-methods` 里，否则测试红。

**Tech Stack:** Python 3.12 / pydantic v2 / stdlib sqlite3；JSON-RPC 2.0 over 环回 TCP + NDJSON（ADR-002）；协议契约在 `protocol/schemas/*.json` + `protocol/ts/index.ts`。

**规格来源：** `docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §6 的 P-1 行与「地基」两层。

---

## ⚠️ 并行工作区须知（开工前必读）

**2026-09-10 实测更新**：另一执行者已合入 `engine_configs` 全栈（提交 `299db8e`）与随后的 ASR 回退、e2e 改动。核对结果：

- **冲突已解除**：`api/__init__.py`（已含 `engine_configs` 注册）、`protocol/ts/index.ts`（已含其方法名）、`protocol/schemas/engine_configs.json` 均已落库，工作区干净。
- **P-1 的五个核心目标文件对方未动**：`api/export.py`、`infra/jobs.py`、`api/project.py`、`repos/projects.py`、`repos/exports.py` —— 本计划里的行号锚点**仍然有效**。
- **migrations 仍到 007**，本计划用 **008** 不变。
- **`settings.test_tts/test_asr/test_vlm` 的归属要重新看一眼**：`engine_configs` 已经建了"云端服务端点多实例"的配置面，这三条连通自检很可能该挂在它下面而不是 `settings`。本计划已把它们**排除在 P-1 之外**，正是为此。

**开工第一步仍然必须** `git status --short`：对方在持续推进，若上面五个文件出现脏状态，停下协调，不要在其上继续改。

**基线（2026-09-10 实测）**：`cd service && ../.venv/Scripts/python -m pytest tests` → **190 passed, 8 warnings in ~19s**。本计划全程**只增不减**。
`.venv` 在仓库根，不在 `service/` 下。`pyproject.toml` 有 `addopts = "-q"`，所以 `pytest -q` 等于 `-qq`，**不打印通过摘要行**——要计数就别加 `-q`。
已知 flaky（非本计划引入）：`tests/api/test_analysis.py::test_resync_semantic_refreshes_without_touching_asr` 偶发 30 秒超时；**别把它误判成自己的回归，也不得为它放宽断言**。

## Task 1 落地后的实测修正（Task 2-6 必须遵守）

Task 1 已完成（`74f19d0` 部分 + `aa3b84c` + `bdb6e6f`），过程中撞到三件计划没写的事：

1. **新增迁移必须同步 `tests/infra/storage/test_db.py::test_migrate_idempotent` 的白名单。** 该测试硬编码了迁移文件名的完整有序列表，任何新迁移都会让它红。对方提交 008 时漏了它，**HEAD 一度是红的**，由 `aa3b84c` 修回。**Task 5 若再加列请沿用同一处**。
2. **`list_recent` 已按实测加固，Task 2-4 直接依赖这个形状**：排序为 `ORDER BY updated_at DESC, created_at DESC, id`（`updated_at` 毫秒精度，同毫秒写入否则顺序随机，队列页会跳行）；`active_only` 用 `NOT IN (终态集)` 而非 `IN ('pending','running')`（将来新增非终态状态不会静默从队列页消失）。两条行为各有测试锁定。
3. **`model_download` 任务从不 `set_progress`、也从不 `mark_running`**——进度在 `downloader.download_in_background` 内部走 notifier，任务创建后一直停在 `pending` 直到被翻成 `completed`。**Task 4 的 `jobs.cancel` 必须预期这种情况**（`cancel_events` 里没有它 → 返回 `cancelling:false, reason:"任务不可中断"`），Task 6 文档里要写明这个已知限制，不要假装队列页对四类任务一视同仁。

另外：`set_progress` 的 label 贯通已覆盖 `analysis`(3 处) / `export`(1) / `narration`(2)；**prescreen 逐集循环、semantic 中间阶段、`_run_generation_parallel` 的线程计数处没有配对消息，未强接**——留待有真实需要时再说，别为凑齐而新增调用。

---

## 文件结构

**新建**
- `service/dramaclip/infra/storage/migrations/008_jobs_label_and_project_settings.sql` — `jobs.label` + `projects.settings`
- `service/dramaclip/api/jobs.py` — `jobs` 命名空间：`list` / `get` / `cancel`
- `protocol/schemas/jobs.json` — 该命名空间的契约与 `x-methods`
- `service/tests/api/test_jobs_api.py` — 三个 RPC 的行为
- `service/tests/infra/test_job_store_list.py` — JobStore 查询与标签
- `service/tests/api/test_export_retry.py` — 失败落库 + 重试幂等
- `service/tests/api/test_project_settings.py` — 项目级参数存取

**修改**
- `service/dramaclip/infra/jobs.py` — `list_recent()`、`set_label()`，`set_progress` 顺带更新标签
- `service/dramaclip/api/export.py` — 失败也写 `export_jobs`；新增 `retry`
- `service/dramaclip/api/project.py` — 新增 `update_settings`
- `service/dramaclip/infra/storage/repos/projects.py` — `set_settings()`，并在返回列里带出 `settings`
- `service/dramaclip/api/context.py` — 无需改（`cancel_events` 已存在）
- `service/dramaclip/api/__init__.py` — 注册 `jobs`
- `protocol/ts/index.ts` — `METHOD_NAMES` 补条目

---

# Task 1: jobs 表加标签列，JobStore 支持列表与标签

**Files:**
- Create: `service/dramaclip/infra/storage/migrations/008_jobs_label_and_project_settings.sql`
- Modify: `service/dramaclip/infra/jobs.py:46-51`（`set_progress`）、文件末尾追加
- Test: `service/tests/infra/test_job_store_list.py`

- [ ] **Step 1: 写失败测试**

```python
"""JobStore：标签写入与跨类型列表（队列页数据源）。"""

from __future__ import annotations

import sqlite3
import time

from dramaclip.infra import jobs as jobs_mod


def test_set_progress_updates_label(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("export", ref_id="e1")
    store.mark_running(job_id)
    store.set_progress(job_id, 42.0, label="切割 5/8")
    assert store.get(job_id)["label"] == "切割 5/8"


def test_list_recent_spans_types_and_is_newest_first(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    first = store.create("analysis", ref_id="p1")
    time.sleep(0.005)  # updated_at 是毫秒精度；不留间隔则同毫秒内顺序不确定
    second = store.create("prescreen", ref_id="p1")
    store.mark_running(first)
    time.sleep(0.005)
    store.set_progress(first, 10.0, label="第1集 转写中")
    store.mark_completed(second)
    rows = store.list_recent(limit=10)
    ids = [row["id"] for row in rows]
    assert ids[0] == second                      # 最新变更在前
    assert set(ids) == {first, second}
    assert rows[0]["type"] == "prescreen"
    assert any(row["label"] == "第1集 转写中" for row in rows)


def test_list_recent_filters_out_terminal_when_asked(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    live = store.create("export", ref_id="e1")
    done = store.create("export", ref_id="e2")
    store.mark_running(done)
    store.mark_completed(done)
    active = store.list_recent(limit=10, active_only=True)
    assert [row["id"] for row in active] == [live]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra/test_job_store_list.py -v`
Expected: 三条 FAIL —— `KeyError: 'label'` 或 `AttributeError: 'JobStore' object has no attribute 'list_recent'`。

- [ ] **Step 3: 写迁移**

新建 `service/dramaclip/infra/storage/migrations/008_jobs_label_and_project_settings.sql`：

```sql
-- P-1 地基：队列页需要人读标签与项目级参数覆盖。
-- 权威定义同步更新 docs/service/04-数据模型.md。
ALTER TABLE jobs ADD COLUMN label TEXT;
ALTER TABLE projects ADD COLUMN settings TEXT NOT NULL DEFAULT '{}';
```

迁移由 `infra/storage/db.py` 的 `migrate()` 按文件名顺序执行（现有 001~007 即此机制）；`migrations/` 下已有 `007_engine_configs.sql`，**故本文件必须编号 008**。

- [ ] **Step 4: 改 JobStore**

`service/dramaclip/infra/jobs.py` —— `set_progress` 换签名（`:46-51`）：

```python
    def set_progress(self, job_id: str, percent: float, label: str | None = None) -> None:
        """更新进度；label 为队列页要显示的人读阶段（如「第3集 预筛中」）。"""
        if label is None:
            self._conn.execute(
                "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (percent, _now_ms(), job_id),
            )
        else:
            self._conn.execute(
                "UPDATE jobs SET progress = ?, label = ?, updated_at = ? WHERE id = ?",
                (percent, label, _now_ms(), job_id),
            )
        self._conn.commit()
```

同文件把 `get` 的查询与键补上 `label`（`:53-62`）：

```python
    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, type, ref_id, status, progress, label, error, created_at, updated_at"
            " FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        keys = (
            "id", "type", "ref_id", "status", "progress",
            "label", "error", "created_at", "updated_at",
        )
        return dict(zip(keys, row, strict=True))
```

在 `sweep_interrupted` 之前插入 `list_recent`：

```python
    _LIST_COLUMNS = (
        "id", "type", "ref_id", "status", "progress", "label", "error", "created_at", "updated_at",
    )

    def list_recent(self, *, limit: int = 50, active_only: bool = False) -> list[dict[str, Any]]:
        """队列页数据源：按最近变更倒序取任务，可只要未终态。"""
        where = " WHERE status IN ('pending', 'running')" if active_only else ""
        rows = self._conn.execute(
            f"SELECT {', '.join(self._LIST_COLUMNS)} FROM jobs{where}"
            " ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(zip(self._LIST_COLUMNS, row, strict=True)) for row in rows]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/infra -q`
Expected: 全绿（含既有 jobs 测试；`set_progress` 新增参数有默认值，旧调用点不破）。
Run: `cd service && ../.venv/Scripts/python -m pytest tests`
Expected: 全量仍绿。

- [ ] **Step 6: 提交**

```bash
git add service/dramaclip/infra/storage/migrations/008_jobs_label_and_project_settings.sql \
        service/dramaclip/infra/jobs.py service/tests/infra/test_job_store_list.py
git commit -m "feat(jobs): 任务增人读标签与跨类型列表查询（队列页数据源）"
```

---

# Task 2: `jobs.list` / `jobs.get` RPC

**Files:**
- Create: `service/dramaclip/api/jobs.py`
- Create: `protocol/schemas/jobs.json`
- Modify: `service/dramaclip/api/__init__.py:14-25,42`
- Modify: `protocol/ts/index.ts`（`METHOD_NAMES`）
- Test: `service/tests/api/test_jobs_api.py`

- [ ] **Step 1: 写失败测试**

```python
"""jobs.list / jobs.get：队列页与"任务掉线后可查"的最小面。"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from dramaclip.api import jobs as jobs_api
from dramaclip.infra import jobs as jobs_mod
from dramaclip.transport.rpc import Router, RpcRequest
from dramaclip.transport.notify import Notifier


def _router(conn: sqlite3.Connection, store: jobs_mod.JobStore) -> Router:
    router = Router()
    context = SimpleNamespace(
        conn=conn, job_store=store, cancel_events={}, notifier=Notifier(lambda _m: None)
    )
    jobs_api.register(router, context)  # type: ignore[arg-type]
    return router


def _call(router: Router, method: str, params: dict) -> dict:
    response = router.dispatch(RpcRequest(id=method, method=method, params=params))
    assert response.error is None, response.error
    return response.result  # type: ignore[return-value]


def test_list_returns_jobs_newest_first(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    first = store.create("export", ref_id="e1")
    second = store.create("prescreen", ref_id="p1")
    store.set_progress(first, 30.0, label="切割 3/8")
    router = _router(memory_db, store)
    result = _call(router, "jobs.list", {})
    assert [item["id"] for item in result["jobs"]][0] == second
    assert {"id", "type", "ref_id", "status", "progress", "label"} <= set(result["jobs"][0])


def test_list_active_only_filter(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    live = store.create("export", ref_id="e1")
    done = store.create("export", ref_id="e2")
    store.mark_completed(done)
    router = _router(memory_db, store)
    result = _call(router, "jobs.list", {"active_only": True})
    assert [item["id"] for item in result["jobs"]] == [live]


def test_get_returns_single_job_with_error(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("export", ref_id="e1")
    store.mark_running(job_id)
    store.mark_failed(job_id, "编码失败")
    router = _router(memory_db, store)
    result = _call(router, "jobs.get", {"job_id": job_id})
    assert result["job"]["status"] == "failed"
    assert result["job"]["error"] == "编码失败"


def test_get_missing_job_is_domain_error(memory_db: sqlite3.Connection) -> None:
    router = _router(memory_db, jobs_mod.JobStore(memory_db))
    response = router.dispatch(RpcRequest(id=1, method="jobs.get", params={"job_id": "nope"}))
    assert response.error is not None
    assert response.error.code == -32404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_jobs_api.py -v`
Expected: 收集期即 FAIL —— `ModuleNotFoundError: No module named 'dramaclip.api.jobs'`。

- [ ] **Step 3: 写命名空间**

新建 `service/dramaclip/api/jobs.py`：

```python
"""jobs 命名空间：任务查询（队列页数据源）。取消在 Task 4 加入。"""

from __future__ import annotations

from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.transport.rpc import Router, RpcDomainError

_ERR_JOB_NOT_FOUND = -32404


def register(router: Router, context: AppContext) -> None:
    router.register("jobs.list", lambda params: list_jobs(context, params))
    router.register("jobs.get", lambda params: get_job(context, params))


def list_jobs(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """跨类型任务列表，按最近变更倒序。"""
    limit = min(int(params.get("limit", 50)), 200)
    active_only = bool(params.get("active_only", False))
    return {
        "jobs": context.job_store.list_recent(limit=limit, active_only=active_only),
        "server_time_ms": _now_ms(),
    }


def get_job(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    job_id = str(params.get("job_id", ""))
    job = context.job_store.get(job_id)
    if job is None:
        raise RpcDomainError(_ERR_JOB_NOT_FOUND, f"任务不存在: {job_id}")
    return {"job": job}
```

同文件末尾补时间源（与 `infra/jobs.py` 同语义，不跨模块引私有函数）：

```python
def _now_ms() -> int:
    return int(time.time() * 1000)
```
并在文件头 import 处加 `import time`。

- [ ] **Step 4: 登记命名空间**

`service/dramaclip/api/__init__.py` —— import 元组按字母序插入 `jobs`（在 `export` 与 `models` 之间）：

```python
    from dramaclip.api import (
        analysis,
        engine_configs,
        export,
        jobs,
        models,
        narration,
        project,
        settings,
        subtitle,
        system,
        timeline,
    )
```
注册行加在 `timeline.register(...)` 之后：

```python
    jobs.register(router, context)
```

> 该文件正被另一执行者改动（`engine_configs` 是本次新出现的）。**动手前先 `git status --short` 确认它干净**；若脏，等对方提交后再改，不要抢。

- [ ] **Step 5: 写契约 schema**

新建 `protocol/schemas/jobs.json`（形态对齐既有 `protocol/schemas/system.json`；`x-methods` 是 `test_contract_sync.py` 的比对源）：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://dramaclip.dev/protocol/jobs.json",
  "title": "jobs 命名空间（P-1 地基：任务查询与取消）",
  "namespace": "jobs",
  "x-methods": [
    {
      "name": "jobs.list",
      "summary": "跨类型任务列表，按最近变更倒序；active_only 只要未终态",
      "params": {
        "type": "object",
        "properties": {
          "limit": { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 },
          "active_only": { "type": "boolean", "default": false }
        },
        "additionalProperties": false
      },
      "result": {
        "type": "object",
        "required": ["jobs", "server_time_ms"],
        "properties": {
          "jobs": { "type": "array", "items": { "$ref": "#/$defs/JobInfo" } },
          "server_time_ms": { "type": "integer" }
        }
      }
    },
    {
      "name": "jobs.get",
      "summary": "单任务详情（含 error，供队列页显示失败原因）",
      "params": {
        "type": "object",
        "required": ["job_id"],
        "properties": { "job_id": { "type": "string" } },
        "additionalProperties": false
      },
      "result": {
        "type": "object",
        "required": ["job"],
        "properties": { "job": { "$ref": "#/$defs/JobInfo" } }
      }
    }
  ],
  "$defs": {
    "JobInfo": {
      "type": "object",
      "required": ["id", "type", "status", "progress", "created_at", "updated_at"],
      "properties": {
        "id": { "type": "string" },
        "type": { "type": "string", "description": "prescreen|analysis|narration|export|produce|model_download" },
        "ref_id": { "type": ["string", "null"] },
        "status": { "type": "string", "enum": ["pending", "running", "completed", "failed", "cancelled"] },
        "progress": { "type": "number" },
        "label": { "type": ["string", "null"], "description": "人读阶段，队列页显示" },
        "error": { "type": ["string", "null"] },
        "created_at": { "type": "integer" },
        "updated_at": { "type": "integer" }
      }
    }
  }
}
```

- [ ] **Step 6: 跑契约同步测试**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/transport/test_contract_sync.py -v`
Expected: 先 FAIL（`jobs.list` 在 router 里但 schema 未加载？不会——schema 已加）。**若报集合不等，按打印的差集补 `jobs.json` 的 `x-methods`**；补齐后应 PASS。这一步同时验证了"新 RPC 必须有契约"这条门禁真的在生效。

- [ ] **Step 7: 补 TS 侧方法名**

`protocol/ts/index.ts` 的 `METHOD_NAMES` 数组里，按同一分组位置插入两条：

```ts
  'jobs.list',
  'jobs.get',
```

Run: `cd desktop && npm run typecheck`
Expected: 干净（`METHOD_NAMES` 是 `as const` 数组，新增条目不破坏类型）。

- [ ] **Step 8: 全量门禁 + 提交**

Run: `cd service && ../.venv/Scripts/python -m pytest tests`
Expected: 全绿，条数 ≥ 基线 + 4。
```bash
git add service/dramaclip/api/jobs.py service/dramaclip/api/__init__.py \
        protocol/schemas/jobs.json protocol/ts/index.ts service/tests/api/test_jobs_api.py
git commit -m "feat(api): 新增 jobs.list / jobs.get（队列页地基）"
```

---

# Task 3: 导出失败必须落 `export_jobs`（先补记录，再谈重试）

**Files:**
- Modify: `service/dramaclip/api/export.py:40-62,138-169`
- Test: `service/tests/api/test_export_retry.py`

**为什么这一条在 retry 之前：** 实测 `jobs` 表有 44 条导出记录、`export_jobs` 只有 13 行，且 3 次失败只留了"服务中断"却没进 `export_jobs`——**失败路径与记录路径不同源**。retry 要"绑定原 export_id 覆盖写"，前提是失败时那个 id 存在。先补记录。

- [ ] **Step 1: 写失败测试**（自包含，不依赖未确认的仓储签名）

```python
"""导出失败必须在 export_jobs 留下带原因的记录，否则队列页与重试都无从谈起。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.narration.models import PlanData, TimelineSegment
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier


def _context(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings={},
        notifier=Notifier(lambda _m: None),
        executor=None,
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
    )


def _seed(memory_db: sqlite3.Connection, tmp_path: Path) -> tuple[str, str, str, PlanData]:
    """项目 + 一条引用不存在集的编排。项目下没有任何 episode，
    渲染时 encoder 必抛 EpisodeSourceMissing —— 确定失败，不需要真素材。"""
    project_id = str(projects_repo.create(memory_db, "重试剧", str(tmp_path))["id"])
    plan_data = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep-absent", start=0.0, end=1.0, audio="original")],
    )
    plan_id = str(
        plans_repo.create(
            memory_db, project_id, "raw_clip", ["ep-absent"], plan_data.model_dump()
        )["id"]
    )
    export_id = exports_repo.create(memory_db, project_id, plan_id, "raw_clip")
    return project_id, plan_id, export_id, plan_data


def test_render_failure_writes_export_job_with_error(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    context = _context(memory_db, tmp_path)
    project_id, plan_id, export_id, plan_data = _seed(memory_db, tmp_path)
    plan_row = plans_repo.get(memory_db, plan_id)
    assert plan_row is not None

    with pytest.raises(Exception, match="源文件缺失"):
        export_api.render_export(
            context, export_id, project_id, plan_row, plan_data,
            cancel_event=threading.Event(), report=lambda _p, _m: None,
        )

    record = exports_repo.get(memory_db, export_id)
    assert record is not None, "失败必须已在 export_jobs 留下该 id 的记录"
    assert record["status"] == "failed"
    assert record["error"], "失败原因必须落库，不能只进日志"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_export_retry.py -v`
Expected: FAIL —— `assert record is not None`（现在失败记录由 `_run_export` 的 `except` 写，而 `render_export` 自身不落库；本测试直接调 render 证明记录不随渲染产生）。

- [ ] **Step 3: 让 render 自己负责失败记录**

`api/export.py` 的 `render_export`（`:75-135`）整体包一层失败落库。把函数体改为"内层实现 + 外层记录"，最小改动形式：

```python
def render_export(
    context: AppContext,
    export_id: str,
    project_id: str,
    plan_row: dict[str, Any],
    plan_data: PlanData,
    *,
    cancel_event: threading.Event,
    report: Any,
) -> Path:
    """渲染核心：剪辑→遮罩→字幕→编码→写成品记录；失败就地落 failed 后原样抛出。"""
    try:
        return _render(
            context, export_id, project_id, plan_row, plan_data,
            cancel_event=cancel_event, report=report,
        )
    except Exception as exc:
        exports_repo.mark_failed(context.conn, export_id, str(exc))
        raise
```

把原 `render_export` 函数体整段改名为 `_render(...)`（参数不变，去掉最外层 `try` 的语义变化），并在 `_run_export` 的 `except` 里**去掉重复的 `mark_failed`**（`:166-169`），避免二次覆盖与错误来源不清：

```python
    except Exception as exc:
        context.job_store.mark_failed(job_id, str(exc))
        context.notifier.log("error", f"导出失败: {exc}")
```

- [ ] **Step 4: 让 `export.start` 在提交前就建好记录**

`api/export.py:40-62` 已经是 `exports_repo.create(...)` 先建记录再 submit（现状正确），**无需改动**——本步只做确认：

Run: `cd service && ../.venv/Scripts/python -c "import inspect;from dramaclip.api import export;print(inspect.getsource(export.start))"`
Expected: 打印出的 `start()` 里 `exports_repo.create` 出现在 `context.executor.submit` 之前。若不是（说明对方已重构），把 `create` 提到 submit 之前再进 Step 5。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api -q`
Expected: 全绿；`test_produce` 端到端不回归（它走成功路径）。

- [ ] **Step 6: 提交**

```bash
git add service/dramaclip/api/export.py service/tests/api/test_export_retry.py
git commit -m "fix(export): 渲染失败就地落 export_jobs 并记原因，不再只进日志"
```

---

# Task 4: `export.retry` 幂等重试 + `jobs.cancel` 统一取消

**Files:**
- Modify: `service/dramaclip/api/export.py:34-38`（注册）、末尾新增 `retry`
- Modify: `service/dramaclip/api/jobs.py`（加 `cancel`）
- Modify: `protocol/schemas/jobs.json`、`protocol/schemas/export.json`（`x-methods`）
- Modify: `protocol/ts/index.ts`
- Test: `service/tests/api/test_export_retry.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `tests/api/test_export_retry.py`，复用 Task 3 的 `_context` / `_seed`）

```python
def _export_router(memory_db: sqlite3.Connection, tmp_path: Path) -> tuple[Router, SimpleNamespace]:
    context = _context(memory_db, tmp_path)
    context.executor = ThreadPoolExecutor(max_workers=2)
    router = Router()
    export_api.register(router, context)  # type: ignore[arg-type]
    return router, context


def _call(router: Router, method: str, params: dict) -> dict:
    response = router.dispatch(RpcRequest(id=method, method=method, params=params))
    assert response.error is None, response.error
    return response.result  # type: ignore[return-value]


def test_retry_reuses_same_export_id_and_adds_no_row(
    memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """幂等核心：重试复用原 export_id，且不得新增记录（否则队列页出现重复成片）。

    不断言 status：重跑是异步的，读到时可能已再次失败——那正是失败记录该有的样子。
    """
    project_id, plan_id, export_id, _plan_data = _seed(memory_db, tmp_path)
    exports_repo.mark_failed(memory_db, export_id, "编码失败")
    router, _context = _export_router(memory_db, tmp_path)

    result = _call(router, "export.retry", {"export_id": export_id})
    assert result["export_id"] == export_id, "retry 不得返回新 id"
    assert "job_id" in result

    rows = exports_repo.list_by_project(memory_db, project_id)
    assert len(rows) == 1, "重试不得新增记录"
    assert rows[0]["id"] == export_id


def test_retry_rejects_completed_export(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    project_id, plan_id, export_id, _plan_data = _seed(memory_db, tmp_path)
    exports_repo.mark_completed(memory_db, export_id, str(tmp_path / "done.mp4"))
    router, _context = _export_router(memory_db, tmp_path)
    response = router.dispatch(
        RpcRequest(id=1, method="export.retry", params={"export_id": export_id})
    )
    assert response.error is not None
    assert response.error.code == -32405


def test_retry_rejects_unknown_export(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router, _context = _export_router(memory_db, tmp_path)
    response = router.dispatch(
        RpcRequest(id=1, method="export.retry", params={"export_id": "nope"})
    )
    assert response.error is not None
    assert response.error.code == -32404


def test_reset_for_retry_clears_error_and_output(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """纯仓储层：复位必须清 error / output_path / completed_at 并回到 pending。"""
    project_id, plan_id, export_id, _plan_data = _seed(memory_db, tmp_path)
    exports_repo.mark_failed(memory_db, export_id, "编码失败")
    exports_repo.set_meta(memory_db, export_id, duration_s=61.0, size_bytes=1024)

    exports_repo.reset_for_retry(memory_db, export_id)

    record = exports_repo.get(memory_db, export_id)
    assert record is not None
    assert record["status"] == "pending"
    assert record["error"] is None
    assert record["output_path"] is None
    assert record["completed_at"] is None
    assert record["progress"] == 0


def test_jobs_cancel_sets_registered_event(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("export", ref_id="e1")
    store.mark_running(job_id)
    event = threading.Event()
    context = SimpleNamespace(
        conn=memory_db, job_store=store, cancel_events={job_id: event},
        notifier=Notifier(lambda _m: None),
    )
    router = Router()
    jobs_api.register(router, context)  # type: ignore[arg-type]
    result = _call(router, "jobs.cancel", {"job_id": job_id})
    assert result["cancelling"] is True
    assert event.is_set()


def test_jobs_cancel_on_terminal_job_returns_false(memory_db: sqlite3.Connection) -> None:
    store = jobs_mod.JobStore(memory_db)
    job_id = store.create("export", ref_id="e1")
    store.mark_running(job_id)
    store.mark_completed(job_id)
    context = SimpleNamespace(
        conn=memory_db, job_store=store, cancel_events={},
        notifier=Notifier(lambda _m: None),
    )
    router = Router()
    jobs_api.register(router, context)  # type: ignore[arg-type]
    result = _call(router, "jobs.cancel", {"job_id": job_id})
    assert result["cancelling"] is False
    assert result["reason"] == "任务已终态"


def test_jobs_cancel_unknown_job_is_domain_error(memory_db: sqlite3.Connection) -> None:
    context = SimpleNamespace(
        conn=memory_db, job_store=jobs_mod.JobStore(memory_db), cancel_events={},
        notifier=Notifier(lambda _m: None),
    )
    router = Router()
    jobs_api.register(router, context)  # type: ignore[arg-type]
    response = router.dispatch(RpcRequest(id=1, method="jobs.cancel", params={"job_id": "x"}))
    assert response.error is not None
    assert response.error.code == -32404
```

同文件顶部补 import（Task 3 已建立的之外还需要的）：

```python
from concurrent.futures import ThreadPoolExecutor

from dramaclip.api import jobs as jobs_api
from dramaclip.transport.rpc import Router, RpcRequest
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_export_retry.py -v`
Expected: 新增 **七条** FAIL —— `export.retry` / `jobs.cancel` 未注册（`RpcError` 方法不存在）；`reset_for_retry` 为 `AttributeError`。Task 3 那一条应仍 FAIL 到 Step 3 完成为止。

- [ ] **Step 3: 实现 `export.retry`**

`api/export.py` 注册处（`:34-38`）加一行：

```python
    router.register("export.retry", lambda params: retry(context, params))
```

文件内新增（错误码常量放顶部，与 `_ERR_PLAN_NOT_FOUND` 并列）：

```python
_ERR_EXPORT_NOT_FOUND = -32404
_ERR_EXPORT_NOT_RETRYABLE = -32405


def retry(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """重试一条失败导出：**复用原 export_id 覆盖写**，不新建记录。"""
    export_id = str(params.get("export_id", ""))
    record = exports_repo.get(context.conn, export_id)
    if record is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    if record["status"] != "failed":
        raise RpcDomainError(
            _ERR_EXPORT_NOT_RETRYABLE, f"仅失败记录可重试，当前 {record['status']}"
        )
    plan_id = str(record["narration_plan_id"])
    plan_row = plans_repo.get(context.conn, plan_id)
    if plan_row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    plan_data = PlanData.model_validate(plan_row["plan_data"])
    exports_repo.reset_for_retry(context.conn, export_id)
    job_id = context.job_store.create("export", ref_id=export_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        _run_export, context, job_id, export_id, str(record["project_id"]),
        plan_row, plan_data, cancel_event,
    )
    return {"job_id": job_id, "export_id": export_id}
```

`repos/exports.py` 新增（放在 `mark_failed` 之后）：

```python
def reset_for_retry(conn: sqlite3.Connection, export_id: str) -> None:
    """重试前复位：清 error 与产物路径、进度归零、状态回 pending。"""
    conn.execute(
        "UPDATE export_jobs SET status = 'pending', error = NULL, output_path = NULL,"
        " progress = 0, completed_at = NULL WHERE id = ?",
        (export_id,),
    )
    conn.commit()
```

- [ ] **Step 4: 实现 `jobs.cancel`**

`api/jobs.py` 注册处加一行：

```python
    router.register("jobs.cancel", lambda params: cancel(context, params))
```

新增函数（复用 `AppContext.cancel_events`，与 `analysis.cancel` 同一注册表）：

```python
def cancel(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """按 job_id 请求取消；任务自己在下个检查点退出并标 cancelled。"""
    job_id = str(params.get("job_id", ""))
    job = context.job_store.get(job_id)
    if job is None:
        raise RpcDomainError(_ERR_JOB_NOT_FOUND, f"任务不存在: {job_id}")
    if job["status"] in ("completed", "failed", "cancelled"):
        return {"job_id": job_id, "cancelling": False, "reason": "任务已终态"}
    event = context.cancel_events.get(job_id)
    if event is None:
        return {"job_id": job_id, "cancelling": False, "reason": "任务不可中断"}
    event.set()
    context.notifier.log("info", f"已请求取消：{job['type']} {job.get('label') or job_id}")
    return {"job_id": job_id, "cancelling": True}
```

- [ ] **Step 5: 补契约**

`protocol/schemas/jobs.json` 的 `x-methods` 数组追加：

```json
    {
      "name": "jobs.cancel",
      "summary": "按 job_id 请求取消；已终态或不可中断时返回 cancelling=false 并给原因",
      "params": {
        "type": "object",
        "required": ["job_id"],
        "properties": { "job_id": { "type": "string" } },
        "additionalProperties": false
      },
      "result": {
        "type": "object",
        "required": ["job_id", "cancelling"],
        "properties": {
          "job_id": { "type": "string" },
          "cancelling": { "type": "boolean" },
          "reason": { "type": "string" }
        }
      }
    }
```

`protocol/schemas/export.json` 的 `x-methods` 追加：

```json
    {
      "name": "export.retry",
      "summary": "重试失败导出：复用原 export_id 覆盖写，不新建记录",
      "params": {
        "type": "object",
        "required": ["export_id"],
        "properties": { "export_id": { "type": "string" } },
        "additionalProperties": false
      },
      "result": {
        "type": "object",
        "required": ["job_id", "export_id"],
        "properties": { "job_id": { "type": "string" }, "export_id": { "type": "string" } }
      }
    }
```

`protocol/ts/index.ts` 的 `METHOD_NAMES` 补 `'jobs.cancel'` 与 `'export.retry'`。

- [ ] **Step 6: 门禁**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/transport -q`
Expected: `test_router_matches_schemas` PASS（集合相等，证明四个新方法与契约一一对应）。
Run: `cd service && ../.venv/Scripts/python -m pytest tests`
Expected: 全绿。
Run: `cd desktop && npm run typecheck && npm test`
Expected: 干净、13 passed。

- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/api/export.py service/dramaclip/api/jobs.py \
        service/dramaclip/infra/storage/repos/exports.py \
        protocol/schemas/jobs.json protocol/schemas/export.json protocol/ts/index.ts \
        service/tests/api/test_export_retry.py
git commit -m "feat(api): export.retry 幂等覆盖重试 + jobs.cancel 统一取消入口"
```

---

# Task 5: `project.update_settings`（项目级默认+覆盖的存储落点）

**Files:**
- Modify: `service/dramaclip/infra/storage/repos/projects.py`
- Modify: `service/dramaclip/api/project.py`（注册 + 新函数）
- Create: `protocol/schemas/project.json` 追加（该文件已存在，只加 `x-methods` 条目）
- Modify: `protocol/ts/index.ts`
- Test: `service/tests/api/test_project_settings.py`

- [ ] **Step 1: 写失败测试**

```python
"""项目级参数：K、转写档位、风格、字幕预设的覆盖值都存这里（默认+覆盖机制）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from dramaclip.api import project as project_api
from dramaclip.infra import jobs as jobs_mod
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


def _router(memory_db: sqlite3.Connection, tmp_path: Path) -> Router:
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings={},
        notifier=Notifier(lambda _m: None),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
    )
    router = Router()
    project_api.register(router, context)  # type: ignore[arg-type]
    return router


def _call(router: Router, method: str, params: dict) -> dict:
    response = router.dispatch(RpcRequest(id=method, method=method, params=params))
    assert response.error is None, response.error
    return response.result  # type: ignore[return-value]


def test_update_then_read_back(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "参数剧", "source_path": str(tmp_path)})
    _call(
        router, "project.update_settings",
        {"project_id": project["id"], "settings": {"variant_count": 3, "transcribe_mode": "full"}},
    )
    fetched = _call(router, "project.get", {"project_id": project["id"]})
    assert json.loads(fetched["project"]["settings"]) == {"variant_count": 3, "transcribe_mode": "full"}


def test_update_merges_not_replaces(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "合并剧", "source_path": str(tmp_path)})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"variant_count": 3}})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"subtitle_preset": "karaoke-pop"}})
    settings = json.loads(
        _call(router, "project.get", {"project_id": project["id"]})["project"]["settings"]
    )
    assert settings == {"variant_count": 3, "subtitle_preset": "karaoke-pop"}


def test_null_value_clears_key(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """恢复默认 = 把该键置 null，而不是删整个 settings。"""
    router = _router(memory_db, tmp_path)
    project = _call(router, "project.create", {"name": "清键剧", "source_path": str(tmp_path)})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"variant_count": 5, "style_id": "suspense"}})
    _call(router, "project.update_settings",
          {"project_id": project["id"], "settings": {"variant_count": None}})
    settings = json.loads(
        _call(router, "project.get", {"project_id": project["id"]})["project"]["settings"]
    )
    assert settings == {"style_id": "suspense"}


def test_missing_project_is_domain_error(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    router = _router(memory_db, tmp_path)
    response = router.dispatch(
        RpcRequest(id=1, method="project.update_settings",
                   params={"project_id": "nope", "settings": {}})
    )
    assert response.error is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_project_settings.py -v`
Expected: 四条 FAIL —— `project.update_settings` 未注册；`project.get` 返回的 project 无 `settings` 键。

- [ ] **Step 3: 仓储层**

`infra/storage/repos/projects.py`：先读该文件确认它的返回列元组名（`_COLUMNS` 或类似），把 `"settings"` 加进去，并新增两个函数：

```python
def get_settings(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT settings FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        return {}
    try:
        parsed = json.loads(str(row[0] or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def update_settings(
    conn: sqlite3.Connection, project_id: str, changes: dict[str, Any]
) -> dict[str, Any] | None:
    """合并写入；值为 None 表示清除该键（恢复默认）。项目不存在返回 None。"""
    if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        return None
    merged = get_settings(conn, project_id)
    for key, value in changes.items():
        if value is None:
            merged.pop(str(key), None)
        else:
            merged[str(key)] = value
    conn.execute(
        "UPDATE projects SET settings = ?, updated_at = ? WHERE id = ?",
        (json.dumps(merged, ensure_ascii=False), _now_ms(), project_id),
    )
    conn.commit()
    return merged
```
（该文件若无 `json` / `_now_ms`，按文件现状补 import 或复用其既有时间函数。）

- [ ] **Step 4: RPC 层**

`api/project.py` 注册处加一行（与其余 project 方法并列）：

```python
    router.register("project.update_settings", lambda params: update_settings(context, params))
```

新增函数（错误码沿用该文件既有的 `_ERR_PROJECT_NOT_FOUND`）：

```python
def update_settings(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """项目级参数覆盖（K / 转写档位 / 风格 / 字幕预设）。null 值=恢复该项默认。"""
    project_id = str(params.get("project_id", ""))
    changes = params.get("settings")
    if not isinstance(changes, dict):
        raise RpcDomainError(_ERR_INVALID_SETTINGS, "settings 必须是对象")
    merged = projects_repo.update_settings(context.conn, project_id, changes)
    if merged is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    return {"project_id": project_id, "settings": merged}
```
顶部补错误码常量：`_ERR_INVALID_SETTINGS = -32104`（接在该文件既有的 `-32101` / `-32102` / `-32103` 之后，同一号段）。

- [ ] **Step 5: 契约**

`protocol/schemas/project.json` 的 `x-methods` 追加：

```json
    {
      "name": "project.update_settings",
      "summary": "项目级参数覆盖（默认+覆盖机制的存储落点）；值为 null 表示恢复该项默认",
      "params": {
        "type": "object",
        "required": ["project_id", "settings"],
        "properties": {
          "project_id": { "type": "string" },
          "settings": { "type": "object", "additionalProperties": true }
        },
        "additionalProperties": false
      },
      "result": {
        "type": "object",
        "required": ["project_id", "settings"],
        "properties": {
          "project_id": { "type": "string" },
          "settings": { "type": "object", "additionalProperties": true }
        }
      }
    }
```

并在该文件 `Project` 的 `$defs` 属性里加 `"settings": { "type": "string", "description": "JSON 文本；项目级参数覆盖" }`。
`protocol/ts/index.ts` 的 `METHOD_NAMES` 补 `'project.update_settings'`，`Project` 接口加 `readonly settings: string;`。

- [ ] **Step 6: 门禁**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/transport tests/api -q`
Expected: 契约集合相等 PASS；四条新测试 PASS。
Run: `cd service && ../.venv/Scripts/python -m pytest tests`
Expected: 全绿。
Run: `cd desktop && npm run typecheck && npm test`
Expected: 干净（`Project` 加必填字段后，若前端有构造 `Project` 字面量的地方会报错——按报错补 `settings: '{}'`）。

- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/infra/storage/repos/projects.py service/dramaclip/api/project.py \
        protocol/schemas/project.json protocol/ts/index.ts desktop/src \
        service/tests/api/test_project_settings.py
git commit -m "feat(api): project.update_settings 与项目级参数存储（默认+覆盖落点）"
```

---

# Task 6: 文档收口与出口验证

**Files:**
- Modify: `docs/service/04-数据模型.md`（`jobs.label`、`projects.settings`）
- Modify: `docs/service/01-传输与API层设计.md`（新增 `jobs` 命名空间与方法数）
- Modify: `docs/03-IPC协议规范.md`（命名空间清单）

- [ ] **Step 1: 更新数据模型文档**

`docs/service/04-数据模型.md` 的 `jobs` 表定义加 `label TEXT`（人读阶段，队列页显示），`projects` 表加 `settings TEXT NOT NULL DEFAULT '{}'`（项目级参数覆盖，JSON）。注明迁移来源 008。

- [ ] **Step 2: 更新 API 层文档**

`docs/service/01-传输与API层设计.md` 的命名空间清单加 `jobs`（3 方法），并把方法总数改为实测值：

Run: `cd service && ../.venv/Scripts/python -c "from types import SimpleNamespace as S;from dramaclip.api import build_router;print(len(build_router(S(), shutdown=lambda:None).method_names))"`
Expected: 打印实际数（基线 36 + 本次 6 = 42 量级），按实测写文档，不写估计值。

- [ ] **Step 3: 出口验证（本计划的 DoD）**

- [ ] `cd service && ../.venv/Scripts/python -m pytest tests` 全绿，条数 ≥ 基线 + 11
- [ ] `cd desktop && npm run typecheck && npm test` 全绿
- [ ] 契约测试 PASS：新增 6 个 RPC 与 `x-methods` 集合相等
- [ ] **手工验证队列页数据源真的通了**：跑一次真实导出并中途杀 Python 进程 → 重启应用 → `jobs.list` 能查到那条 `failed` 且 `error='服务中断'`，`export.list` 里**同一 id 也在**（Task 3 的成果），`export.retry` 返回**同一个 export_id**（Task 4 的幂等成果）
- [ ] `grep -rn "work_dir.parent" service/dramaclip` 仍无命中（不回归 A1）

- [ ] **Step 4: 提交**

```bash
git add docs/service/04-数据模型.md docs/service/01-传输与API层设计.md docs/03-IPC协议规范.md
git commit -m "docs: P-1 地基接口收口（jobs 命名空间、008 迁移、方法数实测）"
```

---

## 本计划不做（明确划界）

- 队列页界面本身 → **P-2.5**（它依赖本计划的 `jobs.list`，但界面属 P-2.5）
- `narration.plan_variants` / `export.submit` 拆分 → **P-2**
- `project.batch_create`、`project.list` 阶段聚合、`licenses`/授权相关（已定案不做）→ **P-2 / 已移除**
- `settings.test_tts` / `test_asr` / `test_vlm` → 与另一执行者正在做的 `engine_configs` 命名空间重叠，**等其落地后再定归属**，不在本计划抢做
- 前端任何改动（除 Task 5 Step 6 因类型必填字段被迫产生的最小修补）
