# GPU 覆盖 P1（零新依赖）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 ASR、TTS、视频导出三条链的“本次实际用了什么算力”成为落库、可展示、可断言的事实；修掉显式 CUDA 静默回退与 AI 标注整片重编。

**Architecture:** 新增 `infra/compute.py` 作为唯一的算力回执契约（构造 + 不变量 + 显式 CUDA 异常）；各引擎在真实加载/推理后产出 `ComputeReport`，经 `jobs.compute`、`export_jobs.compute`、`models/selftest.json`、`PlanData.compute`、试听 sidecar 五个既有出口落账；UI 只读这些账，不从安装态猜运行态。AI 标注从“成片后整片 libx264 重编”折叠为段滤镜 `drawtext`，编码器收益不再在最后一步蒸发。

**Tech Stack:** Python 3.12/3.13、pytest、SQLite migrations、faster-whisper/CT2、funasr worker、Kokoro/IndexTTS/CosyVoice worker、FFmpeg、React + TypeScript。

**Spec:** `docs/superpowers/specs/2026-10-20-gpu-coverage-design.md`

## Global Constraints

- 本批**不新增依赖**；P2 的 ORT 版本不在此计划内。
- `auto` 才允许回退；显式 `cuda` 失败必须抛 `ComputeUnavailableError`，不得产出 `actual="cpu"`。
- 硬件/框架不支持时 `resolved="cpu"`、`fallback=false`；`unsupported` 不得显示成 GPU 已启用。
- 成功路径 `actual` 不得为 `unknown`；`unknown ≠ ok`。
- 回退只在“先试了 GPU、失败后落 CPU”时 `fallback=true`，且 `reason` 非空。
- 云端引擎报告 `resolved="cloud"`/`actual="cloud"`，忽略本地设备请求。
- 质量优先：AI 标注字体缺失、`drawtext` 失败一律硬失败，不交付无标注成片。
- 不把通知流当日志真相源；任务终态读数据库 `compute`。
- **不要提交**：用户尚未要求 commit。只改明确列出的文件，禁止宽 `git add`。
- 不碰 `docs/05-开发路线图.md`；不覆盖并行批次在改的 profile/UI。
- 测试命令统一在 `service/` 下执行：`../.venv/Scripts/python.exe -m pytest ...`。
- 全量收口：`../.venv/Scripts/python.exe -m pytest` 与 `../.venv/Scripts/python.exe -m ruff check dramaclip tests` 必须全绿。

---

### Task 1: 算力回执契约 `infra/compute.py`

**Files:**
- Create: `service/dramaclip/infra/compute.py`
- Test: `service/tests/infra/test_compute_contract.py`

**Interfaces:**
- Produces:
  - `class ComputeUnavailableError(RuntimeError)`
  - `@dataclass(frozen=True) class ComputeReport`，字段 `component: str, requested: str = "auto", resolved: str = "cpu", actual: str = "unknown", fallback: bool = False, reason: str = "", device: str = ""`
  - `ComputeReport.to_dict() -> dict[str, Any]`
  - `normalize_requested(value: str | None) -> str`（空/None → `"auto"`；非法值抛 `ValueError`）
  - `remember(report) -> dict[str, Any]`（`to_dict` 的别名，调用方不必知道 dataclass）
  - `assert_success(report: ComputeReport) -> None`（成功路径不变量，违约抛 `ComputeUnavailableError`）
  - `cloud(component: str, requested: str = "auto") -> ComputeReport`
  - `unsupported(component: str, requested: str, reason: str) -> ComputeReport`（`resolved="cpu", actual="cpu", fallback=False`）
- Invariants enforced in `__post_init__`:
  1. `requested ∈ {auto,cuda,cpu}`；`component/resolved/actual` 非空。
  2. `fallback=True` ⇒ `resolved=="cuda" and actual=="cpu" and reason.strip()`。
  3. `requested=="cpu"` ⇒ `resolved != "cuda"`（云端 `cloud` 合法）。
  4. `device` 为空时自动填 `actual`（视频编码器用 codec 名，如 `nvenc`）。
- `assert_success` additionally: `actual=="unknown"` 抛；`requested=="cuda"` 但 `actual!="cuda"` 抛；`requested=="cpu"` 但 `actual not in {"cpu","cloud"}` 抛。

- [ ] **Step 1: 写失败测试**

```python
"""compute 契约：回执形状、回退不变量、显式 cuda 的硬门。"""

from __future__ import annotations

import pytest

from dramaclip.infra import compute


def test_normalize_requested_defaults_to_auto() -> None:
    assert compute.normalize_requested(None) == "auto"
    assert compute.normalize_requested("") == "auto"
    assert compute.normalize_requested(" CUDA ") == "cuda"
    with pytest.raises(ValueError):
        compute.normalize_requested("gpu")


def test_fallback_requires_tried_cuda_and_reason() -> None:
    with pytest.raises(ValueError):
        compute.ComputeReport(
            component="asr.whisper", requested="auto", resolved="cuda",
            actual="cpu", fallback=True, reason="",
        )
    report = compute.ComputeReport(
        component="asr.whisper", requested="auto", resolved="cuda",
        actual="cpu", fallback=True, reason="cublas 缺失",
    )
    assert report.device == "cpu"


def test_unsupported_is_not_a_fallback() -> None:
    report = compute.unsupported("asr.whisper", "auto", "CT2 需要 sm_61")
    assert (report.resolved, report.actual, report.fallback) == ("cpu", "cpu", False)
    assert "sm_61" in report.reason


def test_explicit_cuda_success_requires_actual_cuda() -> None:
    bad = compute.ComputeReport(
        component="tts.kokoro", requested="cuda", resolved="cuda", actual="cpu",
        reason="静默回退",
    )
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(bad)


def test_success_rejects_unknown_but_accepts_video_codec() -> None:
    with pytest.raises(compute.ComputeUnavailableError):
        compute.assert_success(compute.ComputeReport(
            component="asr.whisper", requested="auto", resolved="cpu", actual="unknown",
        ))
    report = compute.ComputeReport(
        component="video.encode", requested="auto", resolved="h264_nvenc",
        actual="h264_nvenc",
    )
    compute.assert_success(report)
    assert report.device == "h264_nvenc"


def test_cloud_ignores_local_requested() -> None:
    report = compute.cloud("tts.cloud", requested="cuda")
    assert (report.resolved, report.actual, report.fallback) == ("cloud", "cloud", False)
    compute.assert_success(report)


def test_cpu_request_cannot_resolve_cuda() -> None:
    with pytest.raises(ValueError):
        compute.ComputeReport(
            component="asr.funasr", requested="cpu", resolved="cuda", actual="cuda",
        )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../.venv/Scripts/python.exe -m pytest tests/infra/test_compute_contract.py -v`
Expected: `ModuleNotFoundError: dramaclip.infra.compute`

- [ ] **Step 3: 实现**

```python
"""算力回执：请求归一、报告不变量、显式 CUDA 失败的统一异常。

引擎不各拼一套 JSON：`auto` 才允许试 GPU 后回退，显式 `cuda` 是承诺。
`actual` 允许视频编码器名（nvenc/qsv/libx264），不局限在设备三元组。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

_REQUESTED = frozenset({"auto", "cuda", "cpu"})


class ComputeUnavailableError(RuntimeError):
    """请求的算力不可用（显式 cuda 失败、或成功路径的实际设备违约）。"""


def normalize_requested(value: str | None) -> str:
    requested = (value or "auto").strip().lower()
    if requested not in _REQUESTED:
        raise ValueError(f"未知算力请求: {value!r}（可用: auto / cuda / cpu）")
    return requested


@dataclass(frozen=True)
class ComputeReport:
    component: str
    requested: str = "auto"
    resolved: str = "cpu"
    actual: str = "unknown"
    fallback: bool = False
    reason: str = ""
    device: str = ""

    def __post_init__(self) -> None:
        if not self.component or not self.resolved or not self.actual:
            raise ValueError("compute 回执的 component/resolved/actual 不能为空")
        if self.requested not in _REQUESTED:
            raise ValueError(f"未知算力请求: {self.requested!r}")
        if self.fallback and (
            self.requested != "auto"
            or self.resolved != "cuda"
            or self.actual != "cpu"
            or not self.reason.strip()
        ):
            raise ValueError("fallback=true 只表示 auto 下试过 GPU 后落 CPU，且必须带原因")
        if self.requested == "cpu" and self.resolved == "cuda":
            raise ValueError("requested=cpu 不得解析到 cuda")
        if not self.device:
            object.__setattr__(self, "device", self.actual)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def remember(report: ComputeReport) -> dict[str, Any]:
    return report.to_dict()


def assert_success(report: ComputeReport) -> None:
    """成功路径的最后一道防假绿：unknown / 显式 cuda 落 CPU 都判违约。"""
    if report.actual == "unknown":
        raise ComputeUnavailableError(
            f"{report.component} 成功路径没有实际设备证据（actual=unknown）"
        )
    if report.requested == "cuda" and report.actual != "cuda":
        raise ComputeUnavailableError(
            f"{report.component} 请求 cuda，实际 {report.actual}：{report.reason or '无原因'}"
        )
    if report.requested == "cpu" and report.actual not in {"cpu", "cloud"}:
        raise ComputeUnavailableError(
            f"{report.component} 请求 cpu，实际 {report.actual}"
        )


def cloud(component: str, requested: str = "auto") -> ComputeReport:
    return ComputeReport(
        component=component, requested=normalize_requested(requested),
        resolved="cloud", actual="cloud",
    )


def unsupported(component: str, requested: str, reason: str) -> ComputeReport:
    return ComputeReport(
        component=component, requested=normalize_requested(requested),
        resolved="cpu", actual="cpu", reason=reason,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `../.venv/Scripts/python.exe -m pytest tests/infra/test_compute_contract.py -v`
Expected: 7 passed

---

### Task 2: 落库 `jobs.compute` / `export_jobs.compute`

**Files:**
- Create: `service/dramaclip/infra/storage/migrations/024_compute_receipts.sql`
- Modify: `service/dramaclip/infra/jobs.py`
- Modify: `service/dramaclip/infra/storage/repos/exports.py`
- Test: `service/tests/infra/storage/test_db.py`
- Test: `service/tests/infra/test_jobs_compute.py` (new)

**Interfaces:**
- Produces:
  - `JobStore.set_compute(job_id: str, reports: list[dict[str, Any]]) -> None`
  - `JobStore.get()/list_recent()` 返回 `compute`（`list[dict] | None`，已解析 JSON）
  - `exports_repo.set_compute(conn, export_id: str, reports: list[dict[str, Any]]) -> None`
  - `exports_repo.get()/list_by_project()` 返回 `compute`
- Migration SQL:

```sql
-- 算力回执：JSON 数组（ComputeReport）；NULL = 本次没有可报告的运行证据。
ALTER TABLE jobs ADD COLUMN compute TEXT;
ALTER TABLE export_jobs ADD COLUMN compute TEXT;
```

- [ ] **Step 1: 写失败测试**

`service/tests/infra/storage/test_db.py` 的有序全等清单末尾追加：

```python
            "024_compute_receipts.sql",
```

新增 `service/tests/infra/test_jobs_compute.py`：

```python
"""jobs/export_jobs 的 compute 列：JSON 数组落库、读取解析、重试清空。"""

from __future__ import annotations

import json
import sqlite3

from dramaclip.infra.jobs import JobStore
from dramaclip.infra.storage.repos import exports as exports_repo


def test_job_compute_roundtrip(memory_db: sqlite3.Connection) -> None:
    store = JobStore(memory_db)
    job_id = store.create("analysis")
    report = {"component": "asr.whisper", "requested": "auto", "resolved": "cuda",
              "actual": "cpu", "fallback": True, "reason": "cublas", "device": "cpu"}
    store.set_compute(job_id, [report])
    assert store.get(job_id)["compute"] == [report]
    assert store.list_recent()[0]["compute"] == [report]


def test_export_compute_roundtrip_and_retry_clears(memory_db: sqlite3.Connection) -> None:
    exports_repo.create(memory_db, "p1", "n1", "intro")
    export_id = exports_repo.list_by_project(memory_db, "p1")[0]["id"]
    report = {"component": "video.encode", "requested": "auto", "resolved": "libx264",
              "actual": "libx264", "fallback": False, "reason": "", "device": "libx264"}
    exports_repo.set_compute(memory_db, export_id, [report])
    assert exports_repo.get(memory_db, export_id)["compute"] == [report]
    exports_repo.mark_failed(memory_db, export_id, "boom")
    assert exports_repo.reset_for_retry(memory_db, export_id) is True
    assert exports_repo.get(memory_db, export_id)["compute"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../.venv/Scripts/python.exe -m pytest tests/infra/test_jobs_compute.py tests/infra/storage/test_db.py -v`
Expected: 缺列 `compute`、迁移清单不等。

- [ ] **Step 3: 实现**

`jobs.py` 加模块函数：

```python
def _parse_compute(raw: object) -> list[dict[str, Any]] | None:
    if raw is None or raw == "":
        return None
    try:
        value = json.loads(str(raw))
    except ValueError:
        return None  # 坏 JSON 按“没有回执”处理，不演成可用证据
    return [dict(item) for item in value] if isinstance(value, list) else None
```

`JobStore` 加：

```python
    def set_compute(self, job_id: str, reports: list[dict[str, Any]]) -> None:
        self._conn.execute(
            "UPDATE jobs SET compute = ?, updated_at = ? WHERE id = ?",
            (json.dumps(reports, ensure_ascii=False), _now_ms(), job_id),
        )
        self._conn.commit()
```

`get` 的 SELECT 加 `compute`，keys 加 `"compute"`，返回前 `row = (*row[:-1], _parse_compute(row[-1]))`。
`_LIST_COLUMNS` 加 `"compute"`；`list_recent` 组装时把最后一列解析。

`exports.py`：`_COLUMNS` 加 `"compute"`；新增：

```python
def set_compute(conn: sqlite3.Connection, export_id: str, reports: list[dict[str, Any]]) -> None:
    conn.execute(
        "UPDATE export_jobs SET compute = ? WHERE id = ?",
        (json.dumps(reports, ensure_ascii=False), export_id),
    )
    conn.commit()
```

`get`/`list_by_project` 用 `_row(conn-row)` 解析 compute（与 jobs 同款 `_parse_compute`，在本文件内联一份，避免 infra→infra 反依赖）。
`reset_for_retry` 的 UPDATE 追加 `, compute = NULL`。

- [ ] **Step 4: 跑测试确认通过**

Run: `../.venv/Scripts/python.exe -m pytest tests/infra/test_jobs_compute.py tests/infra/storage/test_db.py -v`
Expected: 全绿

---

### Task 3: 协议类型与 schema

**Files:**
- Modify: `protocol/ts/index.ts`
- Modify: `protocol/schemas/jobs.json`
- Modify: `protocol/schemas/export.json`
- Modify: `protocol/schemas/engines.json`
- Modify: `protocol/schemas/tts.json`
- Test: `service/tests/transport/test_contract_sync.py`（现有）
- Test: `desktop` 的 `tsc`

**Interfaces:**
- Produces TS:

```ts
export interface ComputeReport {
  readonly component: string;
  readonly requested: 'auto' | 'cuda' | 'cpu';
  readonly resolved: string;
  readonly actual: string;
  readonly fallback: boolean;
  readonly reason: string;
  readonly device: string;
}
```

- `JobInfo.compute?: readonly ComputeReport[] | null`
- `ExportJob.compute?: readonly ComputeReport[] | null`
- `SelftestResult.compute?: ComputeReport | null`
- `TtsPreviewResult.compute?: ComputeReport | null`
- `TtsCleanReferenceResult.compute?: ComputeReport | null`
- `PlanData.compute?: readonly ComputeReport[]`

- [ ] **Step 1: 改 TS 类型并写一个编译期用例**

在 `desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx` 同级新增 `computeType.test.ts`：

```ts
import type { ComputeReport, JobInfo } from '@dramaclip/protocol';
import { describe, expect, it } from 'vitest';

describe('ComputeReport 协议类型', () => {
  it('任务可以携带回执数组', () => {
    const report: ComputeReport = {
      component: 'asr.whisper', requested: 'auto', resolved: 'cpu',
      actual: 'cpu', fallback: false, reason: 'CT2 需要 sm_61', device: 'cpu',
    };
    const job = {
      id: 'j1', type: 'analysis', ref_id: null, status: 'completed', progress: 100,
      created_at: 1, updated_at: 2, compute: [report],
    } satisfies JobInfo;
    expect(job.compute?.[0]?.actual).toBe('cpu');
  });
});
```

- [ ] **Step 2: 跑类型检查确认失败**

Run: `cd desktop && npx tsc --noEmit`
Expected: `ComputeReport` 不存在 / `compute` 不在 `JobInfo`。

- [ ] **Step 3: 实现类型与 schema**

TS：在 `JobInfo` 前加 `ComputeReport`，六个接口各加可选字段（见 Interfaces）。

Schema：`jobs.json` 的 `x-models` 加 `ComputeReport`，`JobInfo.properties` 加 `"compute": {"type": ["array","null"], "items": {"$ref": "#/x-models/ComputeReport"}}`；`export.json` 的 `ExportJob` 同形加 `compute`（本地定义一份同名 model）；`engines.json` 的 `SelftestResult` 加 `compute`（object 或 null）；`tts.json` 的 `tts.preview.result.properties` 与 `tts.clean_reference.result.properties` 各加 `compute`；`narration.json` 的 `NarrationPlan.plan_data` 是开放 object，无需 schema 改动。

`ComputeReport` schema（每个文件内联相同定义）：

```json
"ComputeReport": {
  "type": "object",
  "required": ["component", "requested", "resolved", "actual", "fallback", "reason", "device"],
  "properties": {
    "component": { "type": "string" },
    "requested": { "type": "string", "enum": ["auto", "cuda", "cpu"] },
    "resolved": { "type": "string" },
    "actual": { "type": "string" },
    "fallback": { "type": "boolean" },
    "reason": { "type": "string" },
    "device": { "type": "string" }
  }
}
```

- [ ] **Step 4: 跑契约与类型检查**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/transport/test_contract_sync.py -v`
Run: `cd desktop && npx tsc --noEmit && npx vitest run src/features/engines/__tests__/computeType.test.ts`
Expected: 全绿

---

### Task 4: ASR 设备语义与自检

**Files:**
- Modify: `service/dramaclip/engines/analysis/transcriber.py`
- Modify: `service/dramaclip/engines/analysis/runtime.py`
- Modify: `service/dramaclip/api/engines.py`
- Modify: `service/dramaclip/infra/model_manager/selftest.py`
- Modify: `service/dramaclip/engines/tts/workers/funasr_worker.py`
- Modify: `service/dramaclip/api/analysis_job.py`
- Test: `service/tests/infra/test_gpu_and_fallback.py`
- Test: `service/tests/api/test_selftest_compute.py` (new)

**Interfaces:**
- Consumes: `compute.normalize_requested`, `compute.ComputeReport`, `compute.ComputeUnavailableError`, `compute.assert_success`.
- Produces:
  - `AsrEngine.compute() -> ComputeReport | None`（协议新增；云端返回 `compute.cloud("asr.cloud")`）
  - `FasterWhisperEngine` 属性 `_requested: str`、`_actual_device: str | None`、`_fallback_reason: str`
  - `SenseVoiceEngine/ParaformerEngine.compute()` 从 `_actual_device/_fallback_reason` 构造
  - `run_asr(..., device: str = "auto")` 返回体含 `compute`
  - `selftest._build_asr` 对 SenseVoice/Paraformer 传 `device` + `models_dir`
  - funasr worker hello：`{"ready": true, "device": ..., "requested": ..., "fallback": ..., "reason": ...}`；失败时 `{"ready": false, "error": ...}` 并 `return 1`

- [ ] **Step 1: 重写 GPU 回退测试（先红）**

把 `test_cuda_failure_falls_back_to_cpu` 改名为 `test_auto_cuda_failure_falls_back_and_reports`：

```python
def test_auto_cuda_failure_falls_back_and_reports(monkeypatch) -> None:
    fake = types.SimpleNamespace(WhisperModel=_FakeWhisper)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    _FakeWhisper.created.clear()
    engine = FasterWhisperEngine("base", device="auto")
    model = engine._ensure_model()
    assert model.device == "cpu"  # type: ignore[attr-defined]
    report = engine.compute()
    assert report is not None
    assert (report.resolved, report.actual, report.fallback) == ("cuda", "cpu", True)
    assert "cublas" in report.reason
```

把 `test_cuda_failure_during_inference_falls_back` 的构造改 `device="auto"`，断言同样检查 `fallback is True`；新增显式 cuda 两条：

```python
def test_explicit_cuda_construction_failure_raises(monkeypatch) -> None:
    fake = types.SimpleNamespace(WhisperModel=_FakeWhisper)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    _FakeWhisper.created.clear()
    engine = FasterWhisperEngine("base", device="cuda")
    with pytest.raises(ComputeUnavailableError):
        engine._ensure_model()
    assert _FakeWhisper.created == ["cuda"], "不得再构造 CPU 模型"


def test_explicit_cuda_inference_failure_does_not_fallback(monkeypatch) -> None:
    fake = types.SimpleNamespace(WhisperModel=_FakeLazyWhisper)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    _FakeLazyWhisper.created.clear()
    engine = FasterWhisperEngine("base", device="cuda")
    with pytest.raises(ComputeUnavailableError):
        engine.transcribe(Path("x.wav"))
    assert _FakeLazyWhisper.created == ["cuda"]
```

新增 `service/tests/api/test_selftest_compute.py`：

```python
"""自检不得假绿：显式 cuda 落 CPU、actual=unknown 都判 ok=false。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra import compute
from dramaclip.infra.model_manager import selftest


class _Engine:
    name = "fake"

    def __init__(self, report: compute.ComputeReport) -> None:
        self._report = report

    def transcribe(self, _wav: Path, _lang: str) -> list[object]:
        seg = type("Seg", (), {"text": "你好"})()
        return [seg]

    def compute(self) -> compute.ComputeReport:
        return self._report


def test_explicit_cuda_actual_cpu_is_red(monkeypatch) -> None:
    report = compute.ComputeReport(
        component="asr.whisper", requested="cuda", resolved="cuda", actual="cpu",
        fallback=False, reason="静默回退",
    )
    monkeypatch.setattr(selftest, "_build_asr", lambda *_a, **_k: _Engine(report))
    result = selftest.run_asr(Path("models"), object(), device="cuda")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert "cuda" in result["error"]


def test_unknown_actual_is_red(monkeypatch) -> None:
    report = compute.ComputeReport(
        component="asr.whisper", requested="auto", resolved="cpu", actual="unknown",
    )
    monkeypatch.setattr(selftest, "_build_asr", lambda *_a, **_k: _Engine(report))
    result = selftest.run_asr(Path("models"), object())  # type: ignore[arg-type]
    assert result["ok"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../.venv/Scripts/python.exe -m pytest tests/infra/test_gpu_and_fallback.py tests/api/test_selftest_compute.py -v`
Expected: `compute()` 不存在、显式 cuda 仍回退、自检结果无 compute。

- [ ] **Step 3: 实现**

`transcriber.py`：

1. 顶部 `from dramaclip.infra import compute`。
2. 协议加 `def compute(self) -> compute.ComputeReport | None: ...`。
3. `FasterWhisperEngine.__init__`：
   ```python
   self._requested = compute.normalize_requested(device)
   self._actual_device: str | None = None
   self._fallback_reason = ""
   ```
4. `_ensure_model` 改为：

```python
    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            from faster_whisper import WhisperModel
            if self._requested == "cpu":
                self._model = self._create(WhisperModel, "cpu")
            else:
                target = "cuda" if self._requested == "cuda" or _ct2_cuda_available() else "cpu"
                self._model = self._create(WhisperModel, target)
        return self._model
```

`_ct2_cuda_available()`：

```python
def _ct2_cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - 探不到就按不可用，后面仍会用真实构造验一次
        return False
```

5. `_create` 改为：

```python
    def _create(self, cls: type[WhisperModel], device: str) -> WhisperModel:
        try:
            model = cls(
                self._model_size,
                device=device,
                compute_type=self._compute_for(device),
                download_root=str(self._models_dir) if self._models_dir else None,
            )
        except Exception as exc:  # noqa: BLE001
            if device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                raise
            if self._requested == "cuda":
                raise compute.ComputeUnavailableError(
                    f"faster-whisper 请求 CUDA，初始化失败：{type(exc).__name__}: {exc}"
                ) from exc
            _LOGGER.warning("CUDA 初始化失败，回退 CPU：%s", exc)
            self._actual_device = "cpu"
            self._fallback_reason = f"{type(exc).__name__}: {exc}"
            model = cls(
                self._model_size,
                device="cpu",
                compute_type=self._compute_for("cpu"),
                download_root=str(self._models_dir) if self._models_dir else None,
            )
        else:
            self._actual_device = "cuda" if device != "cpu" else "cpu"
        return model
```

6. `transcribe` 的 except：

```python
        except Exception as exc:  # noqa: BLE001
            if self._requested == "cuda":
                raise compute.ComputeUnavailableError(
                    f"faster-whisper 请求 CUDA，推理失败：{type(exc).__name__}: {exc}"
                ) from exc
            if self._actual_device == "cpu" or not _CUDA_PROBLEM.search(str(exc)):
                raise
            _LOGGER.warning("CUDA 推理失败，回退 CPU：%s", exc)
            from faster_whisper import WhisperModel
            self._actual_device = "cpu"
            self._fallback_reason = f"{type(exc).__name__}: {exc}"
            self._model = self._create(WhisperModel, "cpu")
            return self._run(self._model, wav_path, language, hotwords)
```

7. `compute()`：

```python
    def compute(self) -> compute.ComputeReport | None:
        if self._actual_device is None:
            return None
        resolved = "cpu" if (self._requested == "cpu" or self._actual_device == "cpu") else "cuda"
        if self._fallback_reason:
            resolved = "cuda"
        return compute.ComputeReport(
            component="asr.whisper",
            requested=self._requested,
            resolved=resolved,
            actual=self._actual_device,
            fallback=bool(self._fallback_reason),
            reason=self._fallback_reason,
        )
```

8. `SenseVoiceEngine/ParaformerEngine.__init__` 同样记录 `_requested = compute.normalize_requested(device)`、`_actual_device`、`_fallback_reason`。进程内 `_ensure_model`：
   - `target = _resolve_torch_device(self._requested)`
   - 构造失败且 `_CUDA_PROBLEM`：显式 cuda → `ComputeUnavailableError`；auto → 置 `_actual_device="cpu"`、reason，CPU 重试。
   - 成功：`_actual_device = "cuda" if target.startswith("cuda") else "cpu"`。
   - worker 分支：`worker = _spawn_funasr_worker(...)`；`hello = worker.ready`；`_actual_device = "cuda" if str(hello.get("device","cpu")).startswith("cuda") else "cpu"`；`_fallback_reason = str(hello.get("reason") or "")`。
   - `compute()` 用 `component="asr.funasr"`，逻辑同 whisper。
9. `_FunasrWorker.start` 保存 `self.ready = ready`（新增属性），`self.device = str(ready.get("device") or "cpu")`。
10. 云端 `DashscopeCloudAsrEngine.compute()` 返回 `compute.cloud("asr.cloud")`。

`funasr_worker.py`：

```python
def _probe_device(device: str) -> tuple[str, str]:
    """返回 (实际设备, 回退原因)。显式 cuda 探针失败由调用方直接失败。"""
    if device == "cpu":
        return "cpu", ""
    import torch
    if not torch.cuda.is_available():
        return "cpu", "torch.cuda.is_available() = False"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda:0", ""
    except Exception as exc:  # noqa: BLE001
        torch.cuda.empty_cache()
        return "cpu", f"{type(exc).__name__}: {exc}"
```

`main`：

```python
    requested = str(cfg.get("device") or "auto")
    actual, probe_reason = _probe_device(requested)
    if requested == "cuda" and actual != "cuda:0":
        _emit({"ready": False, "error": f"请求 CUDA 但探针失败：{probe_reason}"})
        return 1
    fallback = requested != "cpu" and actual == "cpu" and not probe_reason.startswith("torch.cuda.is_available")
    # 若 auto 因无 CUDA 直接落 CPU，不算“试过 GPU 后失败”：
    fallback = bool(probe_reason) and requested != "cpu"
    reason = probe_reason if fallback else (probe_reason if requested == "cuda" else "")
    kwargs = _build_kwargs(cfg, actual)
    try:
        model = AutoModel(**kwargs)
    except Exception as exc:
        if actual != "cpu" and _CUDA_PROBLEM.search(str(exc)):
            if requested == "cuda":
                _emit({"ready": False, "error": f"CUDA 加载失败：{type(exc).__name__}: {exc}"})
                return 1
            actual = "cpu"
            fallback = True
            reason = f"{type(exc).__name__}: {exc}"
            kwargs["device"] = actual
            model = AutoModel(**kwargs)
        else:
            raise
    _emit({"ready": True, "device": actual, "requested": requested,
           "fallback": fallback, "reason": reason})
```

修正 `_emit` 在 `try` 前定义（目前定义在后面）；把 `_probe_device` 的 `cuda:0` 传给 funasr 可接受。

`runtime.py` 第 115 行：`device = settings.get("asr.device", "auto")`。
`api/engines.py` 第 76 行：`str(context.settings.get("asr.device") or "auto")`。
`selftest.py`：
- `run_asr(..., device: str = "auto")`；
- 成功后：

```python
    report = engine.compute() if hasattr(engine, "compute") else None
    if report is not None:
        try:
            compute.assert_success(report)
        except compute.ComputeUnavailableError as exc:
            return {**_fail(str(exc)), "compute": report.to_dict()}
```

- 返回体加 `"compute": report.to_dict() if report is not None else None`。
- `_build_asr`：SenseVoice `SenseVoiceEngine(models_dir=models_dir, device=device)`；Paraformer 加 `device=device`（可保留 vad/spk 不传，自检只验基础转写）。
- `_build_asr` 对 worker 分支也生效（worker 配置里带 device）。

`api/analysis_job.py`：fresh 分析成功后（`raw = pipeline.analyze_episode(...)` 之后、写库之前）：

```python
            report = getattr(context.analysis_runtime.transcriber(), "compute", lambda: None)()
            if report is not None:
                context.job_store.set_compute(job_id, [report.to_dict()])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `../.venv/Scripts/python.exe -m pytest tests/infra/test_gpu_and_fallback.py tests/api/test_selftest_compute.py -v`
Expected: 全绿

Run: `../.venv/Scripts/python.exe -m pytest tests/engines/test_asr_pause_split.py tests/api -q`（现有 ASR/API 回归）
Expected: 全绿；若旧测试仍断言“显式 cuda 静默回退”，按本任务语义改断言而不是改实现。

---

### Task 5: TTS 设备参数、hello 捕获与 Kokoro GPU

**Files:**
- Modify: `service/dramaclip/engines/tts/base.py`
- Modify: `service/dramaclip/engines/tts/factory.py`
- Modify: `service/dramaclip/engines/tts/engines/indextts2.py`
- Modify: `service/dramaclip/engines/tts/engines/cosyvoice.py`
- Modify: `service/dramaclip/engines/tts/engines/kokoro.py`
- Modify: `service/dramaclip/engines/tts/workers/indextts_worker.py`
- Modify: `service/dramaclip/engines/tts/workers/cosyvoice_worker.py`
- Modify: `service/dramaclip/engines/tts/workers/kokoro_worker.py`
- Modify: `service/dramaclip/infra/config.py`
- Test: `service/tests/engines/tts/test_kokoro_device.py` (new)
- Test: `service/tests/engines/tts/test_worker_hello.py` (new)

**Interfaces:**
- `factory.create(engine, models_dir=None, *, api_key="", model="", device="auto")`
- `TtsEngine.compute() -> ComputeReport | None`（默认 `None`）
- `KokoroEngine(model_dir, device="auto")`
- `IndexTts2Engine(model_dir, device="auto")`
- `CosyVoiceEngine(model_dir, engine="cosyvoice", device="auto")`
- `tts.device` 默认 `"auto"`（`config.DEFAULTS`）
- worker hello（三个 worker 同形）：`{"ready": true, "requested": ..., "device": ..., "fallback": bool, "reason": ...}`；失败 `{"ready": false, "error": ...}` 且退出码非 0（Kokoro/IndexTTS/CosyVoice 主进程读到 ready=false 立即抛）

- [ ] **Step 1: 写失败测试**

`service/tests/engines/tts/test_kokoro_device.py`：

```python
"""Kokoro 必须真的 .to(device)；显式 cuda 失败不回退，auto 回退要记账。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.engines.tts.engines import kokoro as kokoro_mod
from dramaclip.infra import compute


class _FakeModel:
    def __init__(self, config: str, model: str) -> None:
        self.device = "cpu"
        self.moved_to: str | None = None

    def to(self, device: object) -> "_FakeModel":
        self.moved_to = str(device)
        self.device = self.moved_to
        return self

    def eval(self) -> "_FakeModel":
        return self


def test_kokoro_moves_model_to_cpu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(kokoro_mod, "_kokoro_importable", lambda: True)
    fake_kokoro = SimpleNamespace(KPipeline=lambda **_: object())
    fake_model_mod = SimpleNamespace(KModel=_FakeModel)
    monkeypatch.setitem(__import__("sys").modules, "kokoro", fake_kokoro)
    monkeypatch.setitem(__import__("sys").modules, "kokoro.model", fake_model_mod)
    engine = kokoro_mod.KokoroEngine(tmp_path, device="cpu")
    engine._ensure_pipeline()
    report = engine.compute()
    assert report is not None
    assert (report.requested, report.actual, report.fallback) == ("cpu", "cpu", False)


def test_kokoro_explicit_cuda_probe_failure_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(kokoro_mod, "_probe_torch_device", lambda _d: ("cpu", "cuda 不可用"))
    engine = kokoro_mod.KokoroEngine(tmp_path, device="cuda")
    with pytest.raises(compute.ComputeUnavailableError):
        engine._ensure_pipeline()
```

`service/tests/engines/tts/test_worker_hello.py`：

```python
"""worker 就绪行必须带 requested/device/fallback/reason；父进程不得丢弃。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dramaclip.engines.tts.engines import indextts2


class _FakeStdin:
    def write(self, _text: str) -> None: ...
    def flush(self) -> None: ...


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)

    def readline(self) -> str:
        return next(self._lines, "")


def test_hello_device_is_kept_for_later_instances(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    proc = subprocess.Popen.__new__(subprocess.Popen)
    proc.stdin = _FakeStdin()  # type: ignore[attr-defined]
    proc.stdout = _FakeStdout([  # type: ignore[attr-defined]
        json.dumps({"ready": True, "requested": "auto", "device": "cuda",
                    "fallback": False, "reason": ""}) + "\n",
        json.dumps({"id": "0", "ok": True}) + "\n",
    ])
    monkeypatch.setattr(indextts2, "_PROC", proc)
    monkeypatch.setattr(indextts2, "_HELLO", {})
    monkeypatch.setattr(indextts2, "runtime_ready", lambda: True)
    engine = indextts2.IndexTts2Engine(tmp_path, device="auto")
    engine._synth_one("你好", "ref.wav", tmp_path / "out.wav")
    report = engine.compute()
    assert report is not None
    assert (report.resolved, report.actual) == ("cuda", "cuda")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../.venv/Scripts/python.exe -m pytest tests/engines/tts/test_kokoro_device.py tests/engines/tts/test_worker_hello.py -v`
Expected: `KokoroEngine` 不接受 device、`compute` 不存在、hello 被丢弃。

- [ ] **Step 3: 实现**

`config.py` 在 `tts.engine` 附近加：

```python
    # 本地 TTS 设备：auto=能力+运行时都过才用 GPU，失败回退并记账；cuda=承诺，失败即报错
    "tts.device": "auto",
```

`base.py` 协议加：

```python
    def compute(self) -> "ComputeReport | None":
        """最近一次真实推理的算力回执；没跑过返回 None，不猜。"""
        return None
```

顶部 `from dramaclip.infra.compute import ComputeReport`。

`factory.create` 加 `device: str = "auto"` 参数，传给三个本地引擎；`capabilities()` 调用不带 device（能力探测不触发加载）。

`indextts2.py` / `cosyvoice.py`：

- `__init__(..., device="auto")` 保存 `self._device = compute.normalize_requested(device)`。
- 模块级 `_HELLO: dict[subprocess.Popen[str], dict[str, Any]] = {}` 替换 `_HELLOED_FOR`。
- `_ensure_worker(models_dir, device)` 增加设备分叉：现有 `_PROC` 存活但 `_PROC_DEVICE != device` 时 terminate 并重置 `_PROC`/`_HELLO`。新增 `_PROC_DEVICE: str | None`。
- 启动参数末位用 `device` 而不是 `"auto"`。
- `_synth_one`：

```python
        with _IO_LOCK:
            proc = _ensure_worker(self._model_dir, self._device)
            if proc.stdin is None or proc.stdout is None:
                raise RuntimeError("worker 进程管道不可用")
            hello = _HELLO.get(proc)
            if hello is None:
                line = proc.stdout.readline()
                try:
                    hello = json.loads(line)
                except ValueError as exc:
                    raise RuntimeError("worker 未返回可解析的就绪行") from exc
                if not hello.get("ready"):
                    raise RuntimeError(f"worker 启动失败：{hello.get('error', '未知原因')}")
                _HELLO[proc] = hello
            ...
```

- `compute()`：

```python
    def compute(self) -> compute.ComputeReport | None:
        proc = _PROC
        hello = _HELLO.get(proc) if proc is not None else None
        if hello is None:
            return None
        return compute.ComputeReport(
            component="tts.indextts2",
            requested=str(hello.get("requested") or self._device),
            resolved="cuda" if str(hello.get("device", "")).startswith("cuda") else "cpu",
            actual="cuda" if str(hello.get("device", "")).startswith("cuda") else "cpu",
            fallback=bool(hello.get("fallback")),
            reason=str(hello.get("reason") or ""),
        )
```

CosyVoice 同形，component `tts.cosyvoice`。

`indextts_worker.py` / `cosyvoice_worker.py`：

```python
def _probe_device(requested: str) -> tuple[str, str]:
    if requested == "cpu":
        return "cpu", ""
    import torch
    if not torch.cuda.is_available():
        return "cpu", "torch.cuda.is_available() = False"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda", ""
    except Exception as exc:  # noqa: BLE001
        torch.cuda.empty_cache()
        return "cpu", f"{type(exc).__name__}: {exc}"
```

`main` 中：

```python
    requested = sys.argv[2] if len(sys.argv) > 2 else "auto"
    device, probe_reason = _probe_device(requested)
    if requested == "cuda" and device != "cuda":
        send({"ready": False, "error": f"请求 CUDA 但探针失败：{probe_reason}"})
        return 1
    fallback = bool(probe_reason) and requested != "cpu"
    reason = probe_reason if fallback else ""
```

模型构造失败时：显式 cuda → send ready=false + return 1；auto → `device="cpu"`、`fallback=True`、reason 填异常，重建一次。成功 hello 带四字段。

`kokoro_worker.py`：

```python
def _probe_device(requested: str) -> tuple[str, str]:
    if requested == "cpu":
        return "cpu", ""
    import torch
    if not torch.cuda.is_available():
        return "cpu", "torch.cuda.is_available() = False"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda", ""
    except Exception as exc:
        torch.cuda.empty_cache()
        return "cpu", f"{type(exc).__name__}: {exc}"
```

`cfg["device"]` 取请求；显式 cuda 探针失败 → `_emit({"ready": False, "error": ...})`；`return 1`。构造 `KModel(...).to(torch.device(device)).eval()`。hello 带四字段。

`kokoro.py`：

- `__init__(model_dir, device="auto")`。
- `_ensure_worker` 配置带 `"device": self._device`。
- `_probe_torch_device(device) -> tuple[str, str]`（与 worker 同款；模块级函数便于测试 monkeypatch）。
- `_ensure_pipeline`：

```python
        target, probe_reason = _probe_torch_device(self._device)
        if self._device == "cuda" and target != "cuda":
            raise compute.ComputeUnavailableError(f"Kokoro 请求 CUDA，探针失败：{probe_reason}")
        import torch
        kmodel = KModel(...).to(torch.device(target)).eval()
        if self._device == "auto" and target == "cpu" and probe_reason:
            self._fallback_reason = probe_reason
        self._actual_device = target
        self._loaded = True
```

- worker 路径在 `_synthesize_worker` 首次请求前读 hello：`self._hello = worker.ready`（`spawn_venv_worker` 是否返回已 start 的 worker？它内部 start 并保留 ready；确认后直接用 `worker.ready`；若为 None 则调用 `worker.start()` 前不重复）。`compute()` 优先用 `_hello`，否则用进程内 `_actual_device`。

- [ ] **Step 4: 跑测试确认通过**

Run: `../.venv/Scripts/python.exe -m pytest tests/engines/tts/test_kokoro_device.py tests/engines/tts/test_worker_hello.py -v`
Expected: 全绿

Run: `../.venv/Scripts/python.exe -m pytest tests/engines/tts -q`
Expected: 全绿（旧的原生构造测试若因签名变化失败，按新签名更新）。

---

### Task 6: TTS 自检、试听缓存与方案回执

**Files:**
- Modify: `service/dramaclip/infra/model_manager/selftest.py`
- Modify: `service/dramaclip/api/engines.py`
- Modify: `service/dramaclip/api/tts.py`
- Modify: `service/dramaclip/engines/narration/models.py`
- Modify: `service/dramaclip/engines/narration/synthesis.py`
- Modify: `service/dramaclip/engines/narration/pipeline.py`
- Test: `service/tests/api/test_tts_preview_compute.py` (new)
- Test: `service/tests/engines/narration/test_plan_compute.py` (new)

**Interfaces:**
- `selftest.run_tts(models_dir, work_dir, spec, voice, *, device="auto")`；结果含 `compute`
- `api/tts.preview` 返回 `compute`
- 试听缓存 key：`preview-{engine}-{sha1(engine|voice|text|device|model)[:12]}.{ext}`；sidecar `{audio_path}.compute.json`
- `PlanData.compute: list[ComputeReport] = Field(default_factory=list)`
- `_EnginePool(setting, models_dir, log, api_key="", model="", device="auto")`
- `_EnginePool.compute_reports() -> list[ComputeReport]`

- [ ] **Step 1: 写失败测试**

`test_tts_preview_compute.py`：

```python
"""试听：显式 cuda 实际 cpu 判红；缓存 key 含设备；sidecar 不参与命中。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra import compute
from dramaclip.infra.model_manager import selftest


class _Engine:
    def __init__(self, report: compute.ComputeReport) -> None:
        self._report = report
        self.capabilities = lambda: type("Caps", (), {"supports_cloning": False})()

    def synthesize(self, _text: str, _voice: str, out: Path) -> Path:
        out.write_bytes(b"RIFF....WAVE")
        return out

    def compute(self) -> compute.ComputeReport:
        return self._report


def test_run_tts_explicit_cuda_actual_cpu_is_red(monkeypatch, tmp_path: Path) -> None:
    report = compute.ComputeReport(
        component="tts.kokoro", requested="cuda", resolved="cuda", actual="cpu",
    )
    engine = _Engine(report)
    monkeypatch.setattr("dramaclip.engines.tts.factory.create", lambda *_a, **_k: engine)
    monkeypatch.setattr(selftest, "audio_duration_s", lambda _p: 1.0)
    result = selftest.run_tts(tmp_path, tmp_path, type("Spec", (), {"engine": "kokoro"})(), "v", device="cuda")
    assert result["ok"] is False


def test_preview_key_changes_with_device() -> None:
    from dramaclip.api import tts as tts_api
    assert tts_api._content_key("kokoro", "zf_001", "你好", "cpu", "") != tts_api._content_key(
        "kokoro", "zf_001", "你好", "cuda", ""
    )
```

`test_plan_compute.py`：

```python
"""方案配音：只汇总真实推理过的段；全缓存时 compute 为空。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.engines.narration import synthesis
from dramaclip.infra import compute


class _Engine:
    name = "kokoro"

    def __init__(self) -> None:
        self.report = compute.ComputeReport(
            component="tts.kokoro", requested="cpu", resolved="cpu", actual="cpu",
        )

    def capabilities(self):  # type: ignore[no-untyped-def]
        return type("Caps", (), {"supports_cloning": False})()

    def synthesize(self, _text: str, _voice: str, out: Path) -> Path:
        out.write_bytes(b"RIFF")
        return out

    def compute(self):  # type: ignore[no-untyped-def]
        return self.report


def test_pool_collects_only_real_inference(monkeypatch, tmp_path: Path) -> None:
    engine = _Engine()
    pool = synthesis._EnginePool("kokoro", tmp_path, None, device="cpu")
    monkeypatch.setattr(pool, "_instances", {"kokoro": engine})
    target = tmp_path / "a.wav"
    target.write_bytes(b"RIFF")
    # 手工走一次真实合成路径所需的最小桩：缓存目录空 = 真合成
    path = pool.synthesize_item("s1", "你好", "", "", tmp_path, tmp_path / "cache")
    assert path.exists()
    reports = pool.compute_reports()
    assert [r.component for r in reports] == ["tts.kokoro"]
```

（若 `_synthesize_into` 的 ffprobe/格式要求使桩难跑，改为直接调用 `pool._remember(engine)` 并断言去重；实现里提供该私有方法，测试随实现收敛。）

- [ ] **Step 2: 跑测试确认失败**

Run: `../.venv/Scripts/python.exe -m pytest tests/api/test_tts_preview_compute.py tests/engines/narration/test_plan_compute.py -v`
Expected: `run_tts` 无 device、`_content_key` 参数不符、`compute_reports` 不存在。

- [ ] **Step 3: 实现**

`selftest.run_tts`：

- 签名加 `*, device: str = "auto"`。
- `engine = factory.create(spec.engine, models_dir, device=device)`。
- 成功后：

```python
    report = engine.compute() if hasattr(engine, "compute") else None
    if report is not None:
        try:
            compute.assert_success(report)
        except compute.ComputeUnavailableError as exc:
            return {**_fail(str(exc)), "compute": report.to_dict()}
    return {
        "ok": True, ..., "compute": None if report is None else report.to_dict(),
    }
```

`api/engines._tts`：`device = str(context.settings.get("tts.device") or "auto")`，传给 `run_tts`。

`api/tts.py`：

- `_content_key(engine, voice, text, device, model)` 的哈希串加 `|{device}|{model}`。
- `preview` 读取 `device = str(context.settings.get("tts.device") or "auto")`、`model` 同 `_preview_audio` 当前取值；`_resolve_voice(..., device?)` 不需要 device。
- `_preview_audio` 返回 `(Path, ComputeReport | None)`：

```python
    cached = _find_cached(root, key)
    if cached is not None:
        return cached, _cached_compute(cached)
    ...
    path, report = _synthesize(...)
    _write_compute_sidecar(path, report)
    return path, report
```

- `_find_cached` 只接受音频：

```python
_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a"})
...
    hits = sorted(
        path for path in root.glob(f"{key}.*")
        if path.suffix.lower() in _AUDIO_SUFFIXES and _has_audio(path)
    )
```

- `_synthesize` 返回 `(Path, ComputeReport | None)`：`engine = create_tts(engine, models_dir, api_key=..., model=..., device=device)`；合成后 `report = engine.compute()`；写 sidecar `path.with_name(path.name + ".compute.json")`（`json.dumps(report.to_dict())`）。
- `_cached_compute` 读 sidecar；坏文件/缺失返回 `None`；命中时 `replace(report, reason="缓存命中")`（`dataclasses.replace`）。注意 `replace` 后 `fallback` 不变量仍成立。
- `preview` 返回体加 `"compute": report.to_dict() if report is not None else None`。
- 若 `_synthesize` 有旧调用点（测试），同步改。

`models.py` PlanData 加：

```python
from dramaclip.infra.compute import ComputeReport
...
    compute: list[ComputeReport] = Field(default_factory=list)
```

`narration/synthesis.py`：

- `_EnginePool.__init__` 加 `device: str = "auto"`，保存 `self._device`；所有 `create_tts(..., device=self._device)`。
- `self._reports: dict[str, ComputeReport] = {}`；`_remember(engine)`：

```python
    def _remember(self, engine: tts_base.TtsEngine) -> None:
        report = engine.compute() if hasattr(engine, "compute") else None
        if report is not None:
            self._reports[report.component] = report

    def compute_reports(self) -> list[ComputeReport]:
        return list(self._reports.values())
```

- `_synthesize_into` 返回值改为 `bool`（True=真推理，False=缓存命中）。在缓存命中分支 `return False`，在 `engine.synthesize` 成功后 `return True`。`synthesize_item` 成功后 `if synthesized: self._remember(engine)`。
- 方案的 `_synthesize_into` 旧断言（测试里）同步更新。

`narration/pipeline.py`：`_EnginePool(..., device=settings.get("tts.device","auto"))`；`laid = PlanData.model_validate({..., "compute": [r.model_dump() for r in pool.compute_reports()]})`（`model_validate` 接受 dict；`model_dump` 后是 dict 列表）。

- [ ] **Step 4: 跑测试确认通过**

Run: `../.venv/Scripts/python.exe -m pytest tests/api/test_tts_preview_compute.py tests/engines/narration/test_plan_compute.py -v`
Run: `../.venv/Scripts/python.exe -m pytest tests/api tests/engines/tts tests/engines/narration -q`
Expected: 全绿

---

### Task 7: AI 标注折叠进段滤镜 + 导出回执

**Files:**
- Modify: `service/dramaclip/engines/exporter/ai_label.py`
- Modify: `service/dramaclip/engines/exporter/encoder.py`
- Modify: `service/dramaclip/api/export.py`
- Test: `service/tests/engines/exporter/test_ai_label.py`
- Test: `service/tests/engines/exporter/test_export_compute.py` (new)

**Interfaces:**
- `ai_label.prepare(work_dir: Path, out_size: tuple[int, int]) -> AiLabelSpec`
  - `AiLabelSpec.vf: str`、`.fingerprint: str`、`.textfile: Path`
  - 字体缺失抛 `AiLabelError`；textfile 固定在 `work_dir / ".ai-label.txt"`（无临时文件泄漏）
- 删除 `ai_label.apply`
- `encoder.cut_segment_args(..., ai_label_vf: str | None = None)`
- `encoder.export_plan(..., compute_sink: Callable[[ComputeReport], None] | None = None, encoder_requested: str = "") -> Path`
- `_export_plan_once(..., ai_label_vf: str | None = None, _report_state: dict[str, Any] | None = None)`

- [ ] **Step 1: 重写 AI 标注测试**

删除 `test_apply_*` 三条，改为：

```python
def test_prepare_writes_textfile_and_fingerprint(monkeypatch, tmp_path: Path) -> None:
    _stub_font(monkeypatch, tmp_path)
    spec = ai_label.prepare(tmp_path / "work", (1080, 1920))
    assert spec.textfile.read_text(encoding="utf-8") == ai_label.LABEL_TEXT
    assert spec.vf.startswith("drawtext=")
    assert len(spec.fingerprint) == 64
    assert "textfile" not in spec.fingerprint  # 临时路径不进签名


def test_prepare_without_font_raises(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ai_label.ffmpeg_cover, "bundled_font_face", lambda: None)
    with pytest.raises(ai_label.AiLabelError, match="字体"):
        ai_label.prepare(tmp_path, (1080, 1920))


def test_ai_label_is_a_segment_filter_not_a_post_pass() -> None:
    assert not hasattr(ai_label, "apply"), "整片后处理必须删除"
    args = encoder.cut_segment_args(
        "src.mp4", "out.mp4", start=0, end=1, audio="original", tts_audio=None,
        rng=random.Random(7), ai_label_vf="drawtext=textfile=x",
    )
    vf = args[args.index("-vf") + 1]
    assert "drawtext=textfile=x" in vf
```

新增 `service/tests/engines/exporter/test_export_compute.py`：

```python
"""导出回执：硬编失败统一重跑后 actual=libx264、fallback=true、reason 非空。"""

from __future__ import annotations

import pytest

from dramaclip.engines.exporter import encoder
from dramaclip.infra import compute


def test_uniform_retry_reports_fallback(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    reports: list[compute.ComputeReport] = []

    def fake_once(_plan, _paths, out, _work, *, video_codec="libx264", _allow_uniform_retry=True, **_kw):
        calls.append(video_codec)
        if _allow_uniform_retry:
            raise encoder._UniformCodecRetry()
        out.write_bytes(b"film")
        return out

    monkeypatch.setattr(encoder, "_export_plan_once", fake_once)
    path = encoder.export_plan(
        type("Plan", (), {"timeline": [object()], "mode": "intro"})(), {},
        tmp_path / "out.mp4", tmp_path, video_codec="h264_nvenc",
        compute_sink=reports.append, encoder_requested="auto",
    )
    assert path.is_file()
    assert calls == ["h264_nvenc", "libx264"]
    report = reports[0]
    assert (report.requested, report.actual, report.fallback) == ("auto", "libx264", True)
    assert report.reason
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../.venv/Scripts/python.exe -m pytest tests/engines/exporter/test_ai_label.py tests/engines/exporter/test_export_compute.py -v`
Expected: `prepare` 不存在、`apply` 仍在、`export_plan` 无 `compute_sink`。

- [ ] **Step 3: 实现**

`ai_label.py`：

- 删除 `apply` 与 `_TIMEOUT_S`、`runner` 导入；保留 `enabled`、`label_vf`。
- 新增：

```python
@dataclass(frozen=True)
class AiLabelSpec:
    vf: str
    fingerprint: str
    textfile: Path


def prepare(work_dir: Path, out_size: tuple[int, int]) -> AiLabelSpec:
    face = ffmpeg_cover.bundled_font_face()
    if face is None:
        raise AiLabelError("随包字体不可用，无法烧制 AI 生成标注")
    work_dir.mkdir(parents=True, exist_ok=True)
    textfile = work_dir / ".ai-label.txt"
    textfile.write_text(LABEL_TEXT, encoding="utf-8")
    vf = label_vf(face, textfile, out_size)
    payload = [
        LABEL_TEXT, vf,
        hashlib.sha256(face.read_bytes()).hexdigest(),
    ]
    fingerprint = hashlib.sha256("\0".join(payload).encode("utf-8")).hexdigest()
    return AiLabelSpec(vf=vf, fingerprint=fingerprint, textfile=textfile)
```

（`label_vf` 已含字号/边距；字体内容 hash 覆盖字体替换。`textfile` 路径不进指纹。）

`encoder.cut_segment_args`：参数加 `ai_label_vf: str | None = None`；在 ASS 之后：

```python
    if ai_label_vf:
        filters.append(ai_label_vf)
```

`_export_plan_once`：

- 参数加 `ai_label_vf: str | None = None`、`_report_state: dict[str, Any] | None = None`。
- 段构建 `cut_segment_args(..., ai_label_vf=ai_label_vf)`。
- `inputs` 仅在 `ai_label_vf` 非空时加 `"ai_label": ai_label_vf`（需要指纹而非路径；把 `ai_label_vf` 参数改成 `ai_label_spec: AiLabelSpec | None` 更稳：内部用 `spec.vf`，签名用 `spec.fingerprint`）。**采用 `ai_label_spec`**，`cut_segment_args` 仍只收 `ai_label_vf` 字符串。
- `_report_state` 在 `_retry_with_libx264` 里写 `fallback=True`、`reason`（首个失败原因 + 次数）。
- 删除末尾 `if burn_ai_label: ai_label.apply(...)` 与进度点。
- 返回前不生成回执（由 `export_plan` 生成）。

`export_plan`：

```python
def export_plan(..., burn_ai_label: bool = False,
                compute_sink: Callable[[compute.ComputeReport], None] | None = None,
                encoder_requested: str = "") -> Path:
    label_spec = ai_label.prepare(work_dir, out_size) if burn_ai_label else None
    state: dict[str, Any] = {"fallback": False, "reason": "", "resolved": video_codec}
    try:
        path = _export_plan_once(..., ai_label_spec=label_spec, _report_state=state)
        actual = video_codec
    except _UniformCodecRetry:
        state.update(fallback=True,
                     reason=state.get("reason") or "段级硬编失败，整片统一 libx264 重跑")
        path = _export_plan_once(..., video_codec=_FALLBACK_CODEC,
                                 ai_label_spec=label_spec, _report_state=state,
                                 _allow_uniform_retry=False)
        actual = _FALLBACK_CODEC
    report = compute.ComputeReport(
        component="video.encode",
        requested=encoder_requested or video_codec,
        resolved=state["resolved"],
        actual=actual,
        fallback=bool(state["fallback"]),
        reason=str(state["reason"]),
    )
    if compute_sink is not None:
        compute_sink(report)
    return path
```

注意 `resolved` 在第一次尝试时即定为选中的 codec；统一重跑不改 resolved。

`api/export.py`：

- 在 `encoder.export_plan(...)` 之前收集 `reports: list[ComputeReport] = []`，传 `compute_sink=reports.append`、`encoder_requested=codec_setting`。
- `export_plan` 返回后：`exports_repo.set_compute(context.conn, export_id, [r.to_dict() for r in reports])`；同函数的作业 `job_id`（若在作用域内）`context.job_store.set_compute(job_id, ...)`。若此处只有 export_id，则在导出作业完成处（`_run_export` 的 caller）补 `jobs.compute`；具体：本函数签名内的 `job_id` 由上游传入，直接写。先读 `def _run_export` 的签名再落笔，保持单一写方。
- `export.encoder` 帮助文案改：
  `'自动=按平台真试编选择硬编（NVENC / QSV / VideoToolbox），全部不可用才 libx264；选固定编码器时不探测'`

- [ ] **Step 4: 跑测试确认通过**

Run: `../.venv/Scripts/python.exe -m pytest tests/engines/exporter/test_ai_label.py tests/engines/exporter/test_export_compute.py -v`
Run: `../.venv/Scripts/python.exe -m pytest tests/engines/exporter -q`
Expected: 全绿（旧断言 `ai_label.apply` 存在的测试同批改掉）。

---

### Task 8: 界面可见性（运行态 ≠ 安装态）

**Files:**
- Modify: `desktop/src/features/engines/AsrTab.tsx`
- Modify: `desktop/src/features/engines/TtsTab.tsx`
- Modify: `desktop/src/features/engines/AssetRow.tsx`
- Modify: `desktop/src/features/engines/assetState.ts`
- Modify: `desktop/src/features/jobs/JobRow.tsx`
- Modify: `desktop/src/features/narration/ExportsCard.tsx`
- Modify: `desktop/src/features/settings/sections.ts`
- Modify: `desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx`
- Modify: `service/dramaclip/infra/device_profile.py`
- Test: `desktop/src/features/engines/__tests__/computeLabel.test.ts` (new)
- Test: `desktop/src/features/engines/__tests__/MachinePanelEnv.test.tsx`（现有）

**Interfaces:**
- `assetState.computeLabel(report?: ComputeReport | null): string | undefined`
  - `undefined` = 没有回执，不显示
  - `本次实际：GPU（cuda:0）` / `本次实际：CPU`
  - `fallback=true` → `已回退 CPU：<reason>`
  - `resolved="unsupported"`（若有）→ `此卡不支持（<reason>）`
  - 视频：`编码：h264_nvenc` / `已回退 libx264：<reason>`
- TtsTab `PARAMS` 复用 AsrTab 的设备三档，新增 `tts.device` 行。
- `device_profile.indextts2_gpu.hint` / `vocal_separation_gpu.hint` 改为“安装后由运行时回执确认”，`ready` 语义不冒充运行态。

- [ ] **Step 1: 写失败测试**

`computeLabel.test.ts`：

```ts
import { describe, expect, it } from 'vitest';
import type { ComputeReport } from '@dramaclip/protocol';
import { computeLabel } from '../assetState';

const base: ComputeReport = {
  component: 'asr.whisper', requested: 'auto', resolved: 'cuda',
  actual: 'cpu', fallback: true, reason: 'cublas 缺失', device: 'cpu',
};

describe('computeLabel', () => {
  it('回退要带原因', () => {
    expect(computeLabel(base)).toBe('已回退 CPU：cublas 缺失');
  });
  it('显式 GPU 显示实际设备', () => {
    expect(computeLabel({ ...base, requested: 'cuda', resolved: 'cuda', actual: 'cuda',
      fallback: false, reason: '', device: 'cuda:0' })).toBe('本次实际：GPU（cuda:0）');
  });
  it('没有回执不编造', () => {
    expect(computeLabel(undefined)).toBeUndefined();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd desktop && npx vitest run src/features/engines/__tests__/computeLabel.test.ts`
Expected: `computeLabel` 未导出。

- [ ] **Step 3: 实现**

`assetState.ts` 加：

```ts
export function computeLabel(report?: ComputeReport | null): string | undefined {
  if (report === undefined || report === null) return undefined;
  if (report.component === 'video.encode') {
    return report.fallback
      ? `已回退 ${report.actual}：${report.reason}`
      : `编码：${report.actual}`;
  }
  if (report.fallback) return `已回退 CPU：${report.reason}`;
  if (report.resolved === 'unsupported') return `此卡不支持（${report.reason}）`;
  if (report.actual === 'cuda') return `本次实际：GPU（${report.device}）`;
  if (report.actual === 'cpu') return '本次实际：CPU';
  if (report.actual === 'cloud') return '本次实际：云端';
  return undefined; // unknown 不点绿、不编造
}
```

- `AssetRow`：在自检摘要行（`selftest` 存在时）追加 `computeLabel(selftest.compute)`，回退用警示色（现有 token `colorWarning`）。不加新接口。
- `JobRow`：`JobMetaLine` 的 parts 里对终态任务追加 `job.compute?.map(computeLabel).filter(Boolean).join(' · ')`（只显示有回执的）。import `computeLabel`。
- `ExportsCard.ExportRow`：`job.compute` 第一条的 `computeLabel` 放 `duration_s` 左侧（小字、警示色仅回退时）。import `computeLabel`。
- `AsrTab` 设备选项文案不变；footnote 改：
  `'「自动」＝能力与运行时都通过才用 GPU，失败会回退并在任务回执里写明原因；「CUDA」是承诺，失败即报错不静默换 CPU。'`
- `TtsTab`：新增 `TTS_PARAMS`（与 AsrTab 同三档）并在 `ActiveCard.props` 加 `{ label: '运行设备', value: <SettingSelect value={settings['tts.device'] ?? ''} .../> }`；云端卡不显示该行。
- `sections.ts`：`export.encoder.help` 改文案（见 Task 7）；`tts.device` 不放进全局设置分区（它属于引擎页配音卡，避免两个真相源）。
- `MachinePanelEnv.test.tsx`：fixture 的 `demucs_gpu` 改成 `vocal_separation_gpu`，hint 改成 `'当前走 CPU（MDX-Net）；安装态不等于运行态，实际以后端回执为准'`。
- `device_profile.py` 两处 hint 改：
  - `indextts2_gpu`: `"安装后由运行时回执确认实际设备（安装态不等于已启用 GPU）"`
  - `vocal_separation_gpu`: `"当前走 CPU（MDX-Net）；P2 接线后由运行时回执确认 GPU"`

- [ ] **Step 4: 跑测试与类型检查**

Run: `cd desktop && npx vitest run src/features/engines/__tests__/computeLabel.test.ts src/features/engines/__tests__/MachinePanelEnv.test.tsx`
Run: `cd desktop && npx tsc --noEmit`
Expected: 全绿

---

### Task 9: 收口验证

**Files:**
- Modify: `docs/superpowers/specs/2026-10-20-gpu-coverage-design.md`（只补“实现状态”段，不改设计结论）
- Test: 全量

- [ ] **Step 1: 后端全量**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest`
Expected: 0 failed；记录实际 passed 数，不以“只跑新增测试”代替。

- [ ] **Step 2: Lint**

Run: `cd service && ../.venv/Scripts/python.exe -m ruff check dramaclip tests`
Expected: 0 error；若历史残留错误与本次无关，列出文件与规则，不顺手大改。

- [ ] **Step 3: 前端全量**

Run: `cd desktop && npx tsc --noEmit && npx vitest run`
Expected: 全绿。

- [ ] **Step 4: 本机真跑（CPU 线）**

按 spec §6 逐项：
1. `asr.device=cpu` 用 `resources/selftest/sample_zh.wav` 真转写 faster-whisper；
2. `asr.device=cpu` 真转写 SenseVoice（service/.venv 已装 funasr）；
3. Kokoro `tts.device=cpu` 真合成 `SELFTEST_TEXT`；
4. 选一个人声参考（应用已装模型/素材）跑 `audio-separator` CPU 分离（P2 前保持现状，只验 CPU 可用）；
5. `export.encoder=libx264` 导出一条含 AI 标注的短片，抽帧确认右上角“AI 生成”在位，且日志无第二遍 libx264 后处理。

把每项的命令、产物路径、实测设备/耗时写进 `docs/superpowers/specs/2026-10-20-gpu-coverage-design.md` 的“实现状态”段（不含用户素材路径）。

- [ ] **Step 5: 本机 GPU 可验项**

1. dev funasr（`service/.venv`，torch cu126）真转写 `sample_zh.wav`，报告 `actual=cuda`；
2. `export.encoder=auto` 真导出，记录 `pick_hw_encoder()` 结果与 `video.encode.actual`；
3. whisper GPU：预期 `unsupported`（sm_52 vs CT2 sm_61），不得写成通过；
4. IndexTTS/CosyVoice/Kokoro GPU：预期 `unsupported`（torch 2.8 cu128 需 sm_70）；
5. 人声分离 GPU：P1 不在范围，保持 CPU 回执。

- [ ] **Step 6: 更新规格实现状态**

在 spec 末尾追加：

```markdown
## 10. 实现状态（2026-10-20 P1）

| 项 | 状态 | 证据 |
|---|---|---|
| compute 契约 | 已实现 | tests/infra/test_compute_contract.py |
| ASR 回执/显式 cuda | 已实现 | test_gpu_and_fallback.py、selftest compute |
| TTS hello/Kokoro | 已实现 | test_kokoro_device.py、test_worker_hello.py |
| 试听/方案回执 | 已实现 | test_tts_preview_compute.py、test_plan_compute.py |
| AI 标注段滤镜 | 已实现 | test_ai_label.py、test_export_compute.py |
| UI 运行态展示 | 已实现 | computeLabel.test.ts、MachinePanelEnv.test.tsx |
| 本机 whisper/TTS GPU | unsupported | 硬件边界（见 §0.2） |
```

不修改 `docs/05-开发路线图.md`。

---

## Self-Review

- **Spec coverage:** §1 契约/落库/协议 → Tasks 1–3；§2 ASR → Task 4；§3 TTS → Tasks 5–6；§4 视频 → Task 7；§1.4/§3.4 UI → Task 8；§6 CPU 线路/§7 验收 → Task 9。
- **Type consistency:** `ComputeReport` 字段在 Python/TS/schema 三处同名同序；`compute_sink` 只接收 `ComputeReport`；`PlanData.compute` 为 list；自检 `compute` 为单条。
- **No placeholders:** 每个任务给出了失败测试、预期失败、实现代码与验收命令；唯一执行期待确认项是 `api/export.py` 内 `job_id` 作用域，实施时以实际函数签名为准（单一写方，不新造接口）。
- **Commit:** 本计划不含 commit 步骤，用户未要求提交。
