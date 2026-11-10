# 批次二 · 自进化闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地改进报告批次二的 6 项（#6–#11）：harness 内容 ID 对账 + A/B 四态、健康线、分享率、时长分桶、VL 钩子两策略、IAA 话术库。

**Architecture:** harness 报告基座（`export.publish_report` 只读聚合 RPC + 成品库「数据报告」抽屉）随本批落地——#6–#9 的「进报告」都预设它存在（裁决 P-R1）。聚合/四态全是纯函数（`api/export_report.py`），原料查询单点走 `exports_repo.list_publish_entries`；回流录入扩展三个可选字段（分享数/前3秒留存/作品ID）+ 保守对账拒录。VL 与六维只做 prompt/parser 增量；IAA 话术是静态用户自选库，服务端单持，两个复制面统一改吃 `publish_pack` 快照（顺带闭批次一遗留 M3）。

**Tech Stack:** Python 3.13（service/，pytest+ruff）、React 19 + TS 5.9 strict + AntD 6（desktop/，vitest）、@dramaclip/protocol 共享类型 + JSON Schema x-methods 契约。

**Spec:** `docs/research/2026-11-09-improvement-proposal.md` §5 批次二（项 6–11）；harness 上位规格 `specs/2026-10-23-data-feedback-harness.md`（§2 指标口径/§4 信号纪律/§5 只读报告）；VL 主线衔接 `specs/2026-10-26-v0.2.4-scope.md` 主线第 2 项。

## Global Constraints

以下裁决与纪律对每个任务隐式生效，违反即返工：

- **P-R1（范围裁决）**：harness 规格 §6 第一步（报告 RPC + 界面表）是本批必需依赖，随 T2/T3 落地；第二步（句式分类器）与第三步（权重调整工作流）**不在本批**（v0.2.4 主线并行项，YAGNI）。
- **P-R2（「免费」冲突裁决）**：`titles._BANNED_PHRASES` 含「免费」**不动**——它拦的是 LLM 产出的平台违禁腔。IAA 话术库是**静态、用户显式自选**的物料，在 LLM 门禁之后由服务端追加，不过标题门禁；默认无话术（现状不变）。不按片单付费性自动分支（三列录入裁决）。
- **P-R3（#10 落点裁决）**：VL 开场钩子画面选择器（v0.2.4 主线第 2 项）未实施；本批只做 prompt + parser 增量——帧 JSON 加 `hook_strategy` 字段（视觉悖论/身份快照/无），旧分析缺字段容忍为「无」；标题 visual_hooks 行带策略后缀。选择器落地时直接消费该字段。不上新模型。
- **P-R4（A/B 初始阈值）**：同项目+同平台、发布日期差 ≤72h（published_at 只录到日，按 3 天计）、双方发布满 72h 且 plays≥500 才比较；|Δ完播| <5pp = 差异不明显，≥5pp = 方向性领先。5pp 是初始值，报告标注待回流校准。四态文案钉死：「等待/证据不足/差异不明显/方向性领先」。
- **P-R5（健康线）**：前 3 秒留存 ≥32%、整体完播 ≥30%，报告标注「通用基准初始值，回流数据足够后自建校准」；低于线只输出静态建议文案（钩子重选/时长分析），**不自动调权**（自进化第三层明确不做）。
- **P-R6（对账保守）**：`video_id` 同平台已绑另一条成片 → 拒录（宁拒不错配）；同一条成片重录覆盖（W8 现状）；作品 ID 缺省不强制。
- **时长让位故事**：#9 只做分析维度，不恢复任何时长上下限硬约束（2026-09 裁决）。
- **不动六维结构**：#8 只补锚点文案，WEIGHTS 六键与权重值一字不动（有变异测试钉死）。
- **同一含义不得第二处真相源**：话术库只在 `publish_pack.CTA_VARIANTS` 定义（前端经 RPC 读选项）；聚合口径只在 `export_report` 定义；两个复制面（逐平台复制/清单一键复制）都吃 `publish_pack` 服务端快照。
- **契约门禁**：新 RPC 必须三处同步——`protocol/ts/index.ts` METHOD_NAMES、`protocol/schemas/*.json` x-methods、服务端 register；`test_contract_sync.py` 与桌面 contract.test.ts 任一不同步即红。
- **样式门禁**：desktop 新组件不得出现裸 rgba(/hex（theme.ts 外），一律 tokens；copyTruth 红线词（指纹/特征向量/同质化/排重/抗比对/消重/绕过平台等）不得进界面文案与 docs/（docs/superpowers/** 豁免）。
- **注释纪律**：只写「为什么是这个值/这个顺序」；批次经过、事故日期、文件指针进提交信息与文档。
- **测试纪律**：纯函数/校验在单测钉死（含变异锚点）；真实 LLM/VL 往返与真实发布数据读数只在真机 DoD（文末）。不得以单测绿冒充真机验证。
- **并行会话 git 协议**： staging 只按显式路径；提交前 `git status`、提交后 `git show --stat HEAD` + `git log --oneline -2` 核实；外来改动留在工作区不卷走；混合文件停报 BLOCKED 由控制者裁决。
- **测试命令**：service 用 `../.venv/Scripts/python -m pytest tests/<path> -v`、`../.venv/Scripts/ruff check dramaclip tests`（cwd=service）；desktop 用 `npx vitest run <path>`、`npm run typecheck`、`npm run lint`（cwd=desktop）。管道会吞退出码——读输出实质，不看 exit code。

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `service/dramaclip/api/export.py` | 修改 | 录入扩展三字段 + 对账拒录 + 注册 publish_report/ab_report |
| `service/dramaclip/api/export_report.py` | 新建 | harness 纯函数：维度聚合/健康线/A/B 四态（T2 建，T4 扩） |
| `service/dramaclip/infra/storage/repos/exports.py` | 修改 | find_video_id_conflict + list_publish_entries |
| `service/dramaclip/engines/narration/variant_scoring.py` | 修改 | cta_pull 锚点补转发语判据（仅 prompt） |
| `service/dramaclip/engines/vision/runtime.py` | 修改 | hook_strategy prompt/parser + hook_label |
| `service/dramaclip/api/narration.py` | 修改 | visual_hooks 策略后缀 + set_cta RPC + cta_id  preservation |
| `service/dramaclip/engines/narration/publish_pack.py` | 修改 | CTA_VARIANTS + build_pack cta 参数 |
| `protocol/ts/index.ts` | 修改 | PublishData/PublishMeta/PlatformPack 扩展 + 报告类型 + METHOD_NAMES ×3 |
| `protocol/schemas/export.json` / `narration.json` | 修改 | 录入新字段 + 三个新 method 条目 |
| `desktop/src/services/client.ts` | 修改 | setPublishData 扩展 + publishReport/abReport/setCta |
| `desktop/src/features/works/WorksDetailPage.tsx` | 修改 | 录入表单三字段 + 清单组件改传 planId |
| `desktop/src/features/works/PublishReportDrawer.tsx` | 新建 | 数据报告抽屉（维度聚合 + 健康线 + 对照实验） |
| `desktop/src/features/works/WorksPage.tsx` | 修改 | 「数据报告」入口按钮 |
| `desktop/src/features/works/PlatformPackSection.tsx` | 修改 | 话术选择器 |
| `desktop/src/features/works/PublishChecklistSection.tsx` | 修改 | 复制改吃 publish_pack 快照（闭 M3） |
| `desktop/src/features/works/publishCopy.ts` | 修改 | buildPublishCopy(pack) 单参 |

任务序：T1 → T2 → T3 → T4 → T5 → T6 → T7（T5/T6/T7 与前四任务无依赖，但按序执行）。

---

### Task 1: 回流录入扩展——分享数/前3秒留存/作品ID + 保守对账

**Files:**
- Modify: `service/dramaclip/api/export.py`（set_publish_data，现 342–384 行）
- Modify: `service/dramaclip/infra/storage/repos/exports.py`（尾部新增查询）
- Modify: `protocol/ts/index.ts`（PublishData，现 485–496 行）
- Modify: `protocol/schemas/export.json`（export.set_publish_data 的 data properties，现 688 行起）
- Modify: `desktop/src/services/client.ts`（setPublishData 参数类型，现 227–240 行）
- Modify: `desktop/src/features/works/WorksDetailPage.tsx`（PublishDataSection，现 373 行起）
- Test: `service/tests/api/test_export_publish_data.py`（追加用例）

**Interfaces:**
- Consumes: W8 现状 `set_publish_data(context, params)`、`exports_repo.get/set_publish_data`、`_PUBLISH_PLATFORMS`、`_ERR_PUBLISH_DATA = -32410`。
- Produces: `exports_repo.find_video_id_conflict(conn, platform: str, video_id: str, *, exclude_id: str) -> str | None`；publish_data JSON 新增可空键 `shares: int | None`、`retention_3s: float | None`、`video_id: str | None`（T2/T4 消费）。

- [ ] **Step 1: 写失败测试（追加到 test_export_publish_data.py）**

复用本文件现有 `_seed/_context/_valid_data`（注意 `_seed` 每次新建一个项目，可调两次得两条独立成片）：

```python
def test_extended_fields_roundtrip(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_id = _seed(memory_db, tmp_path)
    result = export_api.set_publish_data(
        _context(memory_db),
        {"export_id": export_id, "data": {
            **_valid_data(), "shares": 45, "retention_3s": 41.256,
            "video_id": "https://v.douyin.com/abc/",
        }},
    )
    stored = result["publish_data"]
    assert stored["shares"] == 45
    assert stored["retention_3s"] == 41.26, "与 retention_pct 同口径 round 2"
    assert stored["video_id"] == "https://v.douyin.com/abc/"


def test_extended_fields_default_none(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_id = _seed(memory_db, tmp_path)
    result = export_api.set_publish_data(
        _context(memory_db), {"export_id": export_id, "data": _valid_data()}
    )
    stored = result["publish_data"]
    assert stored["shares"] is None and stored["retention_3s"] is None
    assert stored["video_id"] is None, "可选字段缺省为 None，不编 0/空串"


def test_rejects_bad_extended_fields(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_id = _seed(memory_db, tmp_path)
    context = _context(memory_db)
    bad = [
        {"shares": -1}, {"shares": "abc"}, {"retention_3s": 101},
        {"retention_3s": -0.5}, {"retention_3s": "x"}, {"video_id": "字" * 201},
    ]
    for extra in bad:
        with pytest.raises(RpcDomainError) as exc_info:
            export_api.set_publish_data(
                context, {"export_id": export_id, "data": {**_valid_data(), **extra}}
            )
        assert exc_info.value.code == -32410, extra
    row = exports_repo.get(memory_db, export_id)
    assert row is not None and row["publish_data"] is None, "拒收的脏数据一个都不落库"


def test_video_id_conflict_conservative(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    export_a = _seed(memory_db, tmp_path)
    export_b = _seed(memory_db, tmp_path)
    context = _context(memory_db)
    data = {**_valid_data(), "video_id": "douyin-123"}
    export_api.set_publish_data(context, {"export_id": export_a, "data": data})
    # 同平台同作品 ID 绑另一条成片 → 宁拒不错配
    with pytest.raises(RpcDomainError) as exc_info:
        export_api.set_publish_data(context, {"export_id": export_b, "data": data})
    assert exc_info.value.code == -32410
    assert exports_repo.get(memory_db, export_b)["publish_data"] is None
    # 同一条成片重录同 ID → 覆盖（W8 现状），排除自身不算冲突
    export_api.set_publish_data(
        context, {"export_id": export_a, "data": {**data, "plays": 999}}
    )
    assert exports_repo.get(memory_db, export_a)["publish_data"]["plays"] == 999
    # 跨平台同 ID → 不冲突（平台各自编号）
    export_api.set_publish_data(
        context, {"export_id": export_b, "data": {**data, "platform": "快手"}}
    )
    assert exports_repo.get(memory_db, export_b)["publish_data"]["video_id"] == "douyin-123"
```

- [ ] **Step 2: 跑测试确认红**

Run: `../.venv/Scripts/python -m pytest tests/api/test_export_publish_data.py -v`（cwd=service）
Expected: 新 4 用例 FAIL（KeyError: 'shares' / 未拒收）；旧 4 用例仍 PASS。

- [ ] **Step 3: 实现——repo 查询 + RPC 扩展**

`repos/exports.py` 尾部追加（JSON1 json_extract 对 NULL publish_data 得 NULL，自然不匹配）：

```python
def find_video_id_conflict(
    conn: sqlite3.Connection, platform: str, video_id: str, *, exclude_id: str
) -> str | None:
    """对账保守（P-R6）：同平台同作品 ID 已绑别的成片 → 返回其 id；排除自身重录。"""
    row = conn.execute(
        "SELECT id FROM export_jobs WHERE id != ?"
        " AND json_extract(publish_data, '$.platform') = ?"
        " AND json_extract(publish_data, '$.video_id') = ? LIMIT 1",
        (exclude_id, platform, video_id),
    ).fetchone()
    return str(row[0]) if row is not None else None
```

`api/export.py` set_publish_data：plays/retention 的 try 块扩两键，likes 校验之后插入新校验，data 字典加三键：

```python
    try:
        plays = int(str(raw.get("plays")))
        retention = float(str(raw.get("retention_pct")))
        shares = None if raw.get("shares") in (None, "") else int(str(raw.get("shares")))
        retention_3s = (
            None if raw.get("retention_3s") in (None, "") else float(str(raw.get("retention_3s")))
        )
    except (TypeError, ValueError) as exc:
        raise RpcDomainError(
            _ERR_PUBLISH_DATA,
            f"plays/retention_pct 必填且为数字（shares/retention_3s 选填数字）: {exc}",
        ) from exc
```

（plays/retention/likes 原有范围校验不动；其后追加：）

```python
    if shares is not None and shares < 0:
        raise RpcDomainError(_ERR_PUBLISH_DATA, "shares ≥ 0")
    if retention_3s is not None and not 0 <= retention_3s <= 100:
        raise RpcDomainError(_ERR_PUBLISH_DATA, "retention_3s ∈ [0, 100]")
    video_id = str(raw.get("video_id") or "").strip() or None
    if video_id is not None:
        if len(video_id) > 200:
            raise RpcDomainError(_ERR_PUBLISH_DATA, "video_id 过长（≤200 字符）")
        conflict = exports_repo.find_video_id_conflict(
            context.conn, platform, video_id, exclude_id=export_id
        )
        if conflict is not None:
            raise RpcDomainError(
                _ERR_PUBLISH_DATA, f"作品 ID 已绑定另一条成片 {conflict}：宁拒录，不错配"
            )
```

data 字典改为：

```python
    data = {
        "platform": platform,
        "plays": plays,
        "retention_pct": round(retention, 2),
        "likes": likes,
        "shares": shares,
        "retention_3s": None if retention_3s is None else round(retention_3s, 2),
        "video_id": video_id,
        "published_at": published_at,
        "recorded_at": _now_ms(),
    }
```

- [ ] **Step 4: 协议三处同步**

`protocol/ts/index.ts` PublishData 加（likes 之后）：

```ts
  readonly likes?: number | null;
  /** 分享数（可选；视频号社交裂变主指标，报告批二#8）。 */
  readonly shares?: number | null;
  /** 前 3 秒留存百分数 0-100（可选；健康线判据，报告批二#7）。 */
  readonly retention_3s?: number | null;
  /** 平台作品 ID/链接（可选；同平台唯一，对账拒配，报告批二#6）。 */
  readonly video_id?: string | null;
```

`protocol/schemas/export.json` set_publish_data 的 data.properties 加：

```json
                  "shares": { "type": "integer", "minimum": 0 },
                  "retention_3s": { "type": "number", "minimum": 0, "maximum": 100 },
                  "video_id": { "type": "string", "maxLength": 200 }
```

`desktop/src/services/client.ts` setPublishData 的 data 类型加 `shares?: number | null; retention_3s?: number | null; video_id?: string | null;`。

- [ ] **Step 5: 录入表单三字段**

`WorksDetailPage.tsx` PublishDataSection：antd 导入加 `Input`；state 区加（仿 likes 行）：

```tsx
  const [shares, setShares] = useState<number | null>(existing?.shares ?? null);
  const [retention3s, setRetention3s] = useState<number | null>(existing?.retention_3s ?? null);
  const [videoId, setVideoId] = useState(existing?.video_id ?? '');
```

save() 的 setPublishData 载荷加 `shares, retention_3s: retention3s, video_id: videoId.trim() === '' ? null : videoId.trim(),`。 likes 的 InputNumber 之后、DatePicker 之前插入：

```tsx
        <InputNumber
          size="small"
          min={0}
          placeholder="分享(选填)"
          value={shares}
          onChange={(value) => { setShares(typeof value === 'number' ? value : null); }}
          style={{ width: 112 }}
        />
        <InputNumber
          size="small"
          min={0}
          max={100}
          placeholder="前3秒留存(选填)"
          value={retention3s}
          onChange={(value) => { setRetention3s(typeof value === 'number' ? value : null); }}
          suffix="%"
          style={{ width: 160 }}
        />
        <Input
          size="small"
          placeholder="作品ID/链接(选填)"
          value={videoId}
          onChange={(event) => { setVideoId(event.target.value); }}
          style={{ width: 180 }}
        />
```

- [ ] **Step 6: 跑测试确认绿 + 门禁**

Run: `../.venv/Scripts/python -m pytest tests/api/test_export_publish_data.py tests/transport/test_contract_sync.py -v`（cwd=service）→ 全 PASS
Run: `../.venv/Scripts/ruff check dramaclip tests` → 净
Run: `npm run typecheck`（cwd=desktop）→ 净
Run: `npx vitest run src/features/works src/__tests__/contract.test.ts`（cwd=desktop）→ 全 PASS

- [ ] **Step 7: Commit**

```bash
git add service/dramaclip/api/export.py service/dramaclip/infra/storage/repos/exports.py service/tests/api/test_export_publish_data.py protocol/ts/index.ts protocol/schemas/export.json desktop/src/services/client.ts desktop/src/features/works/WorksDetailPage.tsx
git commit -m "feat(harness): 回流录入扩分享数/前3秒留存/作品ID+同平台ID对账拒配（批二#6/#7/#8 数据面）"
```

---

### Task 2: harness 报告基座——publish_report 聚合 RPC（含时长分桶/健康线/分享率）

**Files:**
- Create: `service/dramaclip/api/export_report.py`
- Modify: `service/dramaclip/infra/storage/repos/exports.py`（list_publish_entries）
- Modify: `service/dramaclip/api/export.py`（register + handler + `_ERR_REPORT_PARAM = -32412`）
- Modify: `protocol/ts/index.ts`（报告类型 + METHOD_NAMES）
- Modify: `protocol/schemas/export.json`（x-methods 新条目）
- Test: `service/tests/api/test_export_report.py`（新建）

**Interfaces:**
- Consumes: T1 的 publish_data 新键；`narration_plans.plan_data` JSON 含 `arc`（models.py:82）、`np.angle` 列；`e.narration_mode`、`e.duration_s`。
- Produces: `export_report.DIMENSIONS = ("mode", "arc", "angle", "platform", "duration_bucket")`；`aggregate(entries, dimension) -> dict`；`health(entries) -> dict`；`duration_bucket(float|None) -> str`；`exports_repo.list_publish_entries(conn) -> list[dict]`（行键：export_id/project_id/project_name/mode/angle/arc/duration_s/platform/plays/retention_pct/likes/shares/retention_3s/published_at/video_id）；RPC `export.publish_report({dimension}) -> {dimension, rows, recorded, zero_plays_excluded, health}`。T3 消费 RPC 形状，T4 在本模块追加 ab_pairs。

- [ ] **Step 1: 写失败测试（新建 test_export_report.py）**

```python
"""harness 聚合（批二#7/#8/#9）：中位数/信号纪律/离群点名/健康线——纯函数钉死。

变异锚点：均值换中位数即红（偏态集）；灰黄边界 n=9/10/29/30 四点钉；
plays=0 剔除、缺失辅指标不补 0、方案断链标不可考，各有专杀用例。
"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.api import export_report


def _entry(export_id: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "export_id": export_id, "project_id": "p1", "project_name": "剧一",
        "mode": "full_narration", "angle": "逆袭", "arc": "triumph",
        "duration_s": 60.0, "platform": "抖音", "plays": 1000,
        "retention_pct": 30.0, "likes": None, "shares": None,
        "retention_3s": None, "published_at": None, "video_id": None,
    }
    return {**base, **over}


def test_median_not_mean() -> None:
    rows = [_entry(f"e{i}", retention_pct=v) for i, v in enumerate([10, 12, 14, 16, 200])]
    # 200 离群 >2σ：点名且不进中位数
    result = export_report.aggregate(rows, "mode")
    row = result["rows"][0]
    assert row["median_retention_pct"] == 13.0, "中位数抗爆款绑架；均值 50.4 即红"
    assert row["outliers"] == ["e4"]


def test_signal_boundaries() -> None:
    for n, signal in [(9, "gray"), (10, "yellow"), (29, "yellow"), (30, "ok")]:
        rows = [_entry(f"e{i}") for i in range(n)]
        assert export_report.aggregate(rows, "mode")["rows"][0]["signal"] == signal, n


def test_zero_plays_excluded_and_missing_rates() -> None:
    rows = [
        _entry("e0", plays=0),
        _entry("e1", likes=100, shares=10),
        _entry("e2"),
    ]
    result = export_report.aggregate(rows, "mode")
    assert result["recorded"] == 3 and result["zero_plays_excluded"] == 1
    row = result["rows"][0]
    assert row["n"] == 2
    assert row["like_rate"] == 0.1, "缺失 likes 的条目剔除，不补 0（补 0 则 0.05）"
    assert row["share_rate"] == 0.01


def test_untraceable_bucket() -> None:
    rows = [_entry("e1", arc=None, angle=None)]
    result = export_report.aggregate(rows, "arc")
    assert result["rows"][0]["value"] == "不可考", "方案断链：投票真，骨架不可考"


def test_duration_bucket_boundaries() -> None:
    assert export_report.duration_bucket(None) == "未知"
    assert export_report.duration_bucket(29.9) == "<30s"
    assert export_report.duration_bucket(30.0) == "30-60s"
    assert export_report.duration_bucket(59.9) == "30-60s"
    assert export_report.duration_bucket(60.0) == "60-90s"
    assert export_report.duration_bucket(89.9) == "60-90s"
    assert export_report.duration_bucket(90.0) == "90s+"
    rows = [_entry("e1", duration_s=45.0), _entry("e2", duration_s=75.0)]
    values = [r["value"] for r in export_report.aggregate(rows, "duration_bucket")["rows"]]
    assert set(values) == {"30-60s", "60-90s"}


def test_health_lines_and_suggestions() -> None:
    rows = [
        _entry("e1", retention_3s=20.0, retention_pct=25.0),
        _entry("e2", retention_3s=40.0, retention_pct=35.0),
        _entry("e3", retention_pct=28.0),
    ]
    h = export_report.health(rows)
    assert h["line_3s"] == 32.0 and h["line_retention"] == 30.0
    assert "校准" in h["note"], "通用基准必须标注待回流校准"
    by_id = {(b["export_id"], b["metric"]): b for b in h["below"]}
    assert ("e1", "retention_3s") in by_id and "钩子重选" in by_id[("e1", "retention_3s")]["suggestion"]
    assert ("e1", "retention_pct") in by_id and "时长分析" in by_id[("e1", "retention_pct")]["suggestion"]
    assert ("e3", "retention_pct") in by_id
    assert ("e3", "retention_3s") not in by_id, "未录前3秒不判线，不编数据"
    assert not any(b["export_id"] == "e2" for b in h["below"])


def test_unknown_dimension_raises() -> None:
    with pytest.raises(ValueError):
        export_report.aggregate([], "watch_score")
```

- [ ] **Step 2: 跑测试确认红**

Run: `../.venv/Scripts/python -m pytest tests/api/test_export_report.py -v`（cwd=service）
Expected: FAIL（ModuleNotFoundError: export_report）。

- [ ] **Step 3: 实现纯函数模块**

新建 `service/dramaclip/api/export_report.py`：

```python
"""harness 只读聚合（specs/2026-10-23-data-feedback-harness.md §2/§4/§5）。

中位数抗爆款绑架；plays=0 剔除；辅指标缺失条目不补 0；离群 >2σ 点名不进中位。
健康线/差异阈值是通用基准初始值，标注待回流自建校准；建议只输出文案，不自动调权
（自进化第三层明确不做）。
"""

from __future__ import annotations

import statistics
from typing import Any

DIMENSIONS = ("mode", "arc", "angle", "platform", "duration_bucket")

HEALTH_3S = 32.0
HEALTH_RETENTION = 30.0
HEALTH_NOTE = "通用基准初始值，回流数据足够后自建校准"


def duration_bucket(duration_s: float | None) -> str:
    if duration_s is None:
        return "未知"
    if duration_s < 30:
        return "<30s"
    if duration_s < 60:
        return "30-60s"
    if duration_s < 90:
        return "60-90s"
    return "90s+"


def _key(row: dict[str, Any], dimension: str) -> str:
    if dimension == "duration_bucket":
        return duration_bucket(row.get("duration_s"))
    if dimension == "platform":
        return str(row["platform"])
    return str(row.get(dimension) or "不可考")


def _median_rate(rows: list[dict[str, Any]], field: str) -> float | None:
    ratios = [float(r[field]) / r["plays"] for r in rows if r.get(field) is not None]
    return round(statistics.median(ratios), 4) if ratios else None


def aggregate(entries: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
    if dimension not in DIMENSIONS:
        raise ValueError(f"dimension 必须是 {'/'.join(DIMENSIONS)} 之一")
    valid = [r for r in entries if r["plays"] > 0]
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in valid:
        groups.setdefault(_key(row, dimension), []).append(row)
    rows: list[dict[str, Any]] = []
    for value, members in groups.items():
        rets = [float(r["retention_pct"]) for r in members]
        mean = statistics.mean(rets)
        sigma = statistics.pstdev(rets)
        outliers = [
            r for r in members
            if sigma > 0 and abs(float(r["retention_pct"]) - mean) > 2 * sigma
        ]
        kept = [r for r in members if r not in outliers]
        n = len(members)
        rows.append({
            "value": value,
            "n": n,
            "median_retention_pct": (
                round(statistics.median([float(r["retention_pct"]) for r in kept]), 2)
                if kept else None
            ),
            "like_rate": _median_rate(members, "likes"),
            "share_rate": _median_rate(members, "shares"),
            "signal": "gray" if n < 10 else "yellow" if n < 30 else "ok",
            "outliers": [str(r["export_id"]) for r in outliers],
        })
    rows.sort(key=lambda r: (
        r["median_retention_pct"] is None, -(r["median_retention_pct"] or 0.0), r["value"]
    ))
    return {
        "dimension": dimension,
        "rows": rows,
        "recorded": len(entries),
        "zero_plays_excluded": len(entries) - len(valid),
    }


def health(entries: list[dict[str, Any]]) -> dict[str, Any]:
    below: list[dict[str, Any]] = []
    for row in entries:
        if row["plays"] <= 0:
            continue
        r3 = row.get("retention_3s")
        if r3 is not None and float(r3) < HEALTH_3S:
            below.append({
                "export_id": str(row["export_id"]),
                "project_name": str(row["project_name"]),
                "metric": "retention_3s",
                "value": float(r3),
                "suggestion": "钩子重选：前3秒留存低于基准，开场钩子没留住人",
            })
        if float(row["retention_pct"]) < HEALTH_RETENTION:
            below.append({
                "export_id": str(row["export_id"]),
                "project_name": str(row["project_name"]),
                "metric": "retention_pct",
                "value": float(row["retention_pct"]),
                "suggestion": "时长分析：完播低于基准，可切到时长分桶维度对照",
            })
    return {
        "line_3s": HEALTH_3S,
        "line_retention": HEALTH_RETENTION,
        "note": HEALTH_NOTE,
        "below": below,
    }
```

- [ ] **Step 4: 原料查询 + RPC 接线**

`repos/exports.py` 追加（文件已 import json；STATUS_COMPLETED 已在模块内）：

```python
def list_publish_entries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """harness 聚合原料：有回流账的已完成成片 + 方案归因（LEFT JOIN 断链标不可考）。"""
    rows = conn.execute(
        "SELECT e.id, e.project_id, p.name, e.narration_mode, e.duration_s,"
        " e.publish_data, np.angle, np.plan_data"
        " FROM export_jobs e JOIN projects p ON p.id = e.project_id"
        " LEFT JOIN narration_plans np ON np.id = e.narration_plan_id"
        " WHERE e.status = ? AND e.publish_data IS NOT NULL",
        (STATUS_COMPLETED,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = _parse_publish(row[5])
        if data is None:
            continue
        plan = json.loads(row[7]) if row[7] else {}
        out.append({
            "export_id": str(row[0]),
            "project_id": str(row[1]),
            "project_name": str(row[2]),
            "mode": row[3],
            "duration_s": row[4],
            "angle": row[6],
            "arc": plan.get("arc") if isinstance(plan, dict) else None,
            "platform": data.get("platform"),
            "plays": int(data.get("plays") or 0),
            "retention_pct": float(data.get("retention_pct") or 0),
            "likes": data.get("likes"),
            "shares": data.get("shares"),
            "retention_3s": data.get("retention_3s"),
            "published_at": data.get("published_at"),
            "video_id": data.get("video_id"),
        })
    return out
```

`api/export.py`：错误码区加 `_ERR_REPORT_PARAM = -32412  # 报告维度词表外（harness）`；register 加一行；handler：

```python
def publish_report(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """harness 只读报告：聚合事实摆出来，调权永远人拍板（规格 §5）。"""
    from dramaclip.api import export_report

    dimension = str(params.get("dimension") or "mode")
    if dimension not in export_report.DIMENSIONS:
        raise RpcDomainError(
            _ERR_REPORT_PARAM, f"dimension 必须是 {'/'.join(export_report.DIMENSIONS)} 之一"
        )
    entries = exports_repo.list_publish_entries(context.conn)
    return {**export_report.aggregate(entries, dimension), "health": export_report.health(entries)}
```

register 行：`router.register("export.publish_report", lambda params: publish_report(context, params))`

- [ ] **Step 5: 协议同步**

`protocol/ts/index.ts` 类型区加：

```ts
/** harness 聚合行（export.publish_report）：灰 <10 / 黄 10-30 / ok ≥30；离群点名不进中位。 */
export interface PublishReportRow {
  readonly value: string;
  readonly n: number;
  readonly median_retention_pct: number | null;
  readonly like_rate: number | null;
  readonly share_rate: number | null;
  readonly signal: 'gray' | 'yellow' | 'ok';
  readonly outliers: string[];
}

export interface PublishHealthItem {
  readonly export_id: string;
  readonly project_name: string;
  readonly metric: 'retention_3s' | 'retention_pct';
  readonly value: number;
  readonly suggestion: string;
}

export interface PublishHealth {
  readonly line_3s: number;
  readonly line_retention: number;
  readonly note: string;
  readonly below: PublishHealthItem[];
}

export interface PublishReport {
  readonly dimension: string;
  readonly rows: PublishReportRow[];
  readonly recorded: number;
  readonly zero_plays_excluded: number;
  readonly health: PublishHealth;
}
```

METHOD_NAMES 在 `'export.set_publish_data',` 后加 `'export.publish_report',`。

`protocol/schemas/export.json` x-methods 数组追加（仿 set_publish_data 条目形状）：

```json
    {
      "name": "export.publish_report",
      "summary": "harness 只读聚合报告：维度中位完播/点赞率/分享率 + 灰黄信号 + 健康线",
      "params": {
        "type": "object",
        "properties": {
          "dimension": {
            "type": "string",
            "enum": ["mode", "arc", "angle", "platform", "duration_bucket"]
          }
        }
      },
      "result": { "type": "object" }
    }
```

- [ ] **Step 6: RPC 级测试 + 门禁**

追加到 test_export_report.py（DB 级，复用 test_export_publish_data 的 _seed 手法——真外键，计划真建）：

```python
def test_rpc_roundtrip(memory_db, tmp_path) -> None:
    import json
    from types import SimpleNamespace
    from dramaclip.api import export as export_api
    from dramaclip.infra.storage.repos import exports as exports_repo
    from dramaclip.infra.storage.repos import plans as plans_repo
    from dramaclip.infra.storage.repos import projects as projects_repo
    from dramaclip.infra.storage.repos import episodes as episodes_repo
    from dramaclip.transport.rpc import RpcDomainError

    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    project_id = str(projects_repo.create(memory_db, "报告剧", str(tmp_path))["id"])
    episodes_repo.replace_all(
        memory_db, project_id,
        [{"episode_number": 1, "source_path": str(source), "duration": 120.0}],
    )
    episode_id = str(episodes_repo.list_by_project(memory_db, project_id)[0]["id"])
    plans_repo.create(
        memory_db, project_id, "full_narration", [episode_id],
        {"mode": "full_narration", "arc": "triumph", "timeline": []}, status="ready",
    )
    plan_id = str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])
    export_id = str(exports_repo.create(memory_db, project_id, plan_id, "full_narration"))
    memory_db.execute(
        "UPDATE export_jobs SET status = 'completed', output_path = ?, duration_s = 75.0 WHERE id = ?",
        (str(source), export_id),
    )
    memory_db.commit()
    context = SimpleNamespace(conn=memory_db)
    export_api.set_publish_data(context, {"export_id": export_id, "data": {
        "platform": "抖音", "plays": 2000, "retention_pct": 40.0, "shares": 100,
    }})
    report = export_api.publish_report(context, {"dimension": "duration_bucket"})
    assert report["rows"][0]["value"] == "60-90s"
    assert report["rows"][0]["share_rate"] == 0.05
    assert report["health"]["line_retention"] == 30.0
    arc_report = export_api.publish_report(context, {"dimension": "arc"})
    assert arc_report["rows"][0]["value"] == "triumph"
    with pytest.raises(RpcDomainError) as exc_info:
        export_api.publish_report(context, {"dimension": "watch_score"})
    assert exc_info.value.code == -32412
```

Run: `../.venv/Scripts/python -m pytest tests/api/test_export_report.py tests/transport/test_contract_sync.py -v` → 全 PASS
Run: `../.venv/Scripts/ruff check dramaclip tests` → 净
Run: `npm run typecheck`（cwd=desktop）→ 净

- [ ] **Step 7: Commit**

```bash
git add service/dramaclip/api/export_report.py service/dramaclip/api/export.py service/dramaclip/infra/storage/repos/exports.py service/tests/api/test_export_report.py protocol/ts/index.ts protocol/schemas/export.json
git commit -m "feat(harness): publish_report 只读聚合——五维度中位数/灰黄纪律/健康线/时长分桶（批二#7/#8/#9）"
```

---

### Task 3: 数据报告抽屉——成品库入口 + 维度聚合表 + 健康线横幅

**Files:**
- Create: `desktop/src/features/works/PublishReportDrawer.tsx`
- Modify: `desktop/src/features/works/WorksPage.tsx`（PageHeader actions + 挂载）
- Modify: `desktop/src/services/client.ts`（exportApi.publishReport）
- Test: `desktop/src/features/works/__tests__/publishReport.test.tsx`（新建）

**Interfaces:**
- Consumes: T2 的 `export.publish_report` RPC 与 PublishReport 类型；`errorText` from `../engines/errorText`；PageKit/tokens。
- Produces: `PublishReportDrawer({open, onClose})` 组件；`exportApi.publishReport(dimension: string): Promise<PublishReport>`。T4 在抽屉 Tabs 里追加「对照实验」页。

- [ ] **Step 1: 写失败测试**

新建 `publishReport.test.tsx`（mock 手法仿 worksDetail.test.tsx 的 vi.mock('../../../services/client')）：

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { App as AntdApp } from 'antd';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PublishReport } from '@dramaclip/protocol';
import { PublishReportDrawer } from '../PublishReportDrawer';

const api = { publishReport: vi.fn() };
vi.mock('../../../services/client', () => ({
  exportApi: { publishReport: api.publishReport },
}));

const REPORT: PublishReport = {
  dimension: 'mode',
  rows: [{
    value: 'full_narration', n: 12, median_retention_pct: 35.5,
    like_rate: 0.04, share_rate: 0.012, signal: 'yellow', outliers: ['e-outlier-1'],
  }],
  recorded: 12, zero_plays_excluded: 1,
  health: {
    line_3s: 32, line_retention: 30, note: '通用基准初始值，回流数据足够后自建校准',
    below: [{
      export_id: 'e1', project_name: '剧一', metric: 'retention_3s',
      value: 20, suggestion: '钩子重选：前3秒留存低于基准，开场钩子没留住人',
    }],
  },
};

function renderDrawer() {
  return render(
    <AntdApp><PublishReportDrawer open onClose={() => undefined} /></AntdApp>,
  );
}

beforeEach(() => { vi.clearAllMocks(); });

describe('PublishReportDrawer', () => {
  it('渲染聚合行、信号与离群点名', async () => {
    api.publishReport.mockResolvedValue(REPORT);
    renderDrawer();
    await waitFor(() => { expect(screen.getByText('full_narration')).toBeInTheDocument(); });
    expect(screen.getByText('35.5%')).toBeInTheDocument();
    expect(screen.getByText(/趋势参考/)).toBeInTheDocument();
    expect(screen.getByText(/e-outlier/)).toBeInTheDocument();
    expect(api.publishReport).toHaveBeenCalledWith('mode');
  });

  it('健康线横幅带校准标注与低于线建议', async () => {
    api.publishReport.mockResolvedValue(REPORT);
    renderDrawer();
    await waitFor(() => { expect(screen.getByText(/通用基准初始值/)).toBeInTheDocument(); });
    expect(screen.getByText(/钩子重选/)).toBeInTheDocument();
    expect(screen.getByText(/剧一/)).toBeInTheDocument();
  });

  it('加载失败诚实显示错误，不伪装空表', async () => {
    api.publishReport.mockRejectedValue(new Error('boom'));
    renderDrawer();
    await waitFor(() => { expect(screen.getByText(/报告加载失败：boom/)).toBeInTheDocument(); });
  });

  it('空账如实提示去录入', async () => {
    api.publishReport.mockResolvedValue({ ...REPORT, rows: [], recorded: 0 });
    renderDrawer();
    await waitFor(() => { expect(screen.getByText(/暂无回流数据/)).toBeInTheDocument(); });
  });
});
```

- [ ] **Step 2: 跑测试确认红**

Run: `npx vitest run src/features/works/__tests__/publishReport.test.tsx`（cwd=desktop）
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现组件 + 入口 + client**

`client.ts` exportApi 加：

```ts
  /** harness 只读聚合报告（批二）：维度聚合 + 健康线。 */
  publishReport: (dimension: string): Promise<PublishReport> =>
    rpc<PublishReport>('export.publish_report', { dimension }),
```

（import 类型 PublishReport 加入既有 @dramaclip/protocol 导入列表。）

新建 `PublishReportDrawer.tsx`：

```tsx
/** harness 数据报告（批二#6–#9）：只读事实表——调权永远人拍板，本页不改任何规则。
 *  聚合口径在服务端 export_report 单持，本组件只渲染与搬运。 */
import { Alert, Drawer, Empty, Select, Spin, Table, Tabs, Tag } from 'antd';
import { useEffect, useState, type ReactElement } from 'react';
import type { PublishReport, PublishReportRow } from '@dramaclip/protocol';
import { exportApi } from '../../services/client';
import { errorText } from '../engines/errorText';
import { tokens } from '../../styles/theme';

const DIMENSION_OPTIONS = [
  { value: 'mode', label: '模式' },
  { value: 'arc', label: '叙事母题' },
  { value: 'angle', label: '取材角度' },
  { value: 'platform', label: '平台' },
  { value: 'duration_bucket', label: '时长分桶' },
];

const SIGNAL_LABEL = { gray: '样本不足·只看趋势', yellow: '趋势参考', ok: '可作依据' } as const;

function pct(value: number | null): string {
  return value === null ? '—' : `${String(value)}%`;
}

function rate(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(2)}%`;
}

export function PublishReportDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}): ReactElement {
  const [dimension, setDimension] = useState('mode');
  const [report, setReport] = useState<PublishReport | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError('');
    exportApi
      .publishReport(dimension)
      .then((result) => { if (active) setReport(result); })
      .catch((e: unknown) => { if (active) setError(errorText(e, '报告加载失败')); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, dimension]);

  const columns = [
    { title: '维度值', dataIndex: 'value', key: 'value' },
    { title: '样本', dataIndex: 'n', key: 'n' },
    {
      title: '中位完播', key: 'ret',
      render: (_: unknown, row: PublishReportRow) => pct(row.median_retention_pct),
    },
    {
      title: '点赞率', key: 'like',
      render: (_: unknown, row: PublishReportRow) => rate(row.like_rate),
    },
    {
      title: '分享率', key: 'share',
      render: (_: unknown, row: PublishReportRow) => rate(row.share_rate),
    },
    {
      title: '信号', key: 'signal',
      render: (_: unknown, row: PublishReportRow) => (
        <Tag color={row.signal === 'gray' ? 'default' : row.signal === 'yellow' ? 'warning' : 'success'}>
          {SIGNAL_LABEL[row.signal]}
        </Tag>
      ),
    },
    {
      title: '离群点名', key: 'outliers',
      render: (_: unknown, row: PublishReportRow) =>
        row.outliers.length === 0 ? '—' : row.outliers.map((id) => id.slice(0, 8)).join('、'),
    },
  ];

  return (
    <Drawer title="数据报告" width={780} open={open} onClose={onClose}>
      <Tabs
        items={[{
          key: 'aggregate',
          label: '维度聚合',
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
              <span style={{ display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
                <Select
                  size="small"
                  value={dimension}
                  onChange={setDimension}
                  options={DIMENSION_OPTIONS}
                  style={{ width: 140 }}
                />
                {report !== null && (
                  <span style={{ fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>
                    已录 {report.recorded} 条{report.zero_plays_excluded > 0
                      ? `，剔除零播放 ${String(report.zero_plays_excluded)} 条` : ''}
                  </span>
                )}
              </span>
              {report !== null && (
                <Alert
                  type="info"
                  showIcon
                  message={`健康线：前3秒留存 ≥${String(report.health.line_3s)}% · 整体完播 ≥${String(report.health.line_retention)}%（${report.health.note}）`}
                  description={report.health.below.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
                      {report.health.below.map((item) => (
                        <div key={`${item.export_id}-${item.metric}`}>
                          {item.project_name}（{item.export_id.slice(0, 8)}）{item.metric === 'retention_3s' ? '前3秒' : '完播'} {item.value}%：{item.suggestion}
                        </div>
                      ))}
                    </div>
                  ) : undefined}
                />
              )}
              {error !== '' && <Alert type="error" showIcon message={`报告加载失败：${error}`} />}
              {loading ? <Spin /> : report === null || report.rows.length === 0 ? (
                <Empty description="暂无回流数据——在成片详情页「发布数据」录入后这里开始累积" />
              ) : (
                <Table
                  size="small"
                  rowKey="value"
                  columns={columns}
                  dataSource={report.rows}
                  pagination={false}
                />
              )}
              <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
                分享率=分享数/播放量；视频号社交裂变权重最高（实测分享/点赞比 2.2~2.5）。灰标禁作调权依据，黄标仅趋势参考。
              </div>
            </div>
          ),
        }]}
      />
    </Drawer>
  );
}
```

`WorksPage.tsx`：图标导入加 `BarChartOutlined`；组件内加 `const [reportOpen, setReportOpen] = useState(false);`；PageHeader actions 改为：

```tsx
        actions={
          <span style={{ display: 'flex', gap: tokens.spaceSm }}>
            <Button icon={<BarChartOutlined />} onClick={() => { setReportOpen(true); }}>
              数据报告
            </Button>
            <Button icon={<SafetyCertificateOutlined />} onClick={onSelfcheck}>
              补测自检
            </Button>
          </span>
        }
```

（tokens 若未导入则加 `import { tokens } from '../../styles/theme';`；PreviewModal 挂载行后加：）

```tsx
      <PublishReportDrawer open={reportOpen} onClose={() => { setReportOpen(false); }} />
```

并 import PublishReportDrawer。

- [ ] **Step 4: 跑测试确认绿 + 门禁**

Run: `npx vitest run src/features/works src/__tests__/contract.test.ts`（cwd=desktop）→ 全 PASS
Run: `npm run typecheck` → 净；`npx eslint src/features/works` → 0 errors

- [ ] **Step 5: Commit**

```bash
git add desktop/src/features/works/PublishReportDrawer.tsx desktop/src/features/works/WorksPage.tsx desktop/src/services/client.ts desktop/src/features/works/__tests__/publishReport.test.tsx
git commit -m "feat(harness): 成品库数据报告抽屉——维度聚合表+健康线横幅+灰黄信号（批二#7/#9 界面）"
```

---

### Task 4: A/B 对照组四态——ab_report RPC + 对照实验页

**Files:**
- Modify: `service/dramaclip/api/export_report.py`（追加 ab_pairs）
- Modify: `service/dramaclip/api/export.py`（register + handler）
- Modify: `protocol/ts/index.ts`（AbPair/AbReport + METHOD_NAMES）
- Modify: `protocol/schemas/export.json`（x-methods）
- Modify: `desktop/src/services/client.ts`（exportApi.abReport）
- Modify: `desktop/src/features/works/PublishReportDrawer.tsx`（Tabs 加第二页）
- Test: `service/tests/api/test_export_report.py`（追加）；`desktop/src/features/works/__tests__/publishReport.test.tsx`（追加）

**Interfaces:**
- Consumes: T2 `list_publish_entries` 行形状（含 published_at/video_id）；T3 抽屉。
- Produces: `export_report.ab_pairs(entries, *, now_ms: int) -> dict`；常量 `AB_WINDOW_DAYS = 3`、`AB_MIN_PLAYS = 500`、`AB_DIFF_PP = 5.0`；RPC `export.ab_report({project_id?}) -> {pairs, unpaired, window_days, min_plays, diff_pp}`；pair 行键 project_id/project_name/platform/a/b/retention_a/retention_b/delta_pp/state/leader/note。

- [ ] **Step 1: 写失败测试（追加到 test_export_report.py）**

```python
_NOW_MS = 1_800_000_000_000  # 2027-01-15 前后，固定钟


def _dated(export_id: str, published: str, **over: Any) -> dict[str, Any]:
    return _entry(export_id, published_at=published, **over)


def test_ab_four_states() -> None:
    from datetime import date
    today = date.fromtimestamp(_NOW_MS / 1000)
    old = (today - __import__("datetime").timedelta(days=10)).isoformat()
    young = (today - __import__("datetime").timedelta(days=1)).isoformat()
    # 等待：一方发布未满 72h
    rows = [_dated("a1", old, plays=9000), _dated("a2", young, plays=9000)]
    pair = export_report.ab_pairs(rows, now_ms=_NOW_MS)["pairs"][0]
    assert pair["state"] == "等待"
    # 证据不足：都满 72h 但播放不足 500
    rows = [_dated("b1", old, plays=400), _dated("b2", old, plays=9000)]
    assert export_report.ab_pairs(rows, now_ms=_NOW_MS)["pairs"][0]["state"] == "证据不足"
    # 差异不明显：Δ3pp < 5pp
    rows = [_dated("c1", old, plays=9000, retention_pct=30.0),
            _dated("c2", old, plays=9000, retention_pct=33.0)]
    assert export_report.ab_pairs(rows, now_ms=_NOW_MS)["pairs"][0]["state"] == "差异不明显"
    # 方向性领先：Δ8pp，leader 指向高完播
    rows = [_dated("d1", old, plays=9000, retention_pct=30.0),
            _dated("d2", old, plays=9000, retention_pct=38.0)]
    pair = export_report.ab_pairs(rows, now_ms=_NOW_MS)["pairs"][0]
    assert pair["state"] == "方向性领先" and pair["leader"] == "d2"
    assert pair["delta_pp"] == -8.0


def test_ab_pairing_rules() -> None:
    from datetime import date, timedelta
    today = date.fromtimestamp(_NOW_MS / 1000)
    old = (today - timedelta(days=10)).isoformat()
    far = (today - timedelta(days=20)).isoformat()
    # 发布日期差 >3 天：不成对
    rows = [_dated("f1", old), _dated("f2", far)]
    assert export_report.ab_pairs(rows, now_ms=_NOW_MS)["pairs"] == []
    # 跨平台 / 跨项目：不成对
    rows = [_dated("g1", old), _dated("g2", old, platform="快手")]
    assert export_report.ab_pairs(rows, now_ms=_NOW_MS)["pairs"] == []
    rows = [_dated("h1", old), _dated("h2", old, project_id="p2")]
    assert export_report.ab_pairs(rows, now_ms=_NOW_MS)["pairs"] == []
    # 无发布日期：进 unpaired，不演成可对账
    rows = [_dated("i1", old), _entry("i2")]
    result = export_report.ab_pairs(rows, now_ms=_NOW_MS)
    assert result["pairs"] == [] and result["unpaired"] == 2
```

- [ ] **Step 2: 跑测试确认红**

Run: `../.venv/Scripts/python -m pytest tests/api/test_export_report.py -v`（cwd=service）
Expected: 新用例 FAIL（AttributeError: ab_pairs）。

- [ ] **Step 3: 实现 ab_pairs + RPC**

`export_report.py` 追加（import 区加 `from datetime import date`）：

```python
AB_WINDOW_DAYS = 3  # published_at 只录到日：72h 按 3 天计
AB_MIN_PLAYS = 500
AB_DIFF_PP = 5.0  # 初始值，回流数据足够后校准（P-R4）


def ab_pairs(entries: list[dict[str, Any]], *, now_ms: int) -> dict[str, Any]:
    """同项目同平台对照组（批二#6）：四态保守读数，方向性≠统计显著。"""
    dated: list[tuple[dict[str, Any], date]] = []
    for row in entries:
        raw = row.get("published_at")
        try:
            parsed = date.fromisoformat(str(raw)) if raw else None
        except ValueError:
            parsed = None
        if parsed is not None:
            dated.append((row, parsed))
    groups: dict[tuple[str, str], list[tuple[dict[str, Any], date]]] = {}
    for row, day in dated:
        groups.setdefault((str(row["project_id"]), str(row["platform"])), []).append((row, day))
    today = date.fromtimestamp(now_ms / 1000)
    pairs: list[dict[str, Any]] = []
    unpaired = len(entries) - len(dated)
    for (project_id, platform), members in sorted(groups.items()):
        members.sort(key=lambda m: (m[1], str(m[0]["export_id"])))
        matched: set[int] = set()
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                ri, di = members[i]
                rj, dj = members[j]
                if abs((di - dj).days) > AB_WINDOW_DAYS:
                    continue
                matched.add(i)
                matched.add(j)
                delta = round(float(ri["retention_pct"]) - float(rj["retention_pct"]), 2)
                if (today - di).days < AB_WINDOW_DAYS or (today - dj).days < AB_WINDOW_DAYS:
                    state, leader, note = "等待", None, "发布未满72h，数据仍在累积"
                elif ri["plays"] < AB_MIN_PLAYS or rj["plays"] < AB_MIN_PLAYS:
                    state, leader, note = "证据不足", None, "播放量不足500，样本未达门槛"
                elif abs(delta) < AB_DIFF_PP:
                    state, leader, note = "差异不明显", None, "完播差不足5个百分点（初始阈值，待校准）"
                else:
                    state = "方向性领先"
                    leader = str(ri["export_id"] if delta > 0 else rj["export_id"])
                    note = "方向性读数，非统计显著；建议复跑验证"
                pairs.append({
                    "project_id": project_id,
                    "project_name": str(ri["project_name"]),
                    "platform": platform,
                    "a": str(ri["export_id"]),
                    "b": str(rj["export_id"]),
                    "retention_a": float(ri["retention_pct"]),
                    "retention_b": float(rj["retention_pct"]),
                    "delta_pp": delta,
                    "state": state,
                    "leader": leader,
                    "note": note,
                })
        unpaired += len(members) - len(matched)
    return {
        "pairs": pairs,
        "unpaired": unpaired,
        "window_days": AB_WINDOW_DAYS,
        "min_plays": AB_MIN_PLAYS,
        "diff_pp": AB_DIFF_PP,
    }
```

`api/export.py` register 加 `router.register("export.ab_report", lambda params: ab_report(context, params))`；handler：

```python
def ab_report(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """A/B 对照组四态（批二#6）：同项目同平台/72h/≥500 播放，保守读数。"""
    from dramaclip.api import export_report

    entries = exports_repo.list_publish_entries(context.conn)
    project_id = str(params.get("project_id") or "").strip()
    if project_id:
        entries = [r for r in entries if r["project_id"] == project_id]
    return export_report.ab_pairs(entries, now_ms=_now_ms())
```

- [ ] **Step 4: 协议 + client + 抽屉第二页**

`protocol/ts/index.ts` 加：

```ts
/** A/B 对照对（export.ab_report）：四态保守读数，方向性≠统计显著。 */
export interface AbPair {
  readonly project_id: string;
  readonly project_name: string;
  readonly platform: string;
  readonly a: string;
  readonly b: string;
  readonly retention_a: number;
  readonly retention_b: number;
  readonly delta_pp: number;
  readonly state: '等待' | '证据不足' | '差异不明显' | '方向性领先';
  readonly leader: string | null;
  readonly note: string;
}

export interface AbReport {
  readonly pairs: AbPair[];
  readonly unpaired: number;
  readonly window_days: number;
  readonly min_plays: number;
  readonly diff_pp: number;
}
```

METHOD_NAMES 加 `'export.ab_report',`；schema export.json 追加条目：

```json
    {
      "name": "export.ab_report",
      "summary": "A/B 对照组四态：同项目同平台/72h/≥500 播放，等待/证据不足/差异不明显/方向性领先",
      "params": {
        "type": "object",
        "properties": { "project_id": { "type": "string" } }
      },
      "result": { "type": "object" }
    }
```

`client.ts` exportApi 加：

```ts
  /** A/B 对照组四态（批二#6）。 */
  abReport: (projectId?: string): Promise<AbReport> =>
    rpc<AbReport>('export.ab_report', projectId === undefined ? {} : { project_id: projectId }),
```

`PublishReportDrawer.tsx`：import 加 `AbPair, AbReport` 类型与 exportApi.abReport 调用；组件内加第二组 state：

```tsx
  const [ab, setAb] = useState<AbReport | null>(null);
  const [abError, setAbError] = useState('');
  useEffect(() => {
    if (!open) return;
    let active = true;
    setAbError('');
    exportApi
      .abReport()
      .then((result) => { if (active) setAb(result); })
      .catch((e: unknown) => { if (active) setAbError(errorText(e, '对照读数加载失败')); });
    return () => { active = false; };
  }, [open]);
```

Tabs items 追加第二页：

```tsx
        {
          key: 'ab',
          label: '对照实验',
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
              <div style={{ fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>
                同项目同平台、发布日期差≤72h 成对；双方发布满72h 且播放≥500 才比较。
                {ab !== null && ab.unpaired > 0 ? ` 未成对 ${String(ab.unpaired)} 条（缺发布日期或无同组对照）。` : ''}
              </div>
              {abError !== '' && <Alert type="error" showIcon message={`对照读数加载失败：${abError}`} />}
              {ab === null || ab.pairs.length === 0 ? (
                <Empty description="暂无可对照的组——同剧同平台发两条以上并录入发布日期后开始读数" />
              ) : (
                <Table
                  size="small"
                  rowKey={(row) => `${row.a}-${row.b}`}
                  dataSource={ab.pairs}
                  pagination={false}
                  columns={[
                    { title: '项目', dataIndex: 'project_name', key: 'project' },
                    { title: '平台', dataIndex: 'platform', key: 'platform' },
                    {
                      title: '对照', key: 'pair',
                      render: (_: unknown, row: AbPair) =>
                        `${row.a.slice(0, 8)} ${String(row.retention_a)}% vs ${row.b.slice(0, 8)} ${String(row.retention_b)}%`,
                    },
                    {
                      title: 'Δ完播', key: 'delta',
                      render: (_: unknown, row: AbPair) =>
                        `${row.delta_pp > 0 ? '+' : ''}${String(row.delta_pp)}pp`,
                    },
                    {
                      title: '状态', key: 'state',
                      render: (_: unknown, row: AbPair) => (
                        <Tag color={row.state === '方向性领先' ? 'success' : row.state === '证据不足' ? 'warning' : 'default'}>
                          {row.state}
                        </Tag>
                      ),
                    },
                    { title: '说明', dataIndex: 'note', key: 'note' },
                  ]}
                />
              )}
            </div>
          ),
        },
```

桌面测试追加（publishReport.test.tsx；mock 对象加 abReport）：

```tsx
// mock 改为：const api = { publishReport: vi.fn(), abReport: vi.fn() };
// vi.mock 工厂 exportApi 加 abReport: api.abReport；beforeEach 里 api.abReport.mockResolvedValue({ pairs: [], unpaired: 0, window_days: 3, min_plays: 500, diff_pp: 5 });

it('对照实验页渲染四态与领先方说明', async () => {
  api.publishReport.mockResolvedValue(REPORT);
  api.abReport.mockResolvedValue({
    pairs: [{
      project_id: 'p1', project_name: '剧一', platform: '抖音',
      a: 'aaaaaaaa-1', b: 'bbbbbbbb-2', retention_a: 30, retention_b: 38,
      delta_pp: -8, state: '方向性领先', leader: 'bbbbbbbb-2',
      note: '方向性读数，非统计显著；建议复跑验证',
    }],
    unpaired: 1, window_days: 3, min_plays: 500, diff_pp: 5,
  });
  renderDrawer();
  fireEvent.click(screen.getByText('对照实验'));
  await waitFor(() => { expect(screen.getByText('方向性领先')).toBeInTheDocument(); });
  expect(screen.getByText(/非统计显著/)).toBeInTheDocument();
  expect(screen.getByText(/未成对 1 条/)).toBeInTheDocument();
});
```

（import 加 fireEvent；既有 4 用例的 beforeEach 需给 abReport 默认 mockResolvedValue 空报告，否则抽屉打开即调 abReport 得到 undefined.then 炸。）

- [ ] **Step 5: 跑测试确认绿 + 门禁**

Run: `../.venv/Scripts/python -m pytest tests/api/test_export_report.py tests/transport/test_contract_sync.py -v`（cwd=service）→ 全 PASS
Run: `../.venv/Scripts/ruff check dramaclip tests` → 净
Run: `npx vitest run src/features/works src/__tests__/contract.test.ts`（cwd=desktop）→ 全 PASS
Run: `npm run typecheck` → 净

- [ ] **Step 6: Commit**

```bash
git add service/dramaclip/api/export_report.py service/dramaclip/api/export.py service/tests/api/test_export_report.py protocol/ts/index.ts protocol/schemas/export.json desktop/src/services/client.ts desktop/src/features/works/PublishReportDrawer.tsx desktop/src/features/works/__tests__/publishReport.test.tsx
git commit -m "feat(harness): A/B 对照组四态——同项目同平台/72h/≥500播放保守读数（批二#6）"
```

---

### Task 5: 六维评分锚点补「名场面共鸣/转发语」判据（#8 后半）

**Files:**
- Modify: `service/dramaclip/engines/narration/variant_scoring.py`（_SYSTEM_PROMPT 的 cta_pull 锚点，现 60–63 行）
- Test: `service/tests/engines/narration/test_variant_scoring.py`（若不存在则新建；先跑 `ls service/tests/engines/narration/` 确认）

**Interfaces:**
- Consumes: 现状 WEIGHTS 六键（hook_power/rhythm/emotion_curve/conflict_clarity/cta_pull/visual_potential）。
- Produces: 仅 prompt 文案变化；WEIGHTS/DIMENSIONS/函数签名一字不动。

- [ ] **Step 1: 写失败测试**

```python
"""#8 分享判据：锚点补转发语，六维结构与权重不动（变异锚点：改权重即红）。"""

from dramaclip.engines.narration import variant_scoring as vs


def test_cta_anchor_mentions_share_worthiness() -> None:
    prompt = vs._SYSTEM_PROMPT
    assert "转发语" in prompt and "名场面共鸣" in prompt


def test_six_dimensions_and_weights_frozen() -> None:
    assert vs.WEIGHTS == {
        "hook_power": 0.25, "rhythm": 0.12, "emotion_curve": 0.12,
        "conflict_clarity": 0.16, "cta_pull": 0.25, "visual_potential": 0.10,
    }, "先数据验证再决定是否独立成维——本批不动六维结构"
```

- [ ] **Step 2: 跑测试确认红**

Run: `../.venv/Scripts/python -m pytest tests/engines/narration/test_variant_scoring.py -v`（cwd=service；若文件已存在则跑该文件全量）
Expected: 锚点用例 FAIL（转发语不在 prompt）。

- [ ] **Step 3: 改锚点**

`_SYSTEM_PROMPT` 的 cta_pull 9 分档（现 60–61 行）：

原文：
```
    "【cta_pull 收尾导看力】9=收尾一句口播把「完整版更狠」落在具体悬念上"
    "（点名未揭的反转/未出的结果），让人必须点进去；7=收尾指向看全集但悬念笼统；"
```
改为：
```
    "【cta_pull 收尾导看力】9=收尾一句口播把「完整版更狠」落在具体悬念上"
    "（点名未揭的反转/未出的结果），或收一句名场面共鸣/转发语（替观众说出心里话，"
    "让人想转发给同好），让人必须点进去；7=收尾指向看全集但悬念笼统；"
```

- [ ] **Step 4: 跑测试确认绿 + 回归**

Run: `../.venv/Scripts/python -m pytest tests/engines/narration/ -v`（cwd=service）→ 全 PASS
Run: `../.venv/Scripts/ruff check dramaclip tests` → 净

- [ ] **Step 5: Commit**

```bash
git add service/dramaclip/engines/narration/variant_scoring.py service/tests/engines/narration/test_variant_scoring.py
git commit -m "feat(scoring): cta_pull 锚点补名场面共鸣/转发语判据——六维结构不动（批二#8）"
```

---

### Task 6: VL 钩子两策略标签——hook_strategy 帧字段（#10）

**Files:**
- Modify: `service/dramaclip/engines/vision/runtime.py`（_prompt_for 现 128–142 行；parse_descriptions 现 90–125 行；新增 hook_label）
- Modify: `service/dramaclip/api/narration.py`（generate_titles 的 visual_hooks 行，现 135–143 行）
- Test: `service/tests/engines/vision/test_hook_strategy.py`（新建——test_runtime.py 有并行会话未提交改动，不碰）

**Interfaces:**
- Consumes: 现状帧字典键 t/shot/scene/people/action/mood/watch_score。
- Produces: 帧新键 `hook_strategy: str` ∈ {"视觉悖论", "身份快照", "无"}（缺省/非法→「无」）；`vision.runtime.hook_label(frame: dict) -> str`（命中两策略返回「（策略名）」，否则空串）。v0.2.4 钩子帧选择器落地时消费 hook_strategy。

- [ ] **Step 1: 写失败测试（新建 test_hook_strategy.py）**

```python
"""#10 钩子两策略：prompt 显式标签 + parser 容忍旧分析缺字段（P-R3）。"""

from dramaclip.engines.vision import runtime


def test_prompt_offers_two_strategies() -> None:
    prompt = runtime._prompt_for(16)
    assert "视觉悖论" in prompt and "身份快照" in prompt
    assert "hook_strategy" in prompt


def test_parser_carries_valid_strategy() -> None:
    text = '{"index": 1, "action": "她把婚书扔进火里", "mood": "决绝", "watch_score": 9, "hook_strategy": "视觉悖论"}'
    frames = runtime.parse_descriptions(text, 1, 120.0)
    assert frames[0]["hook_strategy"] == "视觉悖论"


def test_parser_defaults_missing_or_invalid_to_none() -> None:
    missing = '{"index": 1, "action": "x", "mood": "y", "watch_score": 5}'
    invalid = '{"index": 1, "action": "x", "mood": "y", "watch_score": 5, "hook_strategy": "悬念反问"}'
    assert runtime.parse_descriptions(missing, 1, 120.0)[0]["hook_strategy"] == "无", "旧分析缺字段容忍"
    assert runtime.parse_descriptions(invalid, 1, 120.0)[0]["hook_strategy"] == "无", "词表外不演成合法标签"


def test_hook_label_suffix() -> None:
    assert runtime.hook_label({"hook_strategy": "身份快照"}) == "（身份快照）"
    assert runtime.hook_label({"hook_strategy": "无"}) == ""
    assert runtime.hook_label({}) == ""
```

- [ ] **Step 2: 跑测试确认红**

Run: `../.venv/Scripts/python -m pytest tests/engines/vision/test_hook_strategy.py -v`（cwd=service）
Expected: FAIL（prompt 无策略 / KeyError hook_strategy / AttributeError hook_label）。

- [ ] **Step 3: 实现 prompt + parser + hook_label**

`_prompt_for` 的 JSON 示例行与 watch_score 说明改为：

```python
        '{"index": 1, "shot": "景别", "scene": "场景", "people": "人物外观",'
        ' "action": "动作", "mood": "情绪", "watch_score": 7, "hook_strategy": "无"},'
        ' 其中 watch_score 是这张图作为短视频封面的视觉冲击力评分（1~10 整数）：'
        '10=极具张力（激烈动作/极端表情/强反差构图），1=平淡（站桩/过场/空景）；'
        '按画面本身的动作幅度与情绪浓度打分，不受台词影响。'
        'hook_strategy 是开场钩子策略标签，三选一：'
        '"视觉悖论"=画面元素与常识/身份强烈反差（如盛装配狼狈、豪车配工装）；'
        '"身份快照"=一眼读懂人物身份与处境的关系构图；"无"=不构成开场钩子。',
```

`parse_descriptions` 在 watch 钳制之后、frames.append 之前加：

```python
        strategy = str(item.get("hook_strategy") or "无").strip()
        if strategy not in ("视觉悖论", "身份快照"):
            strategy = "无"
```

frames.append 字典加 `"hook_strategy": strategy,`。

模块尾部加：

```python
def hook_label(frame: dict[str, Any]) -> str:
    """标题 visual_hooks 行的策略后缀：命中两策略才标注，无则空串。"""
    strategy = str(frame.get("hook_strategy") or "")
    return f"（{strategy}）" if strategy in ("视觉悖论", "身份快照") else ""
```

`api/narration.py` generate_titles：函数内 import 区加 `from dramaclip.engines.vision.runtime import hook_label`；`scored.append((w, desc))` 改为：

```python
            if w > 0 and desc:
                scored.append((w, desc + hook_label(frame)))
```

- [ ] **Step 4: 跑测试确认绿 + 回归**

Run: `../.venv/Scripts/python -m pytest tests/engines/vision/test_hook_strategy.py tests/api/ -v`（cwd=service）→ 全 PASS
Run: `../.venv/Scripts/ruff check dramaclip tests` → 净

- [ ] **Step 5: Commit**

```bash
git add service/dramaclip/engines/vision/runtime.py service/dramaclip/api/narration.py service/tests/engines/vision/test_hook_strategy.py
git commit -m "feat(vision): 帧级 hook_strategy 两策略标签——视觉悖论/身份快照，衔接 v0.2.4 钩子帧选择（批二#10）"
```

---

### Task 7: IAA 话术库——静态用户自选 + 两个复制面统一吃发布包（#11，顺带闭 M3）

**Files:**
- Modify: `service/dramaclip/engines/narration/publish_pack.py`（CTA_VARIANTS + build_pack）
- Modify: `service/dramaclip/api/narration.py`（set_cta RPC + publish_pack 传 cta_id + generate_titles 保留 cta_id）
- Modify: `protocol/ts/index.ts`（PublishMeta/PlatformPack + METHOD_NAMES）
- Modify: `protocol/schemas/narration.json`（x-methods）
- Modify: `desktop/src/services/client.ts`（titlesApi.setCta）
- Modify: `desktop/src/features/works/PlatformPackSection.tsx`（话术选择器）
- Modify: `desktop/src/features/works/publishCopy.ts`（buildPublishCopy 改吃 pack）
- Modify: `desktop/src/features/works/PublishChecklistSection.tsx`（复制改拉 pack）
- Modify: `desktop/src/features/works/WorksDetailPage.tsx`（清单组件传 planId）
- Test: `service/tests/engines/narration/test_publish_pack.py`（追加；先确认存在）；`service/tests/api/test_narration_cta.py`（新建）；`desktop/src/features/works/__tests__/publishCopy.test.ts`（改写）；`worksDetail.test.tsx`（随 props 变更修）

**Interfaces:**
- Consumes: 现状 `build_pack(titles, caption, tags)`、`plans_repo.get/set_publish_meta`、`publish_meta` JSON {caption, tags}。
- Produces: `publish_pack.CTA_VARIANTS: dict[str, dict[str, str]]`（键 iaa_free/paid_suspense，值 {label, line}）；`build_pack(titles, caption, tags, cta_id=None)` 返回加 `cta_id/cta_line/cta_options`；RPC `narration.set_cta({plan_id, cta_id}) -> {ok, cta_id}`（`_ERR_CTA_INVALID = -32306`）；`buildPublishCopy(pack: PlatformPack): string` 单参。

- [ ] **Step 1: 写失败测试**

`test_publish_pack.py` 追加：

```python
def test_cta_variants_user_selected() -> None:
    from dramaclip.engines.narration import publish_pack as pp

    assert set(pp.CTA_VARIANTS) == {"iaa_free", "paid_suspense"}
    assert "免费看全集" in pp.CTA_VARIANTS["iaa_free"]["line"]
    pack = pp.build_pack([{"text": "标题", "selected": True}], "钩子文案", ["爽剧"], "iaa_free")
    assert pack["cta_id"] == "iaa_free"
    assert pack["caption"] == "钩子文案 免费看全集，点主页链接一次追完"
    assert pack["platforms"]["抖音"]["caption"] == pack["caption"], "逐平台与总览同一份文案"
    assert {o["id"] for o in pack["cta_options"]} == {"iaa_free", "paid_suspense"}


def test_cta_default_none_and_unknown_tolerated() -> None:
    from dramaclip.engines.narration import publish_pack as pp

    pack = pp.build_pack([{"text": "标题", "selected": True}], "钩子文案", [])
    assert pack["cta_id"] is None and pack["cta_line"] is None
    assert pack["caption"] == "钩子文案", "默认无话术＝现状不变"
    unknown = pp.build_pack([{"text": "标题", "selected": True}], None, [], "bogus")
    assert unknown["cta_id"] is None and unknown["caption"] is None, "词表外按无话术，不炸"
    # caption 为 None 且选了话术 → 话术独立成文案
    only = pp.build_pack([{"text": "标题", "selected": True}], None, [], "iaa_free")
    assert only["caption"] == "免费看全集，点主页链接一次追完"
```

新建 `service/tests/api/test_narration_cta.py`：

```python
"""set_cta：词表校验 + publish_meta 合并写 + 重生成标题不丢话术选择。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import narration as narration_api
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import RpcDomainError


def _plan(memory_db: sqlite3.Connection, tmp_path: Path) -> str:
    project_id = str(projects_repo.create(memory_db, "话术剧", str(tmp_path))["id"])
    plans_repo.create(
        memory_db, project_id, "full_narration", [],
        {"mode": "full_narration", "timeline": []}, status="ready",
    )
    return str(plans_repo.list_by_project(memory_db, project_id)[0]["id"])


def test_set_cta_validates_and_merges(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    plan_id = _plan(memory_db, tmp_path)
    context = SimpleNamespace(conn=memory_db)
    plans_repo.set_publish_meta(
        memory_db, plan_id, json.dumps({"caption": "钩子", "tags": ["爽剧"]})
    )
    result = narration_api.set_cta(context, {"plan_id": plan_id, "cta_id": "iaa_free"})
    assert result == {"ok": True, "cta_id": "iaa_free"}
    meta = plans_repo.get(memory_db, plan_id)["publish_meta"]
    assert meta["cta_id"] == "iaa_free"
    assert meta["caption"] == "钩子" and meta["tags"] == ["爽剧"], "合并写，不覆盖既有物料"
    pack = narration_api.publish_pack(context, {"plan_id": plan_id})
    assert pack["cta_id"] == "iaa_free" and "免费看全集" in pack["caption"]
    narration_api.set_cta(context, {"plan_id": plan_id, "cta_id": None})
    assert plans_repo.get(memory_db, plan_id)["publish_meta"]["cta_id"] is None


def test_set_cta_rejects_unknown(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    plan_id = _plan(memory_db, tmp_path)
    with pytest.raises(RpcDomainError) as exc_info:
        narration_api.set_cta(SimpleNamespace(conn=memory_db), {"plan_id": plan_id, "cta_id": "bogus"})
    assert exc_info.value.code == -32306
```

`desktop publishCopy.test.ts` 改写（新签名）：

```ts
import { describe, expect, it } from 'vitest';
import type { PlatformPack } from '@dramaclip/protocol';
import { buildPublishCopy, CHECKLIST_ITEMS } from '../publishCopy';

const PACK: PlatformPack = {
  title: '选中标题', caption: '钩子文案 免费看全集，点主页链接一次追完',
  tags: ['爽剧', '好剧推荐'], cta_id: 'iaa_free', cta_line: '免费看全集，点主页链接一次追完',
  cta_options: [{ id: 'iaa_free', label: '免费看全集（红果/免费剧）' }],
  platforms: {},
};

describe('buildPublishCopy（单参 pack：两个复制面同一份服务端快照）', () => {
  it('标题/文案/话题取服务端发布包（含话题注入与话术）', () => {
    const text = buildPublishCopy(PACK);
    expect(text).toContain('【标题】选中标题');
    expect(text).toContain('【文案】钩子文案 免费看全集');
    expect(text).toContain('#好剧推荐');
    expect(text).toContain('【发布前自查】');
    for (const item of CHECKLIST_ITEMS) expect(text).toContain(`□ ${item}`);
  });
  it('空字段不演成空段', () => {
    const text = buildPublishCopy({ ...PACK, title: '', caption: null, tags: [] });
    expect(text).not.toContain('【标题】');
    expect(text).not.toContain('【文案】');
    expect(text).not.toContain('【话题】');
    expect(text).toContain('【发布前自查】');
  });
});
```

- [ ] **Step 2: 跑测试确认红**

Run: `../.venv/Scripts/python -m pytest tests/engines/narration/test_publish_pack.py tests/api/test_narration_cta.py -v`（cwd=service）→ FAIL
Run: `npx vitest run src/features/works/__tests__/publishCopy.test.ts`（cwd=desktop）→ FAIL

- [ ] **Step 3: 服务端实现**

`publish_pack.py` 常量区加：

```python
#: IAA/充值两话术（批二#11）：静态库、用户显式自选，不过 titles LLM 门禁
#: （_BANNED_PHRASES 拦的是 LLM 违禁腔，P-R2）；默认无话术＝现状。
CTA_VARIANTS: dict[str, dict[str, str]] = {
    "iaa_free": {"label": "免费看全集（红果/免费剧）", "line": "免费看全集，点主页链接一次追完"},
    "paid_suspense": {"label": "充值解锁悬念", "line": "结局反转已更新，点链接解锁全集"},
}
```

`build_pack` 改签名与文案解析：

```python
def build_pack(
    titles: list[dict[str, Any]], caption: str | None, tags: list[str],
    cta_id: str | None = None,
) -> dict[str, Any]:
    """只读快照 → 逐平台包；选用标题优先，无选用取第一条。"""
    selected = next((str(t.get("text", "")) for t in titles if t.get("selected")), "")
    if not selected and titles:
        selected = str(titles[0].get("text", ""))
    merged_tags = inject_topics(tags)
    variant = CTA_VARIANTS.get(cta_id or "")
    cta_line = variant["line"] if variant else None
    resolved = f"{caption} {cta_line}" if caption and cta_line else (caption or cta_line)
    platforms: dict[str, Any] = {}
    for name in PLATFORM_ORDER:
        spec = PLATFORM_SPECS[name]
        platforms[name] = {
            "title": selected,
            "title_fits": len(selected) <= int(spec["title_max"]),
            "caption": resolved,
            "tags": merged_tags,
            "cover_ratio": list(spec["cover_ratio"]),
            "ai_declaration": spec["ai_declaration"],
        }
    return {
        "title": selected, "caption": resolved, "tags": merged_tags,
        "cta_id": cta_id if variant else None, "cta_line": cta_line,
        "cta_options": [{"id": key, "label": v["label"]} for key, v in CTA_VARIANTS.items()],
        "platforms": platforms,
    }
```

`api/narration.py`：错误码区加 `_ERR_CTA_INVALID = -32306`；register 加 `router.register("narration.set_cta", lambda params: set_cta(context, params))`；publish_pack 的 build_pack 调用改：

```python
    return pack_engine.build_pack(
        row.get("titles") or [], meta.get("caption"), meta.get("tags") or [],
        meta.get("cta_id"),
    )
```

新 handler：

```python
def set_cta(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """话术选择（批二#11）：用户显式自选，合并写 publish_meta，不覆盖标题物料。"""
    from dramaclip.engines.narration import publish_pack as pack_engine

    plan_id = str(params.get("plan_id", ""))
    row = plans_repo.get(context.conn, plan_id)
    if row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    raw = params.get("cta_id")
    cta_id = None if raw in (None, "") else str(raw)
    if cta_id is not None and cta_id not in pack_engine.CTA_VARIANTS:
        raise RpcDomainError(
            _ERR_CTA_INVALID, f"cta_id 必须是 {'/'.join(pack_engine.CTA_VARIANTS)} 之一或 null"
        )
    meta = dict(row.get("publish_meta") or {})
    meta["cta_id"] = cta_id
    plans_repo.set_publish_meta(context.conn, plan_id, json.dumps(meta, ensure_ascii=False))
    return {"ok": True, "cta_id": cta_id}
```

generate_titles 的 set_publish_meta 调用改（保留已选话术——重生成标题是物料刷新，不该顺手清掉用户选择）：

```python
    plans_repo.set_publish_meta(
        context.conn,
        plan_id,
        json.dumps(
            {
                "caption": result["caption"], "tags": result["tags"],
                "cta_id": (row.get("publish_meta") or {}).get("cta_id"),
            },
            ensure_ascii=False,
        ),
    )
```

- [ ] **Step 4: 协议 + client**

`protocol/ts/index.ts`：PublishMeta 加 `readonly cta_id?: string | null;`；PlatformPack 加：

```ts
  readonly cta_id: string | null;
  readonly cta_line: string | null;
  readonly cta_options: readonly { readonly id: string; readonly label: string }[];
```

METHOD_NAMES 在 `'narration.publish_pack',` 后加 `'narration.set_cta',`。schema narration.json 追加：

```json
    {
      "name": "narration.set_cta",
      "summary": "发布话术自选（IAA 免费看全集/充值解锁悬念）：静态库，默认无；合并写 publish_meta",
      "params": {
        "type": "object",
        "required": ["plan_id", "cta_id"],
        "properties": {
          "plan_id": { "type": "string" },
          "cta_id": { "type": ["string", "null"], "enum": ["iaa_free", "paid_suspense", null] }
        }
      },
      "result": { "type": "object" }
    }
```

`client.ts` titlesApi 加：

```ts
  setCta: (planId: string, ctaId: string | null): Promise<{ ok: boolean; cta_id: string | null }> =>
    rpc<{ ok: boolean; cta_id: string | null }>('narration.set_cta', { plan_id: planId, cta_id: ctaId }),
```

- [ ] **Step 5: 前端三处**

`PlatformPackSection.tsx` extra 区平台 Select 之前插入话术 Select：

```tsx
          <Select
            size="small"
            value={pack?.cta_id ?? ''}
            options={[
              { value: '', label: '无话术' },
              ...(pack?.cta_options ?? []).map((o) => ({ value: o.id, label: o.label })),
            ]}
            onChange={(value) => {
              titlesApi
                .setCta(planId, value === '' ? null : value)
                .then(() => { setRetryTick((tick) => tick + 1); })
                .catch((error: unknown) => message.error(errorText(error, '话术保存失败')));
            }}
            style={{ width: 200 }}
          />
```

`publishCopy.ts` 改单参（CHECKLIST_ITEMS 不动）：

```ts
/** 发布前自查清单 + 发布包一键复制文本（纯函数）。
 *  清单是动作提醒不是存证数据——不落库（授权存证否决裁决 2026-09-10）。
 *  物料取服务端 publish_pack 快照：与逐平台复制同一份（话题注入/话术都在服务端单持）。 */
import type { PlatformPack } from '@dramaclip/protocol';

export const CHECKLIST_ITEMS = [
  '授权覆盖：确认本剧推广授权覆盖目标平台与切片用途',
  '挂载链接：确认挂载组件/小程序链接已配置且指向正确剧集',
  '标题封面相符：封面帧与标题卖的是同一亮点，不做点击错位',
  '全程剧名：已开「剧名常驻层」开关，或标题/文案含剧名',
  '话题组：含实测高频话题（#好剧推荐 #因为一个片段看了整部剧）',
] as const;

export function buildPublishCopy(pack: PlatformPack): string {
  const tags = pack.tags.length ? pack.tags.map((t) => `#${t}`).join(' ') : '';
  const parts = [
    pack.title !== '' ? `【标题】${pack.title}` : '',
    pack.caption !== null && pack.caption !== '' ? `【文案】${pack.caption}` : '',
    tags !== '' ? `【话题】${tags}` : '',
    `【发布前自查】\n${CHECKLIST_ITEMS.map((item) => `□ ${item}`).join('\n')}`,
  ];
  return parts.filter((part) => part !== '').join('\n');
}
```

`PublishChecklistSection.tsx`：props 改 `{ planId: string }`；import 改 `import { titlesApi } from '../../services/client';` + `import { errorText } from '../engines/errorText';` + buildPublishCopy/CHECKLIST_ITEMS 保留；删 titles/publish props 与 PublishMeta/TitleCandidate 导入；加 `const [copying, setCopying] = useState(false);`；copy 改：

```tsx
  const copy = (): void => {
    setCopying(true);
    titlesApi
      .publishPack(planId)
      .then((pack) =>
        navigator.clipboard.writeText(buildPublishCopy(pack))
          .then(() => message.success('发布包与自查清单已复制'))
          .catch(() => message.error('复制到剪贴板失败'))
      )
      .catch((error: unknown) => message.error(errorText(error, '发布包加载失败')))
      .finally(() => { setCopying(false); });
  };
```

Button 加 `loading={copying}`。

`WorksDetailPage.tsx` 挂载处（现 118 行附近区域）：`<PublishChecklistSection titles={...} publish={...} />` 改 `<PublishChecklistSection planId={detail.job.narration_plan_id ?? ''} />`（以现场实际 props 为准；planId 空串时 copy 按钮应禁用——Button 加 `disabled={planId === ''}`）。

`worksDetail.test.tsx`：清单复制相关用例改为 mock publishPack 返回新形状（含 cta_id/cta_line/cta_options——可给 null/null/[]）；原 buildPublishCopy 双参调用点全改。

- [ ] **Step 6: 跑测试确认绿 + 门禁**

Run: `../.venv/Scripts/python -m pytest tests/engines/narration/test_publish_pack.py tests/api/test_narration_cta.py tests/transport/test_contract_sync.py -v`（cwd=service）→ 全 PASS
Run: `../.venv/Scripts/ruff check dramaclip tests` → 净
Run: `npx vitest run src/features/works src/__tests__/contract.test.ts`（cwd=desktop）→ 全 PASS
Run: `npm run typecheck` → 净；`npx eslint src/features/works` → 0 errors

- [ ] **Step 7: Commit**

```bash
git add service/dramaclip/engines/narration/publish_pack.py service/dramaclip/api/narration.py service/tests/engines/narration/test_publish_pack.py service/tests/api/test_narration_cta.py protocol/ts/index.ts protocol/schemas/narration.json desktop/src/services/client.ts desktop/src/features/works/PlatformPackSection.tsx desktop/src/features/works/publishCopy.ts desktop/src/features/works/PublishChecklistSection.tsx desktop/src/features/works/WorksDetailPage.tsx desktop/src/features/works/__tests__/publishCopy.test.ts desktop/src/features/works/__tests__/worksDetail.test.tsx
git commit -m "feat(publish): IAA/充值两话术用户自选+两复制面统一吃发布包快照（批二#11，闭 M3）"
```

---

## 真机 DoD（批次二验收，单测绿不替代）

1. **回流录入**：成片详情页录一条含分享数/前3秒留存/作品ID 的真实数据；同平台同 ID 录第二条成片被拒且文案指名冲突对象。
2. **报告读数**：真实录入 ≥2 条后开「数据报告」，五维度切换读数正确；健康线横幅有校准标注；低于线条目出建议。
3. **A/B**：同剧同平台录两条发布日期相近的数据，四态随播放量/日龄变化符合预期（可用临时改库造数验证后还原）。
4. **VL 策略**：重跑一集分析（或 VL 冒烟），帧 JSON 出现 hook_strategy 且取值在三词表内；标题生成的 visual_hooks 行带策略后缀。
5. **话术**：发布包选「免费看全集」，逐平台复制与清单一键复制的文案都含该话术且话题一致；重生成标题后话术选择仍在；选「无话术」恢复原文案。
6. **回归**：服务全量 pytest + 桌面全量 vitest + ruff + eslint + typecheck 在最终树跑一遍（外来红归因，不修外来文件）。

## Self-Review 记录

- 规格覆盖：#6→T1（ID/对账）+T4（四态）；#7→T1（retention_3s）+T2（健康线）+T3（横幅）；#8→T1（shares）+T2（分享率）+T5（锚点）；#9→T2（duration_bucket）+T3（维度切换）；#10→T6；#11→T7。P-R1 基座=T2/T3。无缺口。
- 类型一致：list_publish_entries 行键 ↔ aggregate/health/ab_pairs 消费键逐一对齐；PublishReport/AbPair 协议形状 ↔ RPC 返回键一致；buildPublishCopy(pack) 与 PlatformPack 新键一致。
- 占位扫描：T7 Step 1 草稿误留行已当场修正（最终文件不含 `if False`）；无 TBD/TODO。