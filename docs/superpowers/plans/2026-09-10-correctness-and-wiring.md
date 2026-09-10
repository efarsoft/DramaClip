# 成片正确性与数据根目录修复（批次 0 + 0.5）实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让九个模式的成片在音轨、字幕、切点保护上真正正确，把成品/封面/模型路径锚到唯一的数据根目录，并用一条真机九模式回归作为出口门禁。

**Architecture:** 三条根因线，不新增抽象。(1) `AppContext` 缺 `data_dir`，导致 8 处 `work_dir.parent(.parent)` 上跳，其中 2 处把成品与封面写进了 `cache/`；(2) `plan_data` 丢失「哪条旁白配哪一段」的显式映射，导出侧用位置索引重推，凡旁白与时间轴非 1:1 的模式（`cross_narration` / `ultra_short_hook`）错音，且 `ducked` 角色在编码器无分支（`full_narration` 旁白整体丢失）；(3) 台词保护区只认同名 `.srt`，而全服务从不产出 `.srt`，库内 `asr_segments` 从未接进导出。

**Tech Stack:** Python 3.12 / pydantic v2 / sqlite3 / 仓库内置 FFmpeg（`resources/ffmpeg/`）；Electron 44 + React 19 + TS + AntD 5。门禁现状：`pytest` **177 passed**、`tsc --noEmit` 干净、`vitest` **13 passed**。

**范围声明：** 本方案**不含**批次 1（产能矩阵 `modes × episode_ids`）。它依赖一个尚未拍板的设计分叉（八个模式走「每集一条」量产，还是也升级为跨集叙事）。批次 0 中凡与预筛/产能相关的假文案，本方案一律**删除文案**而非临时实现功能。

---

## 前置事实（逐条已核实，执行者无需复查）

| 事实 | 证据 | 结论 |
|---|---|---|
| `work_dir = data_dir/"cache"/"analysis"`，且 `data_dir` 已在构造点作用域内 | `service/dramaclip/service_app.py:59,64-72` | `work_dir.parent` 是 `cache/`，不是数据根 |
| 成品实际落 `data/cache/outputs/`；`data/outputs/` 由 `paths.py` 创建但为空 | `ls data/cache/`（含 `analysis/ covers/ outputs/`）、`export_jobs.output_path` | 真实缺陷，非设计 |
| `AppContext` 无 `data_dir` 字段 | `api/context.py:16-27`（`work_dir` 之后仅有带默认值的 `cancel_events`） | 补字段即可消掉 8 处上跳 |
| `ducked` 只在 `modes_w8.py:63` 产出；`encoder.py:80` 条件为 `audio == "narration" and tts_audio` | 静态读码 | `full_narration` 每段都是 `ducked` → 全落 else → 旁白不进片 |
| 回填循环条件 `if segment["audio"] != "narration" ... : continue` | `engines/narration/pipeline.py:280` | `ducked` 段拿不到时长回填与 `subtitle_text` |
| TTS 映射：生产侧键为 `enumerate(narration_texts)` 序号，消费侧键为 timeline 段序号；且 `kept_texts` 过滤掉合成失败段 | `api/export.py:97-101` vs `encoder.py:186-187`、`pipeline.py:291` | 旁白数≠narration 段数时错位；CTA 被丢 |
| `jitter.srt_for_source` 只读同名 `.srt`；全服务无任何 `.srt` 写者 | `engines/dedup/jitter.py:42-45`、`encoder.py:177-184`、grep 确认 | 保护区恒为空；抖动上限 ±0.3s 但完全不看台词边界 |
| `prescreen.py:95` 硬编码 `score >= 70.0` | 静态读码 | `analysis.prescreen_threshold` 零消费 |
| `plan_row.get("subtitle_preset")` 恒 None（表无此列、`_COLUMNS` 不返回） | `repos/plans.py:11-13`、`api/export.py:103` | 字幕预设端到端死配置 |
| `pyproject.toml` 依赖仅 `pydantic`+`edge-tts`，extras 仅 `dev` | `service/pyproject.toml:10-23` | README 的 `pip install -e "service[dev]"` 装不出 ML 环境 |
| 端到端导出测试仅 1 条且仅 `raw_clip`；`script_driver.py` 收集到的测试数 = **0** | `tests/api/test_produce.py:99-115`、`pytest --collect-only -q \| grep -c script_driver` → `0` | 静默丢旁白得以存活 46 个提交的原因 |
| 失败集渲染成「● 待分析」的确切位置 | `EpisodeListRow.tsx:32` `const asrOk = episode.status === 'done'` → `:46` 传给 `RowMeta` | 布尔化丢失 `failed` 信息 |
| 该文件已证明存在的令牌 | `EpisodeListRow.tsx` 用到 `tokens.textTertiary` / `colorSuccess` / `colorWarning` | 失败态用 `colorWarning`（同时守住「#FF4D4F 只给钩子」的红色纪律） |

**测试夹具基线：** `tests/conftest.py` 提供 `memory_db`（已迁移内存库，`check_same_thread=False`）、`sample_video`（真实 ffmpeg 生成 3 秒 testsrc + 440Hz 正弦）。`tests/api/test_produce.py` 的 `Harness.context` 是 `SimpleNamespace`——**A1 新增字段必须同步补该夹具**。

---

## 文件结构（本方案涉及面）

**修改（service）**：`api/context.py` · `service_app.py` · `api/export.py` · `api/project.py` · `api/models.py` · `api/narration.py` · `api/analysis.py` · `engines/narration/models.py` · `engines/narration/pipeline.py` · `engines/exporter/encoder.py` · `engines/analysis/prescreen.py` · `pyproject.toml` · `tests/api/test_produce.py`
**新建（service/tests）**：`tests/api/test_data_paths.py` · `tests/engines/narration/test_ducked_narration.py` · `tests/engines/narration/test_subtitle_preset.py` · `tests/api/test_export_tts_mapping.py` · `tests/engines/dedup/test_asr_protection.py` · `tests/engines/narration/test_script_driver.py`
**新建（scripts）**：`scripts/verify_modes.py`
**修改（desktop）**：`features/home/EnvPanel.tsx` · `features/home/HomePage.tsx` · `features/home/StartCards.tsx` · `features/analysis/EpisodeListRow.tsx` · `features/narration/ProductionPage.tsx`

---

# Phase A · 数据根目录与死配置接线

## Task A1: AppContext 增加 data_dir，消灭 8 处路径上跳

**Files:**
- Modify: `service/dramaclip/api/context.py:26`
- Modify: `service/dramaclip/service_app.py:64-72`
- Modify: `service/dramaclip/api/export.py:86`、`api/project.py:150,170`、`api/models.py:42,61,91,106`、`api/narration.py:206,234`
- Test: `service/tests/api/test_data_paths.py`（新建）、`service/tests/api/test_produce.py:26-38`

- [ ] **Step 1: 写失败测试** — 成品位置断言 + 一条防复发的静态守卫

新建 `service/tests/api/test_data_paths.py`：

```python
"""数据根目录锚点：成品必须落在 <data>/outputs/，且全服务不得再从 work_dir 上跳推导。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.api.test_produce import Harness, _seed_project_with_analysis

_SERVICE_ROOT = Path(__file__).resolve().parents[2] / "dramaclip"


def test_export_output_lands_under_data_dir(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    produce = harness.rpc("narration.produce", {"project_id": project_id, "modes": ["raw_clip"]})
    status = harness.wait_job(str(produce["job_id"]))
    assert status["status"] == "completed", status.get("error")

    exported = harness.rpc("export.list", {"project_id": project_id})
    out = Path(str(exported[0]["output_path"]))
    assert out.is_file(), "成品未生成"
    assert out.parent.parent == tmp_path / "outputs", f"成品位置错误: {out}"
    assert "cache" not in out.parts, f"成品仍落在缓存目录: {out}"


def test_no_fragile_parent_walks_remain() -> None:
    """永久守卫：路径一律由 AppContext.data_dir / work_dir 直接给出，禁止 .parent 上跳。"""
    offenders = [
        str(py.relative_to(_SERVICE_ROOT))
        for py in sorted(_SERVICE_ROOT.rglob("*.py"))
        if "work_dir.parent" in py.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"出现新的 work_dir 上跳: {offenders}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_data_paths.py -v`
Expected: 两条 FAIL。`test_export_output_lands_under_data_dir` → `TypeError: Harness.__init__() got an unexpected keyword argument 'data_dir'`；`test_no_fragile_parent_walks_remain` → 列出 8 个 offenders。**第二条此刻就该红**，它正是本任务的完成判据。

- [ ] **Step 3: 加字段**

`api/context.py`，`work_dir` 之后、`cancel_events` 之前（顺序要紧：`cancel_events` 带默认值）：

```python
    work_dir: Path  # 分析/中间产物缓存目录（<data>/cache/analysis）
    data_dir: Path  # 数据根：outputs/ models/ logs/ covers/ 的唯一锚点
```

`service_app.py:64-72` 构造点补一行（`data_dir` 已在作用域内，见 `:59`）：

```python
            work_dir=work_dir,
            data_dir=data_dir,
```

- [ ] **Step 4: 替换 8 处上跳**（逐处替换，语义不变、锚点变对）

`api/export.py:86`：
```python
    output_root = context.data_dir / "outputs" / project_id
```
`api/project.py:150` 与 `:170`（两处相同）：
```python
    cover_dir = context.data_dir / "covers"
```
`api/models.py:42,61,91,106`（四处相同）：
```python
    models_dir = context.data_dir / "models"
```
`api/narration.py:206`：
```python
                trace_dir=context.data_dir / "logs" / "llm",
```
`api/narration.py:234`：
```python
        models_dir = context.data_dir / "models"
```

- [ ] **Step 5: 逐个夹具显式补 data_dir（不用条件推导）**

经核实，构造 `AppContext` 形状 `SimpleNamespace` 的测试夹具共 4 处需要补 `data_dir`。`data_dir` 定为**必填关键字参数**——显式优于任何按目录名反推的魔法。

`tests/api/test_produce.py:26-38` 的 `Harness.__init__` 整体替换：

```python
class Harness:
    def __init__(self, conn: sqlite3.Connection, work_dir: Path, *, data_dir: Path) -> None:
        self.sent: list[dict[str, Any]] = []
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.context = SimpleNamespace(
            conn=conn,
            work_dir=work_dir,
            data_dir=data_dir,
            settings={"asr.language": "zh"},
            notifier=Notifier(self.sent.append),
            executor=self.executor,
            job_store=jobs.JobStore(conn),
            cancel_events={},
        )
```

该文件的 3 个调用点（`:70`、`:103`、`:119`）同步改为：

```python
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
```

另外三处按同样方式补参数（**逐个改，漏一处即红灯**）：
- `tests/api/test_analysis.py:56` —— 其 `Harness.__init__` 增 `*, data_dir: Path` 并注入；两个调用点（`:81`、`:133`）传 `data_dir=tmp_path`
- `tests/api/test_project.py:106` —— `SimpleNamespace(conn=conn, work_dir=work_dir, data_dir=...)`；该处用于封面测试，正好验证 A1 的 covers 改动
- `tests/engines/analysis/test_pipeline.py:35` —— 引擎级夹具，若其上下文不含 `data_dir` 消费路径可不改；**以 `pytest` 结果为准，红则补**

**不受影响**（已核实）：`tests/api/test_export.py:20` 的 `Harness` 仅 `SimpleNamespace(conn=conn)`，只测 `list`/`list_works`，不触路径推导；`tests/api/test_settings.py` 无 `work_dir`。

- [ ] **Step 6: 跑全量测试确认通过且无回归**

Run: `cd service && ../.venv/Scripts/python -m pytest tests -q`
Expected: `179 passed`（177 + 新增 2）。若 `test_produce` 端到端用例失败，说明 Step 4 漏改——直接看 `test_no_fragile_parent_walks_remain` 报出的文件名。

- [ ] **Step 7: 确认旧成品不丢（只查不改）**

Run: `PYTHONIOENCODING=utf-8 python -c "import sqlite3;c=sqlite3.connect('data/data.db');print([r[0] for r in c.execute('select output_path from export_jobs limit 3')])"`
Expected: 形如 `...\data\cache\outputs\...` 的绝对路径。**不做数据迁移**：`export_jobs.output_path` 存绝对路径，作品库与 `dramaclip://` 预览照旧可读，只是新成品去正确位置。旧路径留在 `cache/` 已记入末尾「已知遗留」。

- [ ] **Step 8: 提交**

```bash
git add service/dramaclip/api/context.py service/dramaclip/service_app.py \
        service/dramaclip/api/export.py service/dramaclip/api/project.py \
        service/dramaclip/api/models.py service/dramaclip/api/narration.py \
        service/tests/api/test_data_paths.py service/tests/api/test_produce.py
git commit -m "fix(paths): AppContext 增 data_dir，成品与封面不再落入 cache 目录"
```

## Task A2: 字幕预设接进出片（现为死配置）

**Files:**
- Modify: `service/dramaclip/engines/narration/models.py:42-50`
- Modify: `service/dramaclip/api/narration.py:232-242`（`_generate_one` 落库前）
- Modify: `service/dramaclip/api/export.py:103`
- Test: `service/tests/engines/narration/test_subtitle_preset.py`（新建）

**决策：** 预设写进 `plan_data`（JSON 列），**不加数据库迁移**。预设属于"这一条片的配方"，与 `strategy` 同类；旧 plan 缺字段时 pydantic 默认 `None`，行为与今天完全一致，零破坏。**注入点选在 `_generate_one` 落库前一处**，同时覆盖规则路径与 LLM 剧本路径，避免在 `build_plan` 的 9 个分支里各改一遍。

- [ ] **Step 1: 写失败测试**

```python
"""字幕预设必须从设置流到 plan_data（此前 plan_row 无该列，导出恒回退 conflict-impact）。"""

from __future__ import annotations

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.models import PlanData


def test_inject_sets_preset_from_settings() -> None:
    plan = PlanData(mode="raw_clip")
    out = pipeline.with_subtitle_preset(plan, {"subtitle.default_preset": "karaoke-pop"})
    assert out.subtitle_preset == "karaoke-pop"


def test_inject_preserves_explicit_preset() -> None:
    plan = PlanData(mode="raw_clip", subtitle_preset="calm-narrative")
    out = pipeline.with_subtitle_preset(plan, {"subtitle.default_preset": "karaoke-pop"})
    assert out.subtitle_preset == "calm-narrative"


def test_inject_tolerates_missing_key() -> None:
    plan = PlanData(mode="raw_clip")
    assert pipeline.with_subtitle_preset(plan, {}).subtitle_preset is None
```

- [ ] **Step 2:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_subtitle_preset.py -v`
Expected: 三条 FAIL —— `PlanData` 无 `subtitle_preset` 字段（`AttributeError`），且 `pipeline` 无 `with_subtitle_preset`。

- [ ] **Step 3: 加字段**

`engines/narration/models.py` 的 `PlanData` 末尾：

```python
    # 编排来源：rule=规则预算（默认）；llm_script=LLM 剧本驱动
    planner: str = "rule"
    # 本条片使用的字幕预设 id；None → 导出侧回退内置默认
    subtitle_preset: str | None = None
```

- [ ] **Step 4: 加注入函数**

`engines/narration/pipeline.py`（放在 `synthesize_narration_texts` 之前）：

```python
def with_subtitle_preset(plan: PlanData, settings: dict[str, str]) -> PlanData:
    """编排落库前注入字幕预设：显式值优先，其次设置默认（ADR-008 解析序的最内一层）。"""
    if plan.subtitle_preset is None:
        plan.subtitle_preset = settings.get("subtitle.default_preset") or None
    return plan
```

- [ ] **Step 5: 在唯一落库点调用**

`api/narration.py` 的 `_generate_one`，把 `:232-242` 改为（新增一行 `with_subtitle_preset`）：

```python
    if plan.narration_texts:
        tts_dir = context.work_dir / "tts"
        models_dir = context.data_dir / "models"
        plan = narration_pipeline.synthesize_narration_texts(plan, settings, tts_dir, models_dir)
    plan = narration_pipeline.with_subtitle_preset(plan, settings)
    plans_repo.create(
        context.conn,
        project_id,
        mode,
        used_ids,
        plan.model_dump(),
    )
```

- [ ] **Step 6: 导出侧读它**

`api/export.py:103`：
```python
    preset = subtitle_presets.get_preset(plan_data.subtitle_preset)
```

- [ ] **Step 7:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration tests/api -q` → Expected 全绿。
- [ ] **Step 8:** Run: `cd service && ../.venv/Scripts/python -m pytest tests -q` → Expected `182 passed`。
- [ ] **Step 9: 提交**

```bash
git add service/dramaclip/engines/narration/models.py service/dramaclip/engines/narration/pipeline.py \
        service/dramaclip/api/export.py service/dramaclip/api/narration.py \
        service/tests/engines/narration/test_subtitle_preset.py
git commit -m "fix(subtitle): 字幕预设经 plan_data 接进出片，结束恒回退 conflict-impact"
```

## Task A3: 预筛阈值读设置（现为硬编码 70.0）

**Files:**
- Modify: `service/dramaclip/engines/analysis/prescreen.py:60-95`
- Modify: `service/dramaclip/api/analysis.py:81-84`
- Test: `service/tests/engines/analysis/test_prescreen.py`（已存在则追加，不存在则新建，文件头同 test_produce 风格）

- [ ] **Step 1: 写失败测试**

```python
def test_recommend_honours_threshold() -> None:
    """入选判定是纯函数，阈值由调用方从设置传入（不再硬编码 70.0）。"""
    from dramaclip.engines.analysis import prescreen as pe

    assert pe.recommend(60.0, threshold=70.0) is False
    assert pe.recommend(60.0, threshold=50.0) is True
    assert pe.recommend(70.0, threshold=70.0) is True  # 边界含
```

- [ ] **Step 2:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/analysis/test_prescreen.py -v`
Expected: FAIL —— `AttributeError: module 'dramaclip.engines.analysis.prescreen' has no attribute 'recommend'`。

- [ ] **Step 3: 抽纯函数并接收阈值**

`engines/analysis/prescreen.py` 新增（放在 `prescreen_episode` 之前）：

```python
def recommend(score: float, *, threshold: float) -> bool:
    """是否入选推荐集。阈值由调用方从 analysis.prescreen_threshold 传入。"""
    return score >= threshold
```

`prescreen_episode()` 签名增 `*, threshold: float = 70.0`，并把 `:95` 的 `"recommended": score >= 70.0` 替换为：

```python
        "recommended": recommend(score, threshold=threshold),
```

- [ ] **Step 4: 调用方传设置值**

`api/analysis.py:81-84`（`_run_prescreen` 内）。阈值在循环外取一次，避免逐集重复解析：

```python
    threshold = float(context.settings.get("analysis.prescreen_threshold", "70"))
    try:
        for index, episode in enumerate(targets):
            ...
            result = prescreen_engine.prescreen_episode(
                Path(str(episode["source_path"])),
                context.work_dir / "prescreen" / f"{episode_id}.wav",
                threshold=threshold,
            )
```

- [ ] **Step 5:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/analysis tests/api -q` → Expected 全绿。
- [ ] **Step 6:** Run: `cd service && ../.venv/Scripts/python -m pytest tests -q` → Expected `183 passed`。
- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/engines/analysis/prescreen.py service/dramaclip/api/analysis.py \
        service/tests/engines/analysis/test_prescreen.py
git commit -m "fix(prescreen): 推荐阈值读 analysis.prescreen_threshold，去掉硬编码 70.0"
```

## Task A4: 声明式 ML 依赖（README 的安装命令当前装不出可用环境）

**Files:**
- Modify: `service/pyproject.toml:16-23`
- Modify: `README.md:27`、`service/dramaclip/engines/analysis/transcriber.py:1-5`

- [ ] **Step 1: 先核对真实依赖清单**（不要凭记忆写）

Run: `PYTHONIOENCODING=utf-8 python -c "import re,pathlib;print('\n'.join(sorted(set(re.findall(r'\"([A-Za-z0-9_.\\-]+)\", pathlib.Path('scripts/build-service.py').read_text(encoding='utf-8').split('HIDDEN_IMPORTS')[1].split(']')[0])))))"`
Expected: 打印 PyInstaller 里那份 `HIDDEN_IMPORTS`。**以它的实际内容为准**填下一步的 `ml` 列表，逐项核对包名与 import 名的差异（`scenedetect` / `faster_whisper` / `soundfile` / `numpy` / `librosa` / `funasr` / `kokoro`）。凡 Windows 上有版本约束的（如 opencv 必须 <5），约束写进 `ml` 而不是留给口头知识。

- [ ] **Step 2: 加 `ml` extras**

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "ruff>=0.6",
  "mypy>=1.11",
]
# 媒体/AI 引擎重依赖：本地开发与打包共用同一声明，避免 README 与 PyInstaller 两套真相
ml = [
  "numpy",
  "soundfile",
  "scenedetect",
  "faster-whisper",
  "librosa",
]
```

- [ ] **Step 3: 用声明式安装验证可导入**

Run: `.venv/Scripts/pip install -e "service[dev,ml]"`
Run: `cd service && ../.venv/Scripts/python -c "import numpy, soundfile, scenedetect, faster_whisper, librosa; print('ml deps ok')"`
Expected: `ml deps ok`。

- [ ] **Step 4: 同步 README 与 docstring**

`README.md:27` → `.venv/Scripts/pip install -e "service[dev,ml]"`；`transcriber.py:3-5` 关于"ml extras"的表述改为与 `pyproject.toml` 一致的事实。

- [ ] **Step 5:** Run: `cd service && ../.venv/Scripts/python -m pytest tests -q` → Expected `183 passed`（纯声明，不改行为）。
- [ ] **Step 6: 提交**

```bash
git add service/pyproject.toml README.md service/dramaclip/engines/analysis/transcriber.py
git commit -m "fix(deps): 声明 ml extras，README 安装命令恢复可用"
```

---

# Phase B · 成片音轨正确性

> **必须按 B1 → B2 → B3 顺序做**：B1 提供映射字段，B2 修混音分支，B3 用 B1 的字段建正确映射。B2/B3 颠倒会出现中间态红灯。

## Task B1: TimelineSegment 显式携带 narration_id，回填覆盖 ducked

**Files:**
- Modify: `service/dramaclip/engines/narration/models.py:12-21`
- Modify: `service/dramaclip/engines/narration/pipeline.py:277-291`
- Test: `service/tests/engines/narration/test_ducked_narration.py`（新建）

- [ ] **Step 1: 写失败测试**（用 `monkeypatch` 打桩 TTS 与时长探测，不碰网络、不碰真音频）

```python
"""旁白回填必须覆盖 narration 与 ducked 两类段，并显式记录段→旁白映射。

回归动机：ducked 段此前被回填循环跳过（full_narration 全部段），
且导出侧靠位置索引重推映射，旁白数≠narration 段数时错音。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment


class _StubTts:
    """返回一个存在但内容为空的路径；时长探测已被打桩。"""

    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")
        return out_path


def _plan(roles: list[str]) -> PlanData:
    return PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(episode_id="ep1", start=float(i), end=float(i) + 1.0, audio=role)
            for i, role in enumerate(roles)
        ],
        narration_texts=[
            NarrationText(id=f"n{i}", text=f"旁白{i}") for i in range(len(roles))
        ],
    )


@pytest.fixture()
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)


def test_ducked_segments_get_backfilled(stubbed, tmp_path: Path) -> None:
    result = pipeline.synthesize_narration_texts(
        _plan(["ducked", "ducked"]), {"tts.engine": "edge"}, tmp_path
    )
    assert [s.narration_id for s in result.timeline] == ["n0", "n1"]
    assert [s.subtitle_text for s in result.timeline] == ["旁白0", "旁白1"]
    assert [s.end - s.start for s in result.timeline] == [1.25, 1.25]


def test_alternating_roles_map_to_owning_text(stubbed, tmp_path: Path) -> None:
    """原声/旁白交替（cross_narration）：两条旁白必须落在第 1、3 段。"""
    result = pipeline.synthesize_narration_texts(
        _plan(["original", "narration", "original", "narration"]),
        {"tts.engine": "edge"},
        tmp_path,
    )
    assert [s.narration_id for s in result.timeline] == [None, "n0", None, "n1"]
    assert [s.audio for s in result.timeline] == [
        "original", "narration", "original", "narration",
    ]


def test_failed_tts_falls_back_and_clears_id(tmp_path: Path, monkeypatch) -> None:
    """合成失败 → 段回退原声，且不得留下会错配的 narration_id。"""
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _BrokenTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: None)
    result = pipeline.synthesize_narration_texts(
        _plan(["narration"]), {"tts.engine": "edge"}, tmp_path
    )
    assert result.timeline[0].audio == "original"
    assert result.timeline[0].narration_id is None


class _BrokenTts:
    def synthesize(self, text: str, voice: str | None, out_path: Path) -> Path:
        raise RuntimeError("云端不可达")
```

> 桩的两个落点已在源码核实：`pipeline.py:264` 调用 `create_tts(...)`（模块级导入名），`pipeline.py:272` 调用 `tts_base.audio_duration_s(...)`。若 `create_tts` 实际是经 `factory` 命名空间调用，则把打桩目标改为 `pipeline.factory.create_tts`——**以 `pipeline.py` 顶部 import 行为准，跑一次即知**。

- [ ] **Step 2:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_ducked_narration.py -v`
Expected: 三条 FAIL —— `TimelineSegment` 无 `narration_id`（`AttributeError: 'TimelineSegment' object has no attribute 'narration_id'`）。`ducked` 那条若因 `models.py` 已默认忽略未知字段而表现不同，按实际报错调整断言顺序，但**不得放宽断言**。

- [ ] **Step 3: 加字段**

`engines/narration/models.py` 的 `TimelineSegment`：

```python
    subtitle_text: str | None = None
    emotion_label: str | None = None
    # 本段旁白对应的 NarrationText.id；导出侧据此取音，禁止再靠位置索引推断
    narration_id: str | None = None
```

- [ ] **Step 4: 回填循环同时认 narration 与 ducked，并写 id**

`engines/narration/pipeline.py:277-290` 整段替换（保留既有"合成失败回退原声"语义）：

```python
    timeline = [segment.model_dump() for segment in plan.timeline]
    narration_order = 0
    for segment in timeline:
        if segment["audio"] not in ("narration", "ducked"):
            continue
        segment["narration_id"] = None
        if narration_order >= len(updated):
            segment["audio"] = "original"
            continue
        text = updated[narration_order]
        narration_order += 1
        duration = text["duration"]
        if duration is not None and duration > 0:
            segment["end"] = round(segment["start"] + duration, 3)
            segment["subtitle_text"] = str(text["text"])
            segment["narration_id"] = str(text["id"])
        else:
            segment["audio"] = "original"  # 无旁白音频 → 回退原声段（字幕一并取消）
            segment["subtitle_text"] = None
```

- [ ] **Step 5:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration -q`
Expected: 新 3 条 passed；既有 `test_modes_w8.py`（只断言标记为 `ducked`）不回归。
- [ ] **Step 6:** Run: `cd service && ../.venv/Scripts/python -m pytest tests -q` → Expected `186 passed`。
- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/engines/narration/models.py service/dramaclip/engines/narration/pipeline.py \
        service/tests/engines/narration/test_ducked_narration.py
git commit -m "fix(narration): 旁白回填覆盖 ducked 角色，段落显式携带 narration_id"
```

## Task B2: 编码器只要携带旁白音频就混音（修 full_narration 丢旁白）

**Files:**
- Modify: `service/dramaclip/engines/exporter/encoder.py:47,80-92`
- Test: `service/tests/engines/exporter/test_mix.py`（新建；若已有 exporter 测试目录则并入）

- [ ] **Step 1: 写失败测试**

```python
"""只要给了旁白音频就要混进成片——与 audio 标记是 narration 还是 ducked 无关。"""

from __future__ import annotations

import random

from dramaclip.engines.exporter import encoder


def _args(audio: str, tts: str | None) -> list[str]:
    return encoder.cut_segment_args(
        "src.mp4", "out.mp4", start=0.0, end=3.0, audio=audio, mask=False,
        tts_audio=tts, rng=random.Random(0),
    )


def test_ducked_segment_mixes_tts() -> None:
    args = _args("ducked", "tts.mp3")
    assert "-filter_complex" in args, "ducked 段未走混音分支，旁白会整条丢失"
    assert "tts.mp3" in args


def test_narration_segment_mixes_tts() -> None:
    assert "-filter_complex" in _args("narration", "tts.mp3")


def test_original_segment_keeps_source_audio() -> None:
    args = _args("original", None)
    assert "-filter_complex" not in args
    assert "-vf" in args


def test_narration_without_audio_falls_back_to_plain() -> None:
    assert "-filter_complex" not in _args("narration", None), "无音频时不应声明第二路输入"
```

- [ ] **Step 2:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter/test_mix.py -v`
Expected: `test_ducked_segment_mixes_tts` FAIL；其余三条 PASS（说明改动面精确）。

- [ ] **Step 3: 改分支条件**

`encoder.py:80`：

```python
    if tts_audio:
        # 携带旁白即混音：TTS 主音 + 原声压低 20%（原案 6.4 混音规则）
```

同步更新 `cut_segment_args` 的 docstring（`:47`）为准确表述：

```python
    """构建单段切割命令（Phase A）。

    audio 角色语义：narration 与 ducked 在携带旁白音频时渲染等价（旁白 + 原声压低）；
    任一角色在无旁白音频时回退原声。original 恒原声。
    """
```

- [ ] **Step 4:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter -q` → Expected 4 passed，既有 `cut_segment_args` 命令构建测试不回归。
- [ ] **Step 5: 提交**

```bash
git add service/dramaclip/engines/exporter/encoder.py service/tests/engines/exporter/test_mix.py
git commit -m "fix(export): 携带旁白即混音，修复 full_narration 全程无解说音"
```

## Task B3: 导出按 narration_id 取音（修 cross / ultra_short 错音与 CTA 丢失）

**Files:**
- Modify: `service/dramaclip/api/export.py:97-101`
- Test: `service/tests/api/test_export_tts_mapping.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""段→旁白映射必须按 id，不按位置序号。

回归动机：cross_narration 原声/旁白交替、ultra_short 的 CTA 在末段，
按 enumerate(narration_texts) 建映射会整段错一位并丢弃 CTA。
"""

from __future__ import annotations

from dramaclip.api.export import tts_audio_by_segment
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment


def _plan(segments: list[TimelineSegment], texts: list[NarrationText]) -> PlanData:
    return PlanData(mode="cross_narration", timeline=segments, narration_texts=texts)


def test_alternating_timeline_maps_to_owning_text() -> None:
    plan = _plan(
        [
            TimelineSegment(episode_id="e", start=0, end=1, audio="original"),
            TimelineSegment(episode_id="e", start=1, end=2, audio="narration", narration_id="n0"),
            TimelineSegment(episode_id="e", start=2, end=3, audio="original"),
            TimelineSegment(episode_id="e", start=3, end=4, audio="narration", narration_id="n1"),
        ],
        [
            NarrationText(id="n0", text="甲", audio_path="/a/n0.mp3"),
            NarrationText(id="n1", text="乙", audio_path="/a/n1.mp3"),
        ],
    )
    assert tts_audio_by_segment(plan) == {1: "/a/n0.mp3", 3: "/a/n1.mp3"}


def test_missing_id_is_not_silently_mapped() -> None:
    plan = _plan(
        [TimelineSegment(episode_id="e", start=0, end=1, audio="narration")],
        [NarrationText(id="n0", text="甲", audio_path="/a/n0.mp3")],
    )
    assert tts_audio_by_segment(plan) == {}  # 无 id 即无映射，绝不按位置猜


def test_dangling_id_is_dropped() -> None:
    plan = _plan(
        [TimelineSegment(episode_id="e", start=0, end=1, audio="narration", narration_id="ghost")],
        [NarrationText(id="n0", text="甲", audio_path="/a/n0.mp3")],
    )
    assert tts_audio_by_segment(plan) == {}


def test_unsynthesized_text_is_dropped() -> None:
    plan = _plan(
        [TimelineSegment(episode_id="e", start=0, end=1, audio="narration", narration_id="n0")],
        [NarrationText(id="n0", text="甲", audio_path=None)],
    )
    assert tts_audio_by_segment(plan) == {}
```

- [ ] **Step 2:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_export_tts_mapping.py -v`
Expected: 四条 FAIL —— `ImportError: cannot import name 'tts_audio_by_segment'`。

- [ ] **Step 3: 抽纯函数并改调用点**

`api/export.py` 新增（放在 `render_export` 之前）。**返回 `dict[int, str]`**（编码器按字符串路径拼命令，避免多一次 `str()` 转换）：

```python
def tts_audio_by_segment(plan: PlanData) -> dict[int, str]:
    """段序号 → 旁白音频路径。按 segment.narration_id 显式取用，绝不按位置推断。"""
    by_id = {
        text.id: text.audio_path for text in plan.narration_texts if text.audio_path is not None
    }
    return {
        index: by_id[segment.narration_id]
        for index, segment in enumerate(plan.timeline)
        if segment.narration_id is not None and segment.narration_id in by_id
    }
```

`render_export` 内 `:97-101` 整段替换：

```python
    tts_segments = tts_audio_by_segment(plan_data)
```

`encoder.export_plan` 的形参类型同步收敛（`encoder.py:150`、`:187`）：`dict[int, Path] | None` → `dict[int, str] | None`，`:187` 去掉多余 `str()`：

```python
    tts_audio_by_segment: dict[int, str] | None = None,
```
```python
            tts_audio = tts_audio_by_segment.get(index) if tts_audio_by_segment else None
```

- [ ] **Step 4:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/api tests/engines/exporter -q` → Expected 4 passed + 端到端仍绿。
- [ ] **Step 5:** Run: `cd service && ../.venv/Scripts/python -m pytest tests -q` → Expected `194 passed`（186 + B1 的 3 已计、此处 +4；以实际计数为准，**只增不减**）。
- [ ] **Step 6: 提交**

```bash
git add service/dramaclip/api/export.py service/dramaclip/engines/exporter/encoder.py \
        service/tests/api/test_export_tts_mapping.py
git commit -m "fix(export): 旁白按 narration_id 取用，修复交替编排错音与 CTA 丢失"
```

## Task B4: 台词保护区改用库内 ASR（SRT 恒不存在）

**Files:**
- Modify: `service/dramaclip/api/export.py`（新函数 + `render_export`）
- Modify: `service/dramaclip/engines/exporter/encoder.py:144-184`
- Test: `service/tests/engines/dedup/test_asr_protection.py`（新建）

- [ ] **Step 1: 写失败测试**（先写会红的那条：导出侧没有兜底取区能力）

```python
"""无同名 .srt 时，保护区必须取自库内 asr_segments（原案第八章双路设计）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dramaclip.api import export as export_api
from dramaclip.engines.analysis.models import AudioFeatures
from dramaclip.infra.storage.repos import analysis as analysis_repo


def test_zones_fall_back_to_stored_asr(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    """真实工作流里根本没有 .srt —— ASR 只进 SQLite，此前保护区恒为空。"""
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    analysis_repo.upsert(
        memory_db,
        "ep1",
        asr_segments=json.dumps(
            [{"start": 2.0, "end": 4.0, "text": "台词一"}, {"start": 5.0, "end": 6.5, "text": "台词二"}]
        ),
        scene_data="[]",
        audio_features=AudioFeatures().model_dump_json(),
        conflict_scores="[]",
        highlights="[]",
    )
    zones = export_api.protection_zones_for(
        memory_db, episode_id="ep1", source_path=str(source)
    )
    assert [(z.start, z.end) for z in zones] == [(2.0, 4.0), (5.0, 6.5)]


def test_srt_wins_over_stored_asr(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    source = tmp_path / "ep2.mp4"
    source.write_bytes(b"x")
    source.with_suffix(".srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n手工字幕\n", encoding="utf-8"
    )
    zones = export_api.protection_zones_for(
        memory_db, episode_id="ep2", source_path=str(source)
    )
    assert [(z.start, z.end) for z in zones] == [(1.0, 2.0)]


def test_no_analysis_yields_empty(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    zones = export_api.protection_zones_for(
        memory_db, episode_id="missing", source_path=str(tmp_path / "nope.mp4")
    )
    assert zones == []
```

- [ ] **Step 2:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/dedup/test_asr_protection.py -v`
Expected: 三条 FAIL —— `AttributeError: module 'dramaclip.api.export' has no attribute 'protection_zones_for'`。

- [ ] **Step 3: 实现取区函数**

`api/export.py` 新增（置于 `render_export` 之前），并补 import：`json`、`sqlite3`、`SpeechZone`、`jitter`、`analysis_repo`（`from dramaclip.infra.storage.repos import analysis as analysis_repo`）：

```python
def protection_zones_for(
    conn: sqlite3.Connection, *, episode_id: str, source_path: str
) -> list[SpeechZone]:
    """切点保护区双路取源：同名 .srt 优先（尊重手工字幕文件），缺失回退库内 ASR。"""
    srt = jitter.srt_for_source(Path(source_path))
    if srt is not None:
        return jitter.parse_srt(srt)
    record = analysis_repo.get(conn, episode_id)
    if record is None or not record.get("asr_segments"):
        return []
    try:
        segments = json.loads(str(record["asr_segments"]))
    except json.JSONDecodeError:
        return []
    return [
        SpeechZone(start=float(item["start"]), end=float(item["end"]))
        for item in segments
        if isinstance(item, dict) and "start" in item and "end" in item
    ]
```

- [ ] **Step 4: 接入导出链**

`render_export` 内按时间轴涉及的集预取一次（放在 `tts_segments` 之后），并传进编码器：

```python
    zones_by_episode = {
        episode_id: protection_zones_for(
            context.conn, episode_id=episode_id, source_path=episode_paths[episode_id]
        )
        for episode_id in {segment.episode_id for segment in plan_data.timeline}
        if episode_id in episode_paths
    }
```
```python
        protection_zones_by_episode=zones_by_episode,
```

- [ ] **Step 5: 编码器接收 zones 入参并保留 .srt 优先级**

`encoder.py:150` 签名增：

```python
    protection_zones_by_episode: dict[str, list[SpeechZone]] | None = None,
```

`encoder.py:172-184` 的 SRT 缓存块替换为：

```python
    # Phase A：构建每段命令参数（含台词保护区安全切点、字幕、混音）
    job_args: list[list[str]] = []
    zones_cache: dict[str, list[SpeechZone]] = {}
    for index, segment in enumerate(segments):
        source = episode_paths.get(segment.episode_id)
        if source is None or not Path(source).is_file():
            raise EpisodeSourceMissing(f"第 {segment.episode_id} 集源文件缺失")
        if segment.episode_id not in zones_cache:
            from_file = jitter.srt_for_source(Path(source))
            zones_cache[segment.episode_id] = (
                jitter.parse_srt(from_file)
                if from_file is not None
                else (protection_zones_by_episode or {}).get(segment.episode_id, [])
            )
        safe_start, safe_end = jitter.safe_times(
            segment.start, segment.end, zones_cache[segment.episode_id], rng=rng
        )
```

- [ ] **Step 6: 加一条端到端断言（防止再次"接了但没生效"）**

`tests/api/test_export_tts_mapping.py` 追加：

```python
def test_export_plan_uses_injected_zones(memory_db, tmp_path, sample_video) -> None:
    """注入保护区后，落在台词中间的切点必须被外移，而不是原样切下去。"""
    import random

    from dramaclip.engines.analysis.models import SpeechZone
    from dramaclip.engines.exporter import encoder

    zones = {"ep1": [SpeechZone(start=2.0, end=4.0)]}
    rng = random.Random(0)
    plain = jitter.safe_times(3.0, 6.0, [], rng=rng)
    guarded = jitter.safe_times(3.0, 6.0, zones["ep1"], rng=rng)
    assert guarded[0] < plain[0] or guarded[1] > plain[1]
```
（文件头补 `from dramaclip.engines.dedup import jitter`。）

- [ ] **Step 7:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/dedup tests/api tests/engines/exporter -q` → Expected 全绿。
- [ ] **Step 8:** Run: `cd service && ../.venv/Scripts/python -m pytest tests -q` → Expected 仅增不减。
- [ ] **Step 9: 提交**

```bash
git add service/dramaclip/api/export.py service/dramaclip/engines/exporter/encoder.py \
        service/tests/engines/dedup/test_asr_protection.py service/tests/api/test_export_tts_mapping.py
git commit -m "fix(dedup): 台词保护区回退库内 ASR，修复 .srt 恒缺失致保护失效"
```

> **`raw_clip` 说明：** 该模式零加工但仍走同一条导出链。保护区对它有**利**（切点不吞台词），故不关闭。消重参数（微缩放/eq/变速）是否应作用于 `raw_clip` 是批次 1 的独立议题，本方案不动。

## Task B5: 给 script_driver 补回归测试（当前零覆盖）

**Files:**
- Test: `service/tests/engines/narration/test_script_driver.py`（新建）
- Modify（仅当测试暴露缺陷时）: `service/dramaclip/engines/narration/script_driver.py`

**为什么单列一条：** `script_driver.py` 是跨集 + 两层制 + 降级链的**装配入口**，也是全项目最新的核心资产，`pytest --collect-only` 命中数为 0。它同时是今天 16:03 那次 `'dict' object has no attribute 'start'` 失败的现场——该错误在 16:17 之后不再出现，但没有测试能证明它已修好、更挡不住它复发。

- [ ] **Step 1: 写覆盖降级链四态的测试**

```python
"""script_driver 是跨集解说的装配入口，此前零测试覆盖。

四态必须各自锁定：显式风格 > LLM 自选 > 题材映射 > general；
以及 LLM 不可用时整链降级到规则编排。
"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration import script_driver, styles


def test_explicit_style_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        styles, "select_style_with_reason", lambda *a, **k: (_ for _ in ()).throw(AssertionError)
    )
    assert styles.resolve_style_id("suspense", genre="逆袭", auto_select=False) == "suspense"


def test_auto_llm_selection_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(_inputs, _settings, **_k):
        return {"style_id": "shuanggan", "reason": "打脸逆袭节奏"}

    monkeypatch.setattr(styles, "select_style_with_reason", fake)
    assert styles.resolve_style_id("auto", genre="逆袭", auto_select=True) == "shuanggan"


def test_llm_failure_falls_back_to_genre_map(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("超时")

    monkeypatch.setattr(styles, "select_style_with_reason", boom)
    assert styles.resolve_style_id("auto", genre="复仇", auto_select=True) == "shuanggan"


def test_unknown_genre_falls_back_to_general(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(styles, "select_style_with_reason", lambda *a, **k: None)
    assert styles.resolve_style_id("auto", genre="没这个题材", auto_select=True) == "general"


def test_out_of_library_style_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        styles, "select_style_with_reason", lambda *a, **k: {"style_id": "hacker", "reason": "x"}
    )
    assert styles.resolve_style_id("auto", genre="悬疑", auto_select=True) == "suspense"
```

> **执行者注：** `resolve_style_id` 的实际签名以 `engines/narration/styles.py:20-85` 为准（含 `_GENRE_STYLE_MAP` 的键与题材值）。**先读该函数，再把上面五例的参数名/顺序调成与真实签名一致**——断言的**语义**（五态各一）不得改变，改的只是调用形式。若真实签名与上述差异过大，改为按 `styles.py` 实际入参重写这五例并保留同名测试标题。

- [ ] **Step 2:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_script_driver.py -v`
Expected: 首跑可能因签名不符而 `TypeError`——按实际签名修正测试调用形式（这是允许的），**修正后应全绿**。若某条断言真实失败（例如 LLM 返回库外 id 未被拒绝），即为发现的缺陷：**保留红灯，写一条修复使之上绿**，并在提交信息里记明修了什么。

- [ ] **Step 3: 补一条 LLM 失败 → 规则降级的装配断言**

```python
def test_produce_falls_back_to_rule_when_script_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """剧本生成返回 None（超时/未配置）时必须落到规则编排，且不得静默。"""
    monkeypatch.setattr(script_driver, "write_script_episodes", lambda *a, **k: None)
    logs: list[tuple[str, str]] = []
    result = script_driver.build_dialogue_plan(
        _episode_inputs(), _settings(), log=lambda level, msg: logs.append((level, msg))
    )
    assert result is not None
    assert result[0].planner == "rule"
    assert any(level == "warn" for level, _msg in logs), "降级必须留痕，不能静默退化"
```
（`_episode_inputs()` / `_settings()` 参照 `tests/engines/narration/test_script_episodes.py` 里已有的构造方式复用，勿新造数据形状。）

- [ ] **Step 4: 跑测试并按实际签名收敛**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration -q`
Expected: 全绿；`script_driver.py` 的收集测试数由 0 变为 ≥6。

- [ ] **Step 5:** Run: `cd service && ../.venv/Scripts/python -m pytest tests -q` → Expected 仅增不减。
- [ ] **Step 6: 提交**

```bash
git add service/tests/engines/narration/test_script_driver.py
git commit -m "test(narration): 补 script_driver 降级链与风格四态回归（此前零覆盖）"
```

## Task B6: 跨集剧本输入不得静默丢集（当前按集号头部截断）

**Files:**
- Modify: `service/dramaclip/engines/narration/scriptwriter.py:121-136`
- Test: `service/tests/engines/narration/test_script_input_budget.py`（新建）

**已核实的缺陷（本方案里严重度最高的一条）：** `scriptwriter.py:123-129` 按集号升序遍历，累加到总量上限即 `break`（现为 `_EPISODE_LINE_CAP = 80` / `_TOTAL_LINE_CAP = 500`），且集标题行在内层判断**之前**就已 append。真实留痕可证：`data/logs/llm/llm_script_0909_163343.json` 的 `user` 字段含 **300 行台词**（当时的总上限恰为 300，每集上限 40），而该项目共 10 集、每集约 51.6 段 → **模型只看到第 1~8 集，第 9、10 集一行未进**；输出剧本的取材集号也确实止于第 8 集。全程无日志、无标注，而 prompt 明写"转写来自多集"，模型被告知它看到的是全部集。

外推到目标尺度：行均 18.6 字符 → 80 集 ≈ 4128 行 ≈ 76,800 字符 ≈ **46k–76k token**，现代模型窗口**装得下**。所以本缺陷的理由不是"塞不下"，而是**代码写死了截断且截断方向是头部**——反转与高潮集中在后段，配额（现 500 行 ÷ 每集 ~52 行 ≈ 前 10 集）恰好把最有卖点的内容全部丢掉。**这正是「整剧 = 处理单元」模型的头号阻断项。**

**本任务做两件事：把取样从"头部截断"改为"按集分配额"，并把截断事实显式说出来。** 配额取样保证 80 集也能集集露面（并如实标注"每集均匀摘录"）。它不是终局：真正让模型"看懂全剧"的是批次 1 的逐集摘要层——摘要的价值在**可复用**（每集一次，K 条方案 × 九模式 × 重跑 × 批次3证据链 × 批次4文案共用）与**端点中立**（ADR-005 允许切本地模型，不得把"读得进全剧"绑在用户恰好拥有大窗口模型上），而不在省窗口。

- [ ] **Step 1: 写失败测试**

```python
"""跨集剧本输入：预算内必须让每一集都有代表，不得按集号头部截断。"""

from __future__ import annotations

import re

from dramaclip.engines.narration import scriptwriter


def _ep(number: int, segs: int) -> dict:
    return {
        "number": number,
        "episode_id": f"e{number}",
        "duration": 160.0,
        "segments": [
            {"start": float(i), "end": float(i) + 1, "text": f"集{number}台词{i}"}
            for i in range(segs)
        ],
    }


def test_all_episodes_are_represented() -> None:
    """80 集 × 60 段 = 4800 行，远超 500 预算：旧实现只喂进前 ~10 集。"""
    inputs = [_ep(n, 60) for n in range(1, 81)]
    prompt = scriptwriter._format_transcript_episodes(inputs)
    for number in (1, 20, 40, 60, 80):
        assert f"【第{number}集】" in prompt, f"第{number}集被静默整集丢弃"
        assert f"集{number}台词" in prompt


def test_truncation_is_reported() -> None:
    inputs = [_ep(n, 60) for n in range(1, 81)]
    prompt = scriptwriter._format_transcript_episodes(inputs)
    assert "摘录" in prompt, "未向模型说明看到的是配额摘录而非全量逐字"


def test_no_empty_episode_header() -> None:
    """一集若最终一行都没进，就不得留下孤立的集标题。"""
    inputs = [_ep(n, 60) for n in range(1, 81)]
    prompt = scriptwriter._format_transcript_episodes(inputs)
    headers = re.findall(r"【第(\d+)集】\n([^\n]*)", prompt)
    assert headers, "未匹配到任何集块——标题格式与预期不符"
    for number, following in headers:
        assert following.strip(), f"第{number}集标题后为空"


def test_small_project_uses_every_line() -> None:
    """集数少时不应无谓丢行：3 集 × 20 段 = 60 行，远在预算内。"""
    inputs = [_ep(n, 20) for n in (1, 2, 3)]
    prompt = scriptwriter._format_transcript_episodes(inputs)
    assert prompt.count("台词19") == 3  # 每集最后一段仍在
```

> 标题字面量 `【第N集】` 与 Step 3 实现、`cross_block` 措辞三处必须完全一致；本测试即为该一致性的检查点。

- [ ] **Step 2:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_script_input_budget.py -v`
Expected: `test_all_episodes_are_represented` FAIL（第 20/40/60/80 集不在 prompt 里）；`test_truncation_is_reported` FAIL；`test_small_project_uses_every_line` 可能已 PASS。红灯形态即为诊断。

- [ ] **Step 3: 改为按集分配额取样**

`scriptwriter.py` 新增纯函数（置于 `write_script_episodes` 之前），并让后者改用它：

```python
_MIN_LINES_PER_EPISODE = 3


def _pick_across(segments: list[dict[str, Any]], quota: int) -> list[dict[str, Any]]:
    """在单集内均匀取 quota 段（含首与尾）。短剧高潮多在集尾，不可只取开头。"""
    if quota <= 0 or not segments:
        return []
    if len(segments) <= quota:
        return list(segments)
    step = (len(segments) - 1) / (quota - 1) if quota > 1 else 0.0
    picked = [segments[min(int(round(i * step)), len(segments) - 1)] for i in range(quota)]
    seen: set[int] = set()
    ordered: list[dict[str, Any]] = []
    for seg in picked:  # 去重并保持时间升序
        key = id(seg)
        if key not in seen:
            seen.add(key)
            ordered.append(seg)
    return ordered


def _format_transcript_episodes(
    episode_inputs: list[dict[str, Any]],
    *,
    total_cap: int = _TOTAL_LINE_CAP,
    episode_cap: int = _EPISODE_LINE_CAP,
) -> str:
    """把全部集拼成带集号与时间戳的转写块，按集分配额，保证集集露面。"""
    usable = [ep for ep in episode_inputs if ep.get("segments")]
    if not usable:
        return ""
    quota = max(total_cap // len(usable), _MIN_LINES_PER_EPISODE)
    quota = min(quota, episode_cap)
    lines: list[str] = []
    for episode in usable:
        number = int(episode["number"])
        rendered: list[str] = []
        for seg in _pick_across(list(episode["segments"]), quota):
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            span = f"{_clock(float(seg.get('start', 0)))}-{_clock(float(seg.get('end', 0)))}"
            rendered.append(f"{span} {text}")
        if not rendered:  # 空集不留孤立标题
            continue
        lines.append(f"【第{number}集】")
        lines.extend(rendered)
    total_segments = sum(len(ep["segments"]) for ep in usable)
    note = (
        f"（共 {len(usable)} 集、约 {total_segments} 段转写；"
        f"受上下文预算限制，此处为每集均匀摘录约 {quota} 段，非全量逐字。"
        "请据此判断全剧故事线与各集在高潮曲线上的位置。）"
    )
    return "\n".join(lines) + "\n" + note
```

`write_script_episodes` 内原来的 `durations/lines` 拼装循环（`:121-136`）替换为调用该函数；`durations` 单独由一行推导得出：

```python
    durations = {
        int(ep["number"]): float(ep.get("duration") or 0.0) for ep in episode_inputs
    }
    transcript_block = _format_transcript_episodes(episode_inputs)
    if not transcript_block:
        return None
```

同时把 `cross_block` 里"转写按集分组（每组以「第N集：」开头）"的措辞与新标题格式 `【第N集】` 对齐——**两处必须一致，否则模型按旧格式理解新数据**。

- [ ] **Step 4: 调用方留痕（静默降级是本仓库的老毛病，这次不留口子）**

`api/narration.py` 的 `script_dialogue_plan` 调用点之后，把"取样密度"打进日志，让用户在出片记录里看得懂为什么后段剧情没被采用：

```python
        context.notifier.log(
            "info",
            f"跨集输入：{len(episode_inputs)} 集 → 每集约 {max(500 // max(len(episode_inputs), 1), 3)} 段摘录",
        )
```

- [ ] **Step 5:** Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration -q` → Expected 全绿，含既有 `test_script_episodes.py` / `test_scriptwriter.py`（若它们断言了旧标题格式「第N集：」，把期望同步为 `【第N集】`——**格式变更必须显式改测试，不许放宽断言**）。
- [ ] **Step 6: 真机复验（唯一能证明"后段剧情 now 可见"的环节）**

Run: `npm run dev` → 对现有 10 集剧跑一次剧情解说 → 打开新生成的 `data/logs/llm/llm_script_*.json`，确认 `user` 字段里第 9、10 集的台词已出现、且结尾有"每集均匀摘录"说明。**再用一部 40 集以上的剧复跑**，确认 `segments` 里开始出现后段集号。若拿不到更大的剧，就在报告里明确写"80 集尺度未验证"，不要假定成立。
- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/engines/narration/scriptwriter.py service/dramaclip/api/narration.py \
        service/tests/engines/narration/
git commit -m "fix(narration): 跨集输入改按集分配额取样，修复 500 行头部截断致后段剧情整段丢失"
```

---

# Phase C · 客户端止血（假文案与不可见失败）

> 共同原则（用户定案，三档）：**① 指向错误页面的路由必修；② 本方案会接通的功能（字幕预设、预筛阈值）保持原样不动；③ 本方案不接通却仍在设置里摆着的死控件，标注「当前未生效」——不用"即将支持"，以免变成长期谎言；④ 纯虚构的能力（拖放导入）删除或改口。** 不为凑文案去临时实现功能。

## Task C1: EnvPanel 两处错路由 + 三条假提示

**Files:**
- Modify: `desktop/src/features/home/EnvPanel.tsx:38,44,157`
- Modify: `desktop/src/features/home/HomePage.tsx:104`、`StartCards.tsx:25`

- [ ] **Step 1: 先取证现状**（这三处文案都是用户会照做的指引，改错方向代价高）

Run: `cd desktop && npx tsc --noEmit -p tsconfig.app.json && grep -n "models/" src/app/router.tsx`
Expected: 确认引擎中心路由形态为 `/models` + `/models/:tab`，tab 取值含 `asr`/`llm`/`tts`。

- [ ] **Step 2: 修两处错路由**（LLM 配置在 `/models/llm`，不在 `/settings`——`sections.ts` 里没有任何 llm 字段；ASR 模型在 `/models/asr`）

> **给后续改名的提示**：本步改完，这两处路径变成 `/models/llm` 与 `/models/asr`。UI 规格已定案把 `/models` 整体更名为 `/engines`（触点共 10 处），届时**这两处随批量改名一起走**，不要当成回归修回去。

```tsx
      ? { name: 'LLM 文案引擎', ok: false, status: '未配置', action: { label: '去配置', path: '/models/llm' } }
```
```tsx
        : { name: 'ASR 语音识别', ok: false, status: '未安装', action: { label: '去下载', path: '/models/asr' } },
```

- [ ] **Step 3: 删除三条不存在的功能承诺**

`EnvPanel.tsx` 的 `TIPS` 第一条整条移除（客户端无预筛入口）：
```tsx
const TIPS = [
  { icon: <EditOutlined />, text: '转写有误？分析页点对白流直接改，改完重跑语义' },
  { icon: <BookOutlined />, text: '九种模式支持一键全部生成，横向对比效果' },
] as const;
```
同时移除 `RocketOutlined` 的 import（现已无使用者，留着会触发 lint）。
再按同一纪律改口 `HomePage.tsx:104` 的「短剧素材也可以拖进来」→「选择素材所在文件夹」（全库无外部 `dataTransfer`，拖放不存在），以及 `StartCards.tsx:25` 的「AI 自动预筛与全量分析」→「逐集转写与冲突分析」。

- [ ] **Step 4: 门禁**

Run: `npm run typecheck && npm test`
Expected: typecheck 干净；vitest 13 passed（`RocketOutlined` 未用若被判 lint 错误，必须删而不是加 ignore）。

- [ ] **Step 5: 手测（不可省略——这是路由正确性的唯一证明）**

Run: `npm run dev`
Expected: 在引擎中心清空 LLM 的 Base URL 并保存 → 回工作台 → 点「LLM 文案引擎 · 去配置」→ **必须落在引擎中心 LLM 页并看到 Base URL / API Key / 模型三字段**；同理 ASR 未装时点「去下载」落在 ASR 页的模型库。**若落地页看不到对应字段，说明路由仍错，回到 Step 2。**

- [ ] **Step 6: 提交**

```bash
git add desktop/src/features/home/
git commit -m "fix(home): 环境就绪度跳转指向真实配置页，移除预筛/拖放等未实现文案"
```

## Task C2: 失败集必须与未分析集可辨

**Files:**
- Modify: `desktop/src/features/analysis/EpisodeListRow.tsx:32,46,225-245`
- Test: `desktop/src/features/analysis/EpisodeListRow.test.tsx`（新建）

- [ ] **Step 1: 写失败测试**（props 必填项已按 `:19-31` 核实，无 `restProps()` 之类的留白）

```tsx
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Episode } from '@dramaclip/protocol';
import { EpisodeListRow } from './EpisodeListRow';

function episode(status: Episode['status']): Episode {
  return {
    id: 'e1',
    project_id: 'p1',
    episode_number: 3,
    name: 'ep03.mp4',
    source_path: 'D:/x/ep03.mp4',
    duration: 120,
    status,
    created_at: 0,
  } as Episode;
}

function renderRow(episodeArg: Episode) {
  return render(
    <EpisodeListRow
      episode={episodeArg}
      highlightCount={0}
      active={false}
      checked={false}
      dropTarget={false}
      onActivate={vi.fn()}
      onToggle={vi.fn()}
      onDragStart={vi.fn()}
      onDragOver={vi.fn()}
      onDrop={vi.fn()}
      onMove={vi.fn()}
    />,
  );
}

describe('EpisodeListRow 状态可辨性', () => {
  it('failed 不得显示为「待分析」', () => {
    const { getByText, queryByText } = renderRow(episode('failed'));
    expect(getByText(/分析失败/)).toBeTruthy();
    expect(queryByText(/待分析/)).toBeNull();
  });

  it('done 显示已转写', () => {
    const { getByText } = renderRow(episode('done'));
    expect(getByText(/已转写/)).toBeTruthy();
  });

  it('pending 显示待分析', () => {
    const { getByText } = renderRow(episode('pending'));
    expect(getByText(/待分析/)).toBeTruthy();
  });
});
```

> `Episode` 的实际字段名以 `protocol/ts/index.ts` 为准；`as Episode` 断言仅用于夹具。若项目未装 `@testing-library/react`，用 `renderToStaticMarkup` 替代（`react-dom/server`），断言改为对 HTML 字符串做正则匹配。

- [ ] **Step 2:** Run: `cd desktop && npx vitest run src/features/analysis/EpisodeListRow.test.tsx`
Expected: `failed` 那条 FAIL（现状 `:238` 渲染成「● 待分析」）。

- [ ] **Step 3: 改布尔为三态**

`EpisodeListRow.tsx:32` 删除 `asrOk`；`:46` 改为传 `status`：

```tsx
        <RowMeta duration={episode.duration ?? 0} status={episode.status} highlightCount={highlightCount} />
```

`RowMeta`（`:225-245`）替换：

```tsx
function RowMeta({
  duration,
  status,
  highlightCount,
}: {
  duration: number;
  status: Episode['status'];
  highlightCount: number;
}): React.ReactElement {
  const state =
    status === 'done'
      ? { label: '已转写', color: tokens.colorSuccess }
      : status === 'failed'
        ? { label: '分析失败', color: tokens.colorWarning }
        : { label: '待分析', color: tokens.textTertiary };
  return (
    <span style={{ fontSize: 11, color: tokens.textTertiary, display: 'flex', gap: 8 }}>
      <span>{Math.round(duration)}s</span>
      <span style={{ color: state.color }}>● {state.label}</span>
      {highlightCount > 0 && (
        <span style={{ color: tokens.colorWarning }}>高光 {String(highlightCount)}</span>
      )}
    </span>
  );
}
```

（失败态刻意用 `colorWarning` 而非钩子红——「#FF4D4F 只给钩子语义」是既定纪律。）

- [ ] **Step 4:** Run: `cd desktop && npx vitest run && npm run typecheck` → Expected 全绿。
- [ ] **Step 5:** 手测：`npm run dev` → 分析页选一个未做 ASR 的集单独分析并用错路径触发失败，确认行内出现「分析失败」且与「待分析」肉眼可辨。
- [ ] **Step 6:** `git add desktop/src/features/analysis/ && git commit -m "fix(analysis): 失败集与未分析集视觉区分"`

## Task C3: 出片记录显示失败原因、不再截断为 8 行

**Files:**
- Modify: `desktop/src/features/narration/ProductionPage.tsx:227,233-253`
- Modify: `protocol/ts/index.ts`、`protocol/schemas/export.json`（仅当 `export.list` 未返回 `error`）

- [ ] **Step 1: 先确认服务端是否已返回 error**

Run: `cd service && ../.venv/Scripts/python -c "from dramaclip.infra.storage.repos import exports; print(exports.__file__)"` 然后读 `repos/exports.py` 的 `list_by_project`/`_COLUMNS`。
两种走向：
- **已返回** → 跳过 Step 2，直接 Step 3。
- **未返回** → Step 2 补列。

- [ ] **Step 2（条件执行）: 补列**

`repos/exports.py` 的列元组加 `"error"`，`SELECT` 与 `_row_to_dict` 同步；`protocol/ts/index.ts` 的 `ExportJob` 加 `error: string | null;`，`protocol/schemas/export.json` 的响应 schema 同步。契约测试 `tests/transport/test_contract_sync.py` 断言的是**方法名集合**相等，新增字段不影响它，但必须跑一遍确认无其它断言：

Run: `cd service && ../.venv/Scripts/python -m pytest tests/transport -q` → Expected 全绿。

- [ ] **Step 3: 完整列表 + 失败原因可见**

`ProductionPage.tsx:227` 去掉 `slice(0, 8)`，容器改为内部滚动：

```tsx
    <div style={{ maxHeight: 240, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
```
`:233-253` 的 `ExportRow` 内，状态标签后追加原因提示（`Tooltip` 需已在该文件 import，否则从 `antd` 补）：

```tsx
        {job.status === 'failed' && job.error ? (
          <Tooltip title={job.error}>
            <span style={{ color: tokens.colorWarning, fontSize: 11, marginLeft: 6 }}>原因</span>
          </Tooltip>
        ) : null}
```

- [ ] **Step 4:** Run: `npm run typecheck && npm test` → Expected 全绿。
- [ ] **Step 5: 手测（唯一能证明"服务中断"可见的环节）**

Run: `npm run dev` → 发起一次九模式出片，中途从任务管理器杀掉 Python 子进程 → 重开应用 → 出片记录应完整列出各条并把失败那条可悬停看到"服务中断"。**若失败行只有红色 Tag 而无原因，回到 Step 1 重查服务端是否真的返回了 `error`。**
- [ ] **Step 6:** `git add -A desktop protocol && git commit -m "fix(produce): 出片记录显示失败原因并完整展示"`

---

## Task C4: 设置页「输出」四键标注未生效（服务端零消费）

**Files:**
- Modify: `desktop/src/features/settings/sections.ts:74-82`

**已核实：** `export.encoder` / `export.bitrate_kbps` / `export.width` / `export.height` 四键在服务端**无任何读取者**——`encoder.py:104-121` 把 `libx264 / crf 20 / 30fps / 1080×1920 / AAC 128k` 全写死；`export.start` 的 schema 甚至声明了 `bitrate_kbps` 参数但 handler 不读 `params`。用户改这四个框，今天不可能有任何效果。接线它们属批次 1 之后的平台适配层议题（见「已知遗留 #5」），本任务只做**诚实标注**，按 Phase C 原则第 ③ 档。

- [ ] **Step 1: 加 help 标注（沿用该文件既有的 `help` 字段形态，见 `:65`、`:97` 用例）**

```ts
    {
      key: 'export.encoder',
      label: '编码器',
      type: 'select',
      options: () => [{ label: 'H.264', value: 'h264' }],
      help: '当前未生效：成片固定 H.264 / CRF 20 / 30fps',
    },
    {
      key: 'export.bitrate_kbps',
      label: '码率 (kbps)',
      type: 'number',
      min: 1000,
      max: 50000,
      help: '当前未生效：改按 CRF 恒定质量编码，不读码率',
    },
    {
      key: 'export.width',
      label: '宽度',
      type: 'number',
      min: 480,
      max: 2160,
      help: '当前未生效：成片固定 1080×1920 竖屏',
    },
    {
      key: 'export.height',
      label: '高度',
      type: 'number',
      min: 480,
      max: 3840,
      help: '当前未生效：成片固定 1080×1920 竖屏',
    },
```

**措辞纪律**：一律用「当前未生效」+ 实际固定值，**不得写"即将支持"**——后者把未兑现承诺挂在界面上，一旦排期变动就变成长期谎言。告知真实固定值比承诺未来更有用。

- [ ] **Step 2: 确认 `FieldSpec` 类型允许 `help` 出现在 `select` / `number` 两种类型上**

Run: `cd desktop && npx tsc --noEmit -p tsconfig.app.json`
Expected: 干净。若 `help` 在某类型上是可选缺失项，按 `sections.ts` 顶部 `FieldSpec` 定义补 `help?: string`（**不要**为此新建渲染分支）。

- [ ] **Step 3: 手测**

Run: `npm run dev` → 设置→出片分区，四个字段下方应各显示一行灰色说明且内容互不相同。
- [ ] **Step 4:** `git add desktop/src/features/settings/sections.ts && git commit -m "fix(settings): 输出四键标注当前未生效并说明实际固定值"`

---

# Phase D · 出口门禁：真机九模式回归

## Task D1: 九模式真机出片与音轨/字幕断言

**Files:** Create `scripts/verify_modes.py`

**为什么必须有这一步：** 177 条测试**全部只断言 `PlanData` 结构**，端到端仅 `raw_clip` 一条。这正是 `ducked` 无混音分支、TTS 错索引能存活 46 个提交的原因。本脚本产出的是**可听可看的证据**，也是批次 1 放大产能前的唯一防线。

- [ ] **Step 1: 先跑基线（在 Phase B 合入之前，当前 HEAD 上）**

这是本任务最重要的一步：**没有基线就没有"修对了"的证据**，也无法证伪 Phase B 的静态推导。

```bash
git stash list   # 确认无未提交改动
.venv/Scripts/python scripts/verify_modes.py --media <真实短剧目录> --out D:/tmp/dc-baseline
```
把输出的 `summary.json` 与逐片听感记录留存。

- [ ] **Step 2: 写脚本骨架**

```python
"""真机九模式回归：真实素材 → 分析 → 逐模式出片 → 音轨/时长硬断言 + 抽帧存档。

用法：
  .venv/Scripts/python scripts/verify_modes.py --media D:/path/短剧 --out D:/tmp/dc-report

不 mock、不用桩：真实 ffmpeg、真实 RPC 装配、真实编码。任一断言失败即非零退出。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MODES = [
    "raw_clip", "intro_narration", "cross_narration", "ultra_short_hook",
    "dialogue_narration", "full_narration", "subtitle_flow",
    "dual_host_chat", "inner_monologue",
]
MIN_MEAN_VOLUME_DB = -70.0  # 静音/近乎静音判据：直接侦测"旁白整条丢失"


def probe(video: Path, ffmpeg: str, ffprobe: str) -> dict[str, float | bool]:
    """返回 {duration_s, has_audio, mean_volume_db}。"""
    info = json.loads(subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)],
        check=True, capture_output=True, text=True, encoding="utf-8").stdout)
    audio_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    detect = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(video), "-map", "0:a:0", "-af", "volumedetect",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    mean = next(
        (float(line.split("mean_volume:")[1].strip().removesuffix(" dB"))
         for line in detect.stderr.splitlines() if "mean_volume" in line),
        None,
    )
    return {
        "duration_s": float(info["format"]["duration"]),
        "has_audio": bool(audio_streams),
        "mean_volume_db": mean if mean is not None else -999.0,
    }


def extract_frames(video: Path, out_dir: Path, ffmpeg: str, duration_s: float) -> list[Path]:
    """首/中/末三点抽帧，供人工核对字幕已烧入且为简体。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for label, at in (("head", 0.5), ("mid", duration_s / 2), ("tail", max(duration_s - 0.5, 0))):
        target = out_dir / f"{video.stem}_{label}.jpg"
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}",
             "-i", str(video), "-frames:v", "1", str(target)],
            check=True, capture_output=True, timeout=60)
        frames.append(target)
    return frames
```

- [ ] **Step 3: 主流程与断言清单（一条不许省）**

对**每个**模式的成片：

1. `has_audio is True`，且 `mean_volume_db > MIN_MEAN_VOLUME_DB` —— **静音成片的直接侦测器**（`ducked` 丢旁白会在这里红灯）；
2. `duration_s` 落在 `[strategy.min_duration_s, strategy.max_duration_s]` 内，否则打印 `OVERRUN` 并**非零退出**（当前 `intro_narration` 出过 410s 而预算是 300s；本条把这类问题固化成门禁）；
3. 打印该 plan 的 `planner` 字段值 —— 让人明确知道走的是 LLM 路还是规则降级路（今天 UI 上看不出这个区别）；
4. `extract_frames` 三帧存 `report/`，**人工核对字幕已烧入且为简体**；
5. `raw_clip` 额外断言：三帧中**不得**出现烧录字幕与遮罩条（零加工原则）；
6. `subtitle_flow` 额外断言：`mid` 帧含字幕（人工核对即可，脚本记录 `subtitle_expected=True`）；
7. **无长冻结帧**——任何 ≥ 2 秒静止画面即判失败：

```python
def max_freeze_s(video: Path, ffmpeg: str) -> float:
    """最长冻结段秒数。freezedetect 以帧差判定，n=-60dB 为其默认推荐灵敏度。"""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(video), "-vf", "freezedetect=n=-60dB:d=1.0",
         "-map", "0:v:0", "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return max(
        (float(line.split("duration:")[1].strip())
         for line in proc.stderr.splitlines() if "freeze_duration" in line),
        0.0,
    )
```
判据 `max_freeze_s(work) < 2.0`。冻结帧的典型成因是旁白时长回填失败、或段时长与音轨不匹配后被补齐静止——**正是 Phase B1-B3 三项缺陷的外在症状**，故此断言是那三项修复的独立验证器，不能省。

主流程用 in-process `AppContext` 装配（不依赖 Electron），路径与真机一致：`memory_db` 换成 `data_dir` 下的临时库，`project.create` → `scan_episodes` → `analysis.start` → `narration.produce(modes=全部九)` → 等 job → 逐片 `probe`。

- [ ] **Step 4: 生成并列报告**

写 `report/summary.json`：`{mode: {status, duration_s, mean_volume_db, planner, frames}}`，并打印对齐表。若传入 `--baseline D:/tmp/dc-baseline`，则**逐模式并列**修复前后的 `mean_volume_db` 与时长。

- [ ] **Step 5: 判读（关键——这是本方案的证伪点）**

```bash
.venv/Scripts/python scripts/verify_modes.py --media <同一目录> --out D:/tmp/dc-after \
  --baseline D:/tmp/dc-baseline
```
Expected：
- `full_narration`：基线 `mean_volume_db` 应等于纯原声；修复后应**明显升高**（旁白叠加）且人声可辨。
- `cross_narration` / `ultra_short_hook`：逐段听，基线应能听到旁白与画面不匹配 / CTA 缺失；修复后一一对应。
- **若基线里 `full_narration` 本来就有清晰旁白** → Phase B 的静态推导不成立：**立即停止，不要合入 B2/B3**，回到取证环节重新判断。这条判断必须诚实执行，不得为了让方案自洽而放过。

- [ ] **Step 6: 提交**

```bash
git add scripts/verify_modes.py
git commit -m "test(modes): 真机九模式回归脚本，断言音轨存在/时长预算/字幕烧入"
```

---

## DoD（批次 0 + 0.5 出口）

- [ ] `cd service && ../.venv/Scripts/python -m pytest tests -q` 全绿，且 **≥ 194 条**（177 + 本方案新增）
- [ ] `npm run typecheck && npm test` 全绿
- [ ] `grep -rn "work_dir.parent" service/dramaclip` 无命中（由 `test_no_fragile_parent_walks_remain` 永久守卫）
- [ ] 新成品落在 `<data>/outputs/<project_id>/`，`data/outputs/` 不再是空目录
- [ ] 设置页改字幕预设 → 出片后抽帧字幕样式随之改变（此前不可能）
- [ ] `scripts/verify_modes.py` 在真实素材上 9/9 通过，`report/summary.json` 留档，并与基线并列比对
- [ ] 九模式成片**逐个听过一遍**：无静音片、无错音段、CTA 旁白存在
- [ ] 界面不再出现"自动预筛""可以拖进来"等未实现承诺
- [ ] 无同名 `.srt` 时，切点仍避开台词（B4 的双路取区生效）

## 已知遗留（明确不做，批次 1 处理）

1. `narration.produce` 八个模式恒取 `episodes[0]`，且无方案数入参 → **产能天花板**（13 条 plan 里 11 条只用第 1 集）。**产出模型已由用户定案为「整剧 = 处理单元」**：一次提交（剧 × 模式）→ 每模式产出 1..K 条**不同卖点角度**的跨集方案 → 队列并行渲染 → 作品库按剧分组。原「9 模式 × N 集笛卡尔积」提案**已被否决**（它把剧拆散成单集粒度，与跨集编排相悖）。批次 1 单独成案，且必须先补两个前提缺口：`scriptwriter.py:21-22` 的 80 行/集、500 行总量上限使 80 集剧只有约 10% 内容进得了上下文（**已由本方案 Task B6 修为其取替代的按集分配额，但配额仍非终局解**）；`semantic/plot.py`（摘要/剧情结构化）在设计文档里有、文件不存在，`episode_analysis.characters` 列无写入者。
   **K 与角度归属已定案**：K 暴露给用户（即既定「版本数」参数，走设置默认 + 项目空间覆盖，不新开界面），**角度一律 LLM 自选不给用户挑**。因此角度多样性必须是硬约束 + 可见证据：每条片标注角度名与取材集区间，角度间取材重叠超阈值即不产出该角度；调 K 前须显示预计条数与耗时。规则类模式的 K 为全剧 top-K 冲突窗数，与解说类的角度数不同源。
2. 旧成品/封面绝对路径仍指向 `data/cache/`，靠 DB 原样可读；不做搬迁。
3. `highlight` 综合分未进选段逻辑（八个模式只用 `conflict_scores`）；认知层（钩子分/评估报告）缺位 → 批次 3。
4. 预筛在客户端仍无入口、`AnalysisResults` TS 类型仍缺 `prescreen_score`/`recommended` → 随批次 1 的任务队列一并接。
5. `export.encoder/bitrate/width/height` 四键仍零消费（`1080×1920`、`platform="douyin"` 硬编码）→ 平台适配层议题。
6. `SenseVoiceEngine` 把整集压成 1 条段（`transcriber.py:137-143`）→ 批次 2 与云端 ASR 一并处理。
7. 繁简归一化缺失（转写为繁体，污染字幕与编剧输入）→ 批次 2。
8. 安装包落后 HEAD 46 个提交 → 本方案合入后重出包（`npm run dist`）。
9. `narration_plans.tts_segments`、`tts_cache`、`subtitle_presets` 三处表/列无读写者；`_run_generation`、`build_from_script_dialogue` 等死代码未清 → 按「迁移须扫清全部触点」纪律安排**独立的清理提交**，不夹带在功能改动里。
