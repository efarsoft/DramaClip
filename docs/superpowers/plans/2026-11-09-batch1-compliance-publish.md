# 批次一 · 合规与发布摩擦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地改进报告批次一的 5 项：AIGC 隐式标识、字幕安全区、逐平台发布包、剧名常驻层、发布前自查清单。

**Architecture:** 后端新增三个纯函数/轻 IO 模块（aigc_metadata / safe_zone / publish_pack）+ 一个镜像 ai_label 的段滤镜模块（drama_name_layer），全部经既有 JSON-RPC 命名空间接线；前端在成片详情/预览弹层/设置页增量扩展，不新建页面。隐式标识在整片最终交付遍写入（concat/BGM/响度之后），覆盖单段 copyfile 与多段 concat 两条路径。

**Tech Stack:** Python 3.12（service/，pytest+ruff）、ffmpeg/ffprobe（runner.run）、React 19 + TS 5.9 strict + AntD 6（desktop/，vitest）、@dramaclip/protocol 共享类型。

**Spec:** `docs/research/2026-11-09-improvement-proposal.md` §5 批次一（项 1–5）；证据出处随表（法规第 5/6 条、GB 45438-2025 元数据 JSON、阿里云 SASE AIGC 标识指南、抖音元数据规范 comment 通道、四平台实测话题 §2.2）。

## Global Constraints

以下裁决与纪律对每个任务隐式生效，违反即返工：

- **AIGC 隐式标识默认关、用户可开**（业主裁决 2026-11-09）。新键 `export.aigc_metadata` 默认 `"false"`。
- **剧名常驻层默认关、用户可开**（业主裁决 2026-11-09；报告「推广模式默认开」不采纳）。新键 `export.drama_name_layer` 默认 `"false"`。
- **显式 AI 标注（export.ai_label）2026-10-15 裁决不重议**：默认关、用户开关，本批不动它的行为。
- **不做授权存证**（2026-09-10 否决裁决）：自查清单只输出动作清单文本，不落库任何「存证」数据。
- **字幕安全区不得破坏覆盖闸**：字幕落位跟随源台词带（业主裁决「区域一致即可」，`ass_generator.placement_violations` 出片前 raise）。安全区只做预览遮罩 + 灰项劝告，**永不移动字幕、永不判红**。
- **时长让位故事**：本批不加任何时长硬约束。
- **质量优先**：用户明示开启的能力（隐式标识/剧名层）缺失即硬失败，不静默交付缺项成片（镜像 ai_label 语义）。
- **设置键单一真相源**：每个可读键必须登记进 `service/dramaclip/infra/config.py` 的 `DEFAULTS`（settings.update 拒未知键）。
- **注释纪律**：只写「为什么是这个值/这个顺序」；批次经过、事故日期、文件指针进提交信息，不进代码注释。
- **测试纪律**：命令构建/纯函数在单测钉死；真实 ffmpeg 执行只在真机 DoD（文末）。不得以单测绿冒充真机验证。
- **同一含义不得第二处真相源**：平台画幅表只在 publish_pack 定义；遮罩几何只在 safe_zone 定义（前端经 RPC 读）。

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `service/dramaclip/engines/exporter/aigc_metadata.py` | 新建 | 隐式标识 payload/参数/最终交付遍 remux |
| `service/dramaclip/engines/subtitle/safe_zone.py` | 新建 | 遮罩几何常量 + 自检劝告判据 |
| `service/dramaclip/engines/narration/publish_pack.py` | 新建 | 平台规格表 + 话题注入 + 包构建（纯函数） |
| `service/dramaclip/engines/exporter/drama_name_layer.py` | 新建 | 剧名角标 drawtext 规格（镜像 ai_label） |
| `service/dramaclip/infra/config.py` | 修改 | 登记 3 个新键 |
| `service/dramaclip/engines/exporter/encoder.py` | 修改 | aigc_stamp / burn_drama_name 参数与接线 |
| `service/dramaclip/engines/exporter/selfcheck.py` | 修改 | payload 增 safe_zone 灰项 |
| `service/dramaclip/api/export.py` | 修改 | 隐式标识接线 + submit 守卫 + platform_covers RPC |
| `service/dramaclip/api/export_covers.py` | 修改 | generate_platform_covers（画幅重裁） |
| `service/dramaclip/api/narration.py` | 修改 | publish_pack RPC |
| `service/dramaclip/api/subtitle.py` | 修改 | safe_zone RPC |
| `protocol/ts/index.ts` | 修改 | SafeZoneMask / PlatformPack 类型 + SelfCheck.safe_zone |
| `desktop/src/services/client.ts` | 修改 | 三个新 RPC 客户端方法 |
| `desktop/src/features/settings/sections.ts` | 修改 | 出片区三个新字段 |
| `desktop/src/features/works/safeZoneOverlay.ts` | 新建 | 遮罩百分比矩形（纯函数） |
| `desktop/src/features/works/PreviewModal.tsx` | 修改 | 安全区开关 + 遮罩叠层 |
| `desktop/src/features/works/SelfCheckSection.tsx` | 修改 | 安全区劝告行 |
| `desktop/src/features/works/PlatformPackSection.tsx` | 新建 | 逐平台发布包分区 |
| `desktop/src/features/works/publishCopy.ts` | 新建 | 清单一键复制文本（纯函数） |
| `desktop/src/features/works/PublishChecklistSection.tsx` | 新建 | 自查清单分区 |
| `desktop/src/features/works/WorksDetailPage.tsx` | 修改 | 挂载两个新分区 |

任务顺序 = 报告项序：Task 1=①隐式标识，Task 2=②安全区，Task 3=③发布包，Task 4=④剧名层，Task 5=⑤清单。Task 3 的 AI 声明指引引用 Task 1 的开关语义（文案引用，无代码依赖）；Task 5 的清单文案引用 Task 4 的开关名。

**测试命令口径**（Windows Git Bash，仓库根目录起）：
- 后端单测：`cd service && ../.venv/Scripts/python -m pytest tests/<path> -v`（addopts 已含 -q；根 venv 实名 `.venv`，不是 `venv/`）
- 后端全量：`cd service && ../.venv/Scripts/python -m pytest`
- 后端 lint：`cd service && ../.venv/Scripts/ruff check dramaclip tests`
- 前端单测：`cd desktop && npx vitest run <file>`
- 前端类型：`cd desktop && npm run typecheck`

---

### Task 1: AIGC 隐式标识（报告项 ①）

**Files:**
- Create: `service/dramaclip/engines/exporter/aigc_metadata.py`
- Modify: `service/dramaclip/infra/config.py`（DEFAULTS，`export.ai_label` 条目之后）
- Modify: `service/dramaclip/engines/exporter/encoder.py`（import 行 34；export_plan 签名 ~868；两处转发 ~904/~936；_export_plan_once 签名 ~976；收尾 ~1346）
- Modify: `service/dramaclip/api/export.py`（import 行 40；错误码区 ~72；submit ~152；export_plan 调用 ~1021）
- Modify: `desktop/src/features/settings/sections.ts`（EXPORT_SECTION，ai_label 字段后 ~186）
- Test: `service/tests/engines/exporter/test_aigc_metadata.py`（新建）
- Test: `service/tests/api/test_export_submit.py`（追加一个用例）

**Interfaces:**
- Consumes: `config.get_bool` / `config.Settings`；`runner.run(args, *, timeout_s)`（args 不含 ffmpeg 二进制，runner 自加）；`RpcDomainError(code, message)`。
- Produces: `aigc_metadata.enabled(settings) -> bool`；`aigc_metadata.producer_code(settings) -> str`；`aigc_metadata.payload(producer, content_id) -> str`（Base64）；`aigc_metadata.metadata_args(producer, content_id) -> list[str]`；`aigc_metadata.stamp(film: Path, *, producer: str, content_id: str) -> None`；encoder 新关键字参数 `aigc_stamp: tuple[str, str] | None`（(提供者编码, 内容编号)，None=关）。Task 3 的 AI 声明指引文案引用开关名 `export.aigc_metadata`。

**背景（实现者必读）**：GB 45438-2025 的元数据 JSON 为 `{"Label":"1","ContentProducer":<编码>,"ProduceID":<内容编号>}`；业界实现（阿里云 SASE 指南）先拼 `AIGC=` 前缀再整体 Base64。抖音元数据规范接受 comment 通道；XMP uuid box 注入超出 ffmpeg 能力，只读 XMP 的平台靠发布包的逐平台 AI 声明指引兜底（Task 3）。写入点必须在**整片最终交付遍**：`_concat` 的单段分支是 `shutil.copyfile`（encoder.py:1590-1595，不经过 ffmpeg），BGM/响度后置遍是否保留元数据各分支不一——收尾统一 remux 一次覆盖所有路径。提供者编码是法定必填项，开启而编码为空在 submit 即拒（早于渲染，不跑半小时才报错）。

- [ ] **Step 1: 写失败测试（模块级）**

创建 `service/tests/engines/exporter/test_aigc_metadata.py`：

```python
"""engines.exporter.aigc_metadata：AIGC 隐式标识（settings export.aigc_metadata，默认关闭）。

业主裁决 2026-11-09：默认关、用户可开。钉住「默认关」「payload 形状（AIGC= 前缀 +
Base64 + 三字段）」「擦源留标参数序」「原子 remux」「收尾遍接线」。
真实 ffmpeg 执行由真机 DoD 覆盖（同 test_ai_label.py 的规矩）。
"""

from __future__ import annotations

import base64
import inspect
import json
import random
from pathlib import Path

import pytest

from dramaclip.engines.exporter import aigc_metadata, encoder
from dramaclip.infra import config


def test_default_is_off() -> None:
    assert config.DEFAULTS["export.aigc_metadata"] == "false"
    assert config.DEFAULTS["export.aigc_producer_code"] == ""
    assert aigc_metadata.enabled({}) is False
    assert aigc_metadata.enabled({"export.aigc_metadata": "true"}) is True


def test_payload_roundtrip() -> None:
    value = aigc_metadata.payload("001191330106MA2C91330100Y43", "export-123")
    decoded = base64.b64decode(value).decode("utf-8")
    assert decoded.startswith("AIGC=")
    doc = json.loads(decoded[len("AIGC="):])
    assert doc == {
        "Label": "1",
        "ContentProducer": "001191330106MA2C91330100Y43",
        "ProduceID": "export-123",
    }


def test_metadata_args_erase_then_write() -> None:
    args = aigc_metadata.metadata_args("P", "C")
    assert args[:2] == ["-map_metadata", "-1"], "先擦源元数据"
    assert args[2] == "-metadata"
    assert args[3].startswith("comment=")
    decoded = base64.b64decode(args[3][len("comment="):]).decode("utf-8")
    assert json.loads(decoded[len("AIGC="):])["ProduceID"] == "C"


def test_stamp_remuxes_atomically(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    film = tmp_path / "film.mp4"
    film.write_bytes(b"old")
    seen: dict[str, object] = {}

    def fake_run(args: list[str], **_kwargs: object) -> None:
        seen["args"] = args
        Path(args[-1]).write_bytes(b"stamped")

    monkeypatch.setattr(aigc_metadata.runner, "run", fake_run)
    aigc_metadata.stamp(film, producer="P", content_id="C")
    assert film.read_bytes() == b"stamped"
    args = seen["args"]
    assert isinstance(args, list)
    assert "-c" in args and "copy" in args, "流复制 remux，不重编"
    assert list(tmp_path.glob("*.part*")) == [], "半成品收走"


def test_stamp_failure_keeps_original(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    film = tmp_path / "film.mp4"
    film.write_bytes(b"old")

    def fake_run(args: list[str], **_kwargs: object) -> None:
        raise RuntimeError("ffmpeg broke")

    monkeypatch.setattr(aigc_metadata.runner, "run", fake_run)
    with pytest.raises(RuntimeError):
        aigc_metadata.stamp(film, producer="P", content_id="C")
    assert film.read_bytes() == b"old"
    assert list(tmp_path.glob("*.part*")) == []


def test_encoder_param_defaults_off() -> None:
    for fn in (encoder.export_plan, encoder._export_plan_once):
        param = inspect.signature(fn).parameters["aigc_stamp"]
        assert param.default is None
        assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_stamp_runs_at_delivery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """收尾遍接线：concat 之后才 stamp（单段 copyfile 分支同样覆盖）。"""
    from dramaclip.engines.narration.models import PlanData, TimelineSegment

    source = tmp_path / "ep.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=1.0, audio="original")],
    )
    order: list[str] = []
    monkeypatch.setattr(
        encoder, "_run_cut", lambda args, *_a, **_k: Path(args[-1]).write_bytes(b"seg")
    )

    def fake_concat(_files: list[Path], out: Path) -> None:
        order.append("concat")
        Path(out).write_bytes(b"film")

    monkeypatch.setattr(encoder, "_concat", fake_concat)
    monkeypatch.setattr(
        encoder.aigc_metadata, "stamp",
        lambda film, **_kw: order.append("stamp"),
    )
    out = tmp_path / "out.mp4"
    encoder._export_plan_once(plan, {"ep1": str(source)}, out, tmp_path / "work", aigc_stamp=("P", "C"))
    assert order == ["concat", "stamp"]

    order.clear()
    encoder._export_plan_once(plan, {"ep1": str(source)}, out, tmp_path / "work2")
    assert order == ["concat"], "不传 aigc_stamp 零额外动作"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter/test_aigc_metadata.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'dramaclip.engines.exporter.aigc_metadata'`）

- [ ] **Step 3: 实现模块 + 登记设置键**

创建 `service/dramaclip/engines/exporter/aigc_metadata.py`：

```python
"""AIGC 隐式标识（settings ``export.aigc_metadata``，默认关闭）。

业主裁决（2026-11-09）：默认关、用户可开——隐式标识与显式烧录（export.ai_label）
是两条独立要求，各自开关。payload 按 GB 45438-2025 元数据 JSON
（Label/ContentProducer/ProduceID）拼 ``AIGC=`` 前缀后整体 Base64，写入 MP4
comment 字段（抖音元数据规范接受 comment 通道）；XMP 容器注入超出 ffmpeg 能力，
只读 XMP 的平台靠发布包的逐平台 AI 声明指引兜底。

写入点在整片最终交付遍：concat 的单段分支是 copyfile 不经过 ffmpeg，
BGM/响度后置遍的元数据存活性各分支不一——收尾 ``-c copy`` remux 一次，
所有路径覆盖且仅一次（流复制不重编，秒级）。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg import runner

#: GB 45438-2025 内容属性：1=AI 生成合成（2/3 为传播平台专用，制作端不写）。
_LABEL = "1"


def enabled(settings: config.Settings) -> bool:
    """读取开关（默认 false；缺键同样判假）。"""
    return config.get_bool(settings, "export.aigc_metadata")


def producer_code(settings: config.Settings) -> str:
    """服务提供者编码（法定必填；空 = 未填，submit 守卫据此拒收）。"""
    return str(settings.get("export.aigc_producer_code", "") or "").strip()


def payload(producer: str, content_id: str) -> str:
    """AIGC= 前缀 + JSON 整体 Base64（先拼前缀再编码，解码端按前缀识别）。"""
    doc = {"Label": _LABEL, "ContentProducer": producer, "ProduceID": content_id}
    raw = "AIGC=" + json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def metadata_args(producer: str, content_id: str) -> list[str]:
    """擦源留标：-map_metadata -1 在前，comment 写入在后（顺序即语义）。"""
    return ["-map_metadata", "-1", "-metadata", f"comment={payload(producer, content_id)}"]


def stamp(film: Path, *, producer: str, content_id: str) -> None:
    """最终交付遍：流复制 remux 写入隐式标识；失败上抛（用户明示开启，不静默缺标）。"""
    staged = film.with_name(f"{film.stem}.aigc.part{film.suffix}")
    try:
        runner.run(
            ["-y", "-i", str(film), "-c", "copy", *metadata_args(producer, content_id), str(staged)],
            timeout_s=300,
        )
        staged.replace(film)
    finally:
        staged.unlink(missing_ok=True)
```

修改 `service/dramaclip/infra/config.py`，在 `"export.ai_label": "false",` 条目（含其上方注释块）之后插入：

```python
    # AIGC 隐式标识（业主裁决 2026-11-09）：默认关、用户可开，与显式烧录各自开关。
    # 开启后最终交付遍写 GB 45438-2025 元数据（属性/提供者编码/内容编号）进 comment；
    # 提供者编码是法定必填项，空值在 submit 即拒。
    "export.aigc_metadata": "false",
    "export.aigc_producer_code": "",
```

- [ ] **Step 4: encoder 接线**

修改 `service/dramaclip/engines/exporter/encoder.py`：

import 行（34）改为：
```python
from dramaclip.engines.exporter import ai_label, aigc_metadata, drama_name_layer, loudness
```
（注意：`drama_name_layer` 在 Task 4 才创建——本步先只加 `aigc_metadata`，Task 4 再补全。本步写：）
```python
from dramaclip.engines.exporter import ai_label, aigc_metadata, loudness
```

`export_plan` 签名：在 `bgm_track: Path | None = None,` 之后加一行：
```python
    aigc_stamp: tuple[str, str] | None = None,
```

`export_plan` 内两处 `_export_plan_once(...)` 调用：在 `bgm_track=bgm_track,` 之后各加一行：
```python
            aigc_stamp=aigc_stamp,
```

`_export_plan_once` 签名：在 `bgm_track: Path | None = None,` 之后、`_allow_uniform_retry` 之前加：
```python
    aigc_stamp: tuple[str, str] | None = None,
```

`_export_plan_once` 收尾：在响度 else 分支结束（`loudness.normalize_in_place(out_path, ...)` 调用块）之后、`if segment_offsets_sink is not None:` 之前插入：
```python
    if aigc_stamp is not None:
        # 隐式标识走最终交付遍：concat 单段 copyfile 分支不经过 ffmpeg，
        # BGM/响度再 mux 的元数据存活性各分支不一——这里写一次覆盖所有路径。
        aigc_metadata.stamp(out_path, producer=aigc_stamp[0], content_id=aigc_stamp[1])
```

- [ ] **Step 5: 跑模块测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter/test_aigc_metadata.py -v`
Expected: PASS（7 个用例）

- [ ] **Step 6: 写 API 层失败测试**

在 `service/tests/api/test_export_submit.py` 末尾追加：

```python
def test_submit_rejects_aigc_without_producer_code(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开启隐式标识但编码为空：submit 即拒（早于渲染），不跑半小时才报错。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))
    harness = _harness(memory_db, tmp_path)
    harness.context.settings = {"export.aigc_metadata": "true"}
    response = _dispatch(harness, "export.submit", {"plan_ids": [plan_id]})
    assert response.error is not None
    assert "提供者编码" in response.error.message


def test_submit_accepts_aigc_with_producer_code(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))
    harness = _harness(memory_db, tmp_path)
    harness.context.settings = {
        "export.aigc_metadata": "true",
        "export.aigc_producer_code": "001191330106MA2C91330100Y43",
    }
    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert len(result["exports"]) == 1
```

- [ ] **Step 7: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_export_submit.py -k aigc -v`
Expected: FAIL（第一个用例 response.error is None——守卫不存在）

- [ ] **Step 8: api/export.py 接线**

修改 `service/dramaclip/api/export.py`：

import 行（40）改为：
```python
from dramaclip.engines.exporter import ai_label, aigc_metadata, encoder, loudness, selfcheck
```

错误码区（`_ERR_PUBLISH_DATA = -32410` 之后）加：
```python
_ERR_AIGC_CONFIG = -32411  # 隐式标识开启但提供者编码未填：submit 即拒，不待渲染半途失败
```

`submit()` 内，`plan_ids = list(dict.fromkeys(...))` 之后、`accepted/rejected` 初始化之前插入：
```python
    if aigc_metadata.enabled(context.settings) and not aigc_metadata.producer_code(context.settings):
        raise RpcDomainError(
            _ERR_AIGC_CONFIG,
            "AIGC 隐式标识已开启但未填写服务提供者编码：请在设置「出片」分区填写"
            "（全国人工智能生成合成内容标识服务平台注册获取），或关闭隐式标识开关",
        )
```

`encoder.export_plan(...)` 调用内，`bgm_track=_pick_bgm_track(context, plan_data),` 之后加：
```python
        # AIGC 隐式标识（业主裁决 2026-11-09：默认关、用户可开）：内容编号用 export_id，
        # 与回流账同一标识符；编码在 submit 已验非空。
        aigc_stamp=(
            (aigc_metadata.producer_code(context.settings), export_id)
            if aigc_metadata.enabled(context.settings)
            else None
        ),
```

- [ ] **Step 9: 跑 API 测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_export_submit.py -v`
Expected: PASS（含既有用例全绿）

- [ ] **Step 10: 设置页字段**

修改 `desktop/src/features/settings/sections.ts`，在 EXPORT_SECTION 的 `export.ai_label` 字段对象之后插入：

```typescript
    // AIGC 隐式标识（业主裁决 2026-11-09）：默认关、用户可开——与显式烧录独立，
    // 写法定元数据（生成合成属性/提供者编码/内容编号）进成片文件。
    {
      key: 'export.aigc_metadata',
      label: 'AIGC 隐式标识',
      type: 'switch',
      help: '开启后在成片文件元数据写入 AI 生成合成标识（擦源元数据、留标识信息）；需填写下方服务提供者编码。默认关闭，由你按发布平台自行决定',
    },
    {
      key: 'export.aigc_producer_code',
      label: 'AIGC 服务提供者编码',
      type: 'text',
      placeholder: '22 位提供者编码',
      help: '在全国人工智能生成合成内容标识服务平台注册获取；开启隐式标识时必填',
    },
```

- [ ] **Step 11: 类型检查 + lint**

Run: `cd desktop && npm run typecheck`
Expected: 无错误
Run: `cd service && ../.venv/Scripts/ruff check dramaclip tests`
Expected: All checks passed

- [ ] **Step 12: Commit**

```bash
git add service/dramaclip/engines/exporter/aigc_metadata.py service/dramaclip/infra/config.py service/dramaclip/engines/exporter/encoder.py service/dramaclip/api/export.py service/tests/engines/exporter/test_aigc_metadata.py service/tests/api/test_export_submit.py desktop/src/features/settings/sections.ts
git commit -m "feat(export): AIGC 隐式标识——擦源留标最终交付遍（默认关，业主裁决 2026-11-09）"
```

---

### Task 2: 字幕安全区（报告项 ②）

**Files:**
- Create: `service/dramaclip/engines/subtitle/safe_zone.py`
- Modify: `service/dramaclip/api/subtitle.py`（register + 新 RPC）
- Modify: `service/dramaclip/engines/exporter/selfcheck.py`（import + payload 一行）
- Modify: `protocol/ts/index.ts`（SelfCheck 增 safe_zone；新增 SafeZoneMask）
- Modify: `desktop/src/services/client.ts`（subtitleApi.safeZone + 类型 import）
- Create: `desktop/src/features/works/safeZoneOverlay.ts`
- Modify: `desktop/src/features/works/PreviewModal.tsx`
- Modify: `desktop/src/features/works/SelfCheckSection.tsx`
- Test: `service/tests/engines/subtitle/test_safe_zone.py`（新建）
- Test: `service/tests/engines/exporter/test_selfcheck_safe_zone.py`（新建）
- Test: `service/tests/api/test_subtitle_safe_zone.py`（新建）
- Test: `desktop/src/features/works/__tests__/safeZoneOverlay.test.ts`（新建）

**Interfaces:**
- Consumes: `Router.register`；`SelfCheckItem`（protocol，已含 `reason?: string`）；`subtitleApi` 既有对象。
- Produces: `safe_zone.REFERENCE_SIZE = (1080, 1920)`；`safe_zone.mask_ratios() -> dict[str, float]`（键 top/right/bottom）；`safe_zone.check_safe_zone(band: tuple[float, float] | None) -> dict[str, Any]`（{pass, reason}）；RPC `subtitle.safe_zone` → `{reference: [1080, 1920], top, right, bottom, note}`；TS `SafeZoneMask`；`overlayRects(mask) -> OverlayRect[]`。

**背景（实现者必读）**：像素值按报告推断（右 150/底 250–350/顶 150），底取中值 300，**标注待真机校验**。覆盖裁决优先：字幕必须留在源台词带（`placement_violations` 会 raise），所以本任务**不改 MarginV、不移字幕**——只做预览遮罩与自检灰项劝告。`check_safe_zone` 风险时 pass=None（灰），永不 False（红）；`overall_state` 的 `_ITEMS` 不含 safe_zone，不影响汇总态。遮罩几何唯一真相源在后端模块，前端经 RPC 读。

- [ ] **Step 1: 写失败测试（后端）**

创建 `service/tests/engines/subtitle/test_safe_zone.py`：

```python
"""engines.subtitle.safe_zone：平台 UI 安全区（推断值，待真机校验）。

钉住「几何常量」「风险只灰不红」「无承诺灰」——安全区永不移动字幕、
永不判红（覆盖裁决优先：字幕落位跟随源台词带）。
"""

from __future__ import annotations

from dramaclip.engines.subtitle import safe_zone


def test_mask_ratios_reference() -> None:
    ratios = safe_zone.mask_ratios()
    assert ratios == {"top": 150 / 1920, "right": 150 / 1080, "bottom": 300 / 1920}


def test_no_band_is_gray() -> None:
    assert safe_zone.check_safe_zone(None) == {"pass": None, "reason": "无字幕覆盖承诺"}


def test_risk_is_gray_not_red() -> None:
    item = safe_zone.check_safe_zone((0.80, 0.92))
    assert item["pass"] is None, "劝告项永不判红（遮罩是推断值，落位跟随源带）"
    assert "底部互动区" in item["reason"]


def test_clear_is_green() -> None:
    assert safe_zone.check_safe_zone((0.60, 0.80))["pass"] is True
```

创建 `service/tests/engines/exporter/test_selfcheck_safe_zone.py`：

```python
"""selfcheck.run 成绩单含 safe_zone 灰项；不进 overall_state 汇总。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dramaclip.engines.exporter import selfcheck


def test_run_payload_includes_safe_zone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(selfcheck, "measure_audio_video", lambda _v: (-20.0, 0.0))
    payload = selfcheck.run(
        tmp_path / "f.mp4",
        measured_s=10.0, has_audio=True, mode="full_narration",
        budget_s=10.0, planned_segments=1, caption_band=(0.80, 0.92),
    )
    assert payload["safe_zone"]["pass"] is None
    assert "底部互动区" in payload["safe_zone"]["reason"]
    assert selfcheck.overall_state(payload) != "failed", "safe_zone 不进汇总判据"
```

创建 `service/tests/api/test_subtitle_safe_zone.py`：

```python
"""subtitle.safe_zone RPC：遮罩几何的唯一出口（前端不各写一份常量）。"""

from __future__ import annotations

from dramaclip.api import subtitle as subtitle_api
from dramaclip.transport.rpc import Router, RpcRequest


def test_safe_zone_rpc() -> None:
    router = Router()
    subtitle_api.register(router)
    response = router.dispatch(RpcRequest(id="1", method="subtitle.safe_zone", params={}))
    assert response.error is None
    assert response.result["reference"] == [1080, 1920]
    assert response.result["bottom"] == 300 / 1920
    assert "待真机校验" in response.result["note"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/subtitle/test_safe_zone.py tests/engines/exporter/test_selfcheck_safe_zone.py tests/api/test_subtitle_safe_zone.py -v`
Expected: FAIL（safe_zone 模块不存在）

- [ ] **Step 3: 实现 safe_zone 模块 + RPC + selfcheck 接线**

创建 `service/dramaclip/engines/subtitle/safe_zone.py`：

```python
"""平台 UI 安全区：预览遮罩几何 + 自检劝告（不改变字幕落位）。

像素值为推断（报告 2026-11-09：右 150/底 250–350/顶 150，底取中值 300），
待真机校验一轮后固化。字幕落位跟随源台词带（业主裁决「区域一致即可」）：
本模块只报「可能被平台 UI 遮挡」，永不移动字幕——移动会撞出片前覆盖闸
（ass_generator.placement_violations）。风险只灰不红：遮罩是推断值，
红判据会与覆盖裁决自相矛盾。
"""

from __future__ import annotations

from typing import Any

#: 推断值的标定画布（9:16 竖屏）；其他画幅按比例折算，误差真机校验时一并收。
REFERENCE_SIZE = (1080, 1920)
TOP_PX = 150
RIGHT_PX = 150
BOTTOM_PX = 300


def mask_ratios() -> dict[str, float]:
    """遮罩占画布的比例（顶/右/底三条 UI 常驻区）。"""
    width, height = REFERENCE_SIZE
    return {"top": TOP_PX / height, "right": RIGHT_PX / width, "bottom": BOTTOM_PX / height}


def check_safe_zone(band: tuple[float, float] | None) -> dict[str, Any]:
    """自检劝告项：字幕带底是否进入平台底部互动区（band 为归一化覆盖承诺）。"""
    if band is None:
        return {"pass": None, "reason": "无字幕覆盖承诺"}
    limit = 1.0 - mask_ratios()["bottom"]
    if float(band[1]) > limit:
        return {
            "pass": None,
            "reason": (
                f"字幕带底 {float(band[1]):.2f} 进入平台底部互动区"
                f"（推断遮罩 >{limit:.2f}，待真机校验）：预览可叠安全区确认，不影响覆盖承诺"
            ),
        }
    return {"pass": True, "reason": "字幕带在平台底部互动区外（推断遮罩，待真机校验）"}
```

修改 `service/dramaclip/api/subtitle.py` 全文替换为：

```python
"""subtitle 命名空间：list_presets / safe_zone。"""

from __future__ import annotations

from typing import Any

from dramaclip.engines.subtitle import presets, safe_zone
from dramaclip.transport.rpc import Router


def register(router: Router, context: Any = None) -> None:  # noqa: ARG001 - 与其他命名空间签名一致
    router.register("subtitle.list_presets", lambda _params: list_presets())
    router.register("subtitle.safe_zone", lambda _params: safe_zone_payload())


def list_presets() -> list[dict[str, Any]]:
    return [
        {
            "preset_id": str(preset["preset_id"]),
            "preset_name": str(preset["preset_name"]),
            "description": str(preset["description"]),
        }
        for preset in presets.list_presets()
    ]


def safe_zone_payload() -> dict[str, Any]:
    """遮罩几何唯一出口：前端叠层经此读取，不各写一份常量。"""
    return {
        "reference": list(safe_zone.REFERENCE_SIZE),
        **safe_zone.mask_ratios(),
        "note": "推断值，待真机校验；按 9:16 竖屏标定",
    }
```

修改 `service/dramaclip/engines/exporter/selfcheck.py`：

import 区加：
```python
from dramaclip.engines.subtitle.safe_zone import check_safe_zone
```

`run()` 的 payload dict 内，`"caption_placement": ...` 行之后加：
```python
        "safe_zone": check_safe_zone(caption_band),
```

- [ ] **Step 4: 跑后端测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/subtitle/test_safe_zone.py tests/engines/exporter/test_selfcheck_safe_zone.py tests/api/test_subtitle_safe_zone.py -v`
Expected: PASS（6 个用例）

- [ ] **Step 5: 写前端失败测试**

创建 `desktop/src/features/works/__tests__/safeZoneOverlay.test.ts`：

```typescript
import { describe, expect, it } from 'vitest';
import type { SafeZoneMask } from '@dramaclip/protocol';
import { overlayRects } from '../safeZoneOverlay';

const mask: SafeZoneMask = {
  reference: [1080, 1920],
  top: 150 / 1920,
  right: 150 / 1080,
  bottom: 300 / 1920,
  note: '',
};

describe('overlayRects', () => {
  it('三条矩形按顶/右/底铺排，百分比与遮罩比例一致', () => {
    const rects = overlayRects(mask);
    expect(rects.map((r) => r.key)).toEqual(['top', 'right', 'bottom']);
    expect(rects[0].style).toEqual({ top: '0%', left: '0%', width: '100%', height: '7.81%' });
    expect(rects[1].style.left).toBe('86.11%');
    expect(rects[1].style.width).toBe('13.89%');
    expect(rects[2].style.top).toBe('84.38%');
    expect(rects[2].style.height).toBe('15.63%');
  });
});
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd desktop && npx vitest run src/features/works/__tests__/safeZoneOverlay.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 7: protocol 类型 + client + 纯函数实现**

修改 `protocol/ts/index.ts`：

`SelfCheck` 接口内 `readonly caption_placement?: SelfCheckItem;` 之后加：
```typescript
  readonly safe_zone?: SelfCheckItem;
```

`PublishMeta` 接口定义之后加：
```typescript
/** 平台 UI 安全区遮罩（subtitle.safe_zone）：比例相对 reference 画布，推断值待真机校验。 */
export interface SafeZoneMask {
  readonly reference: readonly [number, number];
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
  readonly note: string;
}
```

修改 `desktop/src/services/client.ts`：

顶部 type import 列表加入 `SafeZoneMask`（按字母序插在 `SelftestResults` 附近即可）。`subtitleApi` 对象内加：
```typescript
  /** 平台 UI 安全区遮罩几何（推断值，待真机校验）：预览叠层的唯一数据源。 */
  safeZone: (): Promise<SafeZoneMask> => rpc<SafeZoneMask>('subtitle.safe_zone', {}),
```

创建 `desktop/src/features/works/safeZoneOverlay.ts`：

```typescript
/** 安全区叠层几何：遮罩比例 → 三条百分比矩形（纯函数，单测钉形状）。 */
import type { SafeZoneMask } from '@dramaclip/protocol';

export interface OverlayRect {
  readonly key: 'top' | 'right' | 'bottom';
  readonly label: string;
  readonly style: {
    readonly top: string;
    readonly left: string;
    readonly width: string;
    readonly height: string;
  };
}

const pct = (value: number): string => `${(value * 100).toFixed(2)}%`;

export function overlayRects(mask: SafeZoneMask): OverlayRect[] {
  return [
    { key: 'top', label: '顶栏', style: { top: '0%', left: '0%', width: '100%', height: pct(mask.top) } },
    {
      key: 'right',
      label: '互动区',
      style: {
        top: pct(mask.top),
        left: pct(1 - mask.right),
        width: pct(mask.right),
        height: pct(1 - mask.top - mask.bottom),
      },
    },
    {
      key: 'bottom',
      label: '底部信息区',
      style: { top: pct(1 - mask.bottom), left: '0%', width: '100%', height: pct(mask.bottom) },
    },
  ];
}
```

- [ ] **Step 8: 跑前端测试确认通过**

Run: `cd desktop && npx vitest run src/features/works/__tests__/safeZoneOverlay.test.ts`
Expected: PASS

- [ ] **Step 9: PreviewModal 叠层 + SelfCheckSection 劝告行**

修改 `desktop/src/features/works/PreviewModal.tsx`：

import 区改为：
```typescript
import { useEffect, useState, type ReactElement } from 'react';
import { Modal, Switch } from 'antd';
import type { SafeZoneMask, WorkItem } from '@dramaclip/protocol';
import { modeLabel } from '../../components/modeMeta';
import { mediaUrl, subtitleApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { overlayRects } from './safeZoneOverlay';
```

`PreviewModal` 函数体开头（`const title = ...` 之前）加：
```typescript
  const [mask, setMask] = useState<SafeZoneMask | null>(null);
  const [showSafeZone, setShowSafeZone] = useState(false);
  useEffect(() => {
    void subtitleApi.safeZone().then(setMask).catch(() => undefined);
  }, []);
```

Modal 的 `title={title}` 改为：
```typescript
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
          <span>{title}</span>
          <Switch
            size="small"
            checked={showSafeZone}
            onChange={setShowSafeZone}
            checkedChildren="安全区"
            unCheckedChildren="安全区"
          />
        </span>
      }
```

`{work !== null && <VideoStage path={work.output_path} />}` 改为：
```typescript
      {work !== null && (
        <VideoStage path={work.output_path} mask={showSafeZone ? mask : null} />
      )}
```

`VideoStage` 签名改为 `function VideoStage({ path, mask }: { path: string; mask: SafeZoneMask | null }): ReactElement`，其 return（成功分支）改为：
```typescript
  return (
    <div>
      <div style={{ position: 'relative' }}>
        <video
          src={mediaUrl(path)}
          controls
          autoPlay
          onError={() => {
            setFailed(true);
          }}
          style={{ width: '100%', display: 'block', background: tokens.posterBase }}
        />
        {mask !== null &&
          overlayRects(mask).map((rect) => (
            <div
              key={rect.key}
              style={{
                position: 'absolute',
                ...rect.style,
                background: 'rgba(255, 77, 79, 0.28)',
                border: '1px dashed rgba(255, 77, 79, 0.9)',
                pointerEvents: 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontSize: tokens.text.badge.size,
              }}
            >
              {rect.label}
            </div>
          ))}
      </div>
      {mask !== null && (
        <div style={{ padding: tokens.spaceXs, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
          {mask.note}
        </div>
      )}
    </div>
  );
```

修改 `desktop/src/features/works/SelfCheckSection.tsx`：在 `{badges.map((badge) => (...))}` 块之后、底部 `<span>`（测于…）之前插入：

```typescript
        {selfcheck?.safe_zone !== undefined && (
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
            <SelfCheckChip
              badge={{
                key: 'safe_zone',
                tone: selfcheck.safe_zone.pass === true ? 'ok' : 'none',
                text: selfcheck.safe_zone.pass === true ? '✓ 安全区无风险' : '— 安全区劝告',
                detail: '',
              }}
            />
            <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
              {selfcheck.safe_zone.reason ?? ''}
            </span>
          </div>
        )}
```

（`SelfCheckBadge` 的 tone 词表为 'ok' | 'fail' | 'none'，key 为 string——若 `SelfCheckBadge.key` 是联合字面量类型，把 'safe_zone' 加入该联合；实现时读 `worksView.ts` 顶部类型定义确认。）

- [ ] **Step 10: 类型检查 + 全量前端测试**

Run: `cd desktop && npm run typecheck && npx vitest run`
Expected: 类型无错误；既有测试全绿（previewFailure.test.tsx 渲染 PreviewModal——新增 useEffect 拉 RPC，jsdom 下 window.dramaclip 未 mock 时 bridge() 会抛：该测试已存在且通过的前提是 mock 了 bridge 或 RPC 失败被 catch 吞掉。`safeZone().catch(() => undefined)` 保证未 mock 时不炸；若仍红，读该测试的 mock setup 并补 `subtitle.safe_zone` 的 mock 返回。）

- [ ] **Step 11: 后端 lint + 相关回归**

Run: `cd service && ../.venv/Scripts/ruff check dramaclip tests && ../.venv/Scripts/python -m pytest tests/api/test_export_selfcheck.py tests/engines/exporter -q`
Expected: 全绿

- [ ] **Step 12: Commit**

```bash
git add service/dramaclip/engines/subtitle/safe_zone.py service/dramaclip/api/subtitle.py service/dramaclip/engines/exporter/selfcheck.py service/tests/engines/subtitle/test_safe_zone.py service/tests/engines/exporter/test_selfcheck_safe_zone.py service/tests/api/test_subtitle_safe_zone.py protocol/ts/index.ts desktop/src/services/client.ts desktop/src/features/works/safeZoneOverlay.ts desktop/src/features/works/PreviewModal.tsx desktop/src/features/works/SelfCheckSection.tsx desktop/src/features/works/__tests__/safeZoneOverlay.test.ts
git commit -m "feat(subtitle): 平台安全区预览遮罩+自检灰项劝告（推断值待真机校验，不动字幕落位）"
```

---

### Task 3: 逐平台发布包（报告项 ③）

**Files:**
- Create: `service/dramaclip/engines/narration/publish_pack.py`
- Modify: `service/dramaclip/api/narration.py`（register + publish_pack 函数）
- Modify: `service/dramaclip/api/export_covers.py`（import episodes_repo + generate_platform_covers）
- Modify: `service/dramaclip/api/export.py`（register + platform_covers 包装函数）
- Modify: `protocol/ts/index.ts`（PlatformPack / PlatformPackEntry）
- Modify: `desktop/src/services/client.ts`（titlesApi.publishPack + exportApi.platformCovers）
- Create: `desktop/src/features/works/PlatformPackSection.tsx`
- Modify: `desktop/src/features/works/WorksDetailPage.tsx`（挂载）
- Test: `service/tests/engines/narration/test_publish_pack.py`（新建）
- Test: `service/tests/api/test_narration_publish_pack.py`（新建）
- Test: `service/tests/api/test_export_platform_covers.py`（新建）

**Interfaces:**
- Consumes: `plans_repo.get`（titles/publish_meta 已解析为 list/dict）；`exports_repo.get`；`episodes_repo.list_by_project(conn, project_id)`（返回含 id/source_path 的 dict 列表）；`_cover_title(context, plan_row)`；`_cover_source_frame(conn, plan_data, episode_paths, out_size) -> (source, seek_s, composition) | None`；`ffmpeg_cover.extract_cover(video, out, *, seek_s, title, composition_vf) -> bool`。
- Produces: `publish_pack.PLATFORM_ORDER`；`publish_pack.PLATFORM_SPECS`（cover_ratio/title_max/ai_declaration）；`publish_pack.MEASURED_TOPICS`；`publish_pack.inject_topics(tags) -> list[str]`；`publish_pack.build_pack(titles, caption, tags) -> dict`；RPC `narration.publish_pack {plan_id}`；`export_covers.generate_platform_covers(context, export_id, row) -> {ok, covers, skipped}`；RPC `export.platform_covers {export_id}`；TS `PlatformPack`/`PlatformPackEntry`。Task 5 清单的话题组文案引用 MEASURED_TOPICS 语义。

**背景（实现者必读）**：画幅表来自报告（小红书 3:4/B站 16:10/视频号 6:7，抖音/快手随成片 9:16）；话题库来自 §2.2 实测（#好剧推荐 ×70/#短剧推荐 ×36/#因为一个片段看了整部剧 ×32/#短剧 ×32）。标题全局上限已是 20 字（titles.py `_TITLE_MAX_CHARS`），小红书 20 字适配=校验而非截断。AI 声明指引是运营建议（二手），与 Task 1 的法定隐式标识互补。封面重裁从**源素材**重新截帧（increase 填充 + 居中裁切到目标画布，标题字层重烧）——不能裁现有封面：现有封面字层在底部（cover.py `y=h-text_h-h/16`），居中裁切会把字切掉。封面族语义：增强项永不 raise，逐平台失败进 skipped。

- [ ] **Step 1: 写失败测试（纯函数）**

创建 `service/tests/engines/narration/test_publish_pack.py`：

```python
"""engines.narration.publish_pack：逐平台发布包（画幅/字数适配 + 实测话题注入）。"""

from __future__ import annotations

from dramaclip.engines.narration import publish_pack


def test_platform_specs_match_report() -> None:
    assert publish_pack.PLATFORM_SPECS["小红书"]["cover_ratio"] == (3, 4)
    assert publish_pack.PLATFORM_SPECS["B站"]["cover_ratio"] == (16, 10)
    assert publish_pack.PLATFORM_SPECS["视频号"]["cover_ratio"] == (6, 7)
    assert publish_pack.PLATFORM_SPECS["抖音"]["cover_ratio"] == (9, 16)
    assert publish_pack.PLATFORM_ORDER[0] == "抖音", "平台优先级按实测：抖音>视频号>快手"


def test_inject_topics_dedup_and_cap() -> None:
    assert publish_pack.inject_topics(["逆袭", "好剧推荐"]) == [
        "逆袭", "好剧推荐", "短剧推荐", "因为一个片段看了整部剧", "短剧",
    ]
    full = [f"t{i}" for i in range(8)]
    assert publish_pack.inject_topics(full) == full, "槽满不挤掉用户标签"


def test_build_pack_selected_title_and_fitness() -> None:
    pack = publish_pack.build_pack(
        [{"text": "落选", "selected": False}, {"text": "当选标题", "selected": True}],
        "文案", ["爽剧"],
    )
    assert pack["title"] == "当选标题"
    assert pack["platforms"]["小红书"]["title_fits"] is True
    assert pack["platforms"]["小红书"]["cover_ratio"] == [3, 4]
    assert "好剧推荐" in pack["platforms"]["抖音"]["tags"]
    for entry in pack["platforms"].values():
        assert entry["ai_declaration"] != "", "逐平台 AI 声明指引（报告项①配套）"


def test_build_pack_overlong_title_flagged_not_truncated() -> None:
    pack = publish_pack.build_pack([{"text": "字" * 21, "selected": True}], None, [])
    assert pack["platforms"]["小红书"]["title_fits"] is False
    assert pack["platforms"]["小红书"]["title"] == "字" * 21, "校验而非截断"


def test_build_pack_falls_back_to_first_title() -> None:
    pack = publish_pack.build_pack([{"text": "第一条", "selected": False}], None, [])
    assert pack["title"] == "第一条"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_publish_pack.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 publish_pack 模块**

创建 `service/dramaclip/engines/narration/publish_pack.py`：

```python
"""逐平台发布包：画幅/字数适配 + 实测话题注入 + 逐平台 AI 声明指引。

平台规格与话题库出处见 docs/research/2026-11-09-improvement-proposal.md
（竞品 G2 一手 + §2.2 四平台实测：#好剧推荐 ×70/#短剧推荐 ×36/
#因为一个片段看了整部剧 ×32/#短剧 ×32）。AI 声明指引是运营建议（二手），
法定隐式标识另走 export.aigc_metadata。标题全局上限已是 20 字
（titles._TITLE_MAX_CHARS），平台字数适配是校验而非截断。
"""

from __future__ import annotations

from typing import Any

#: 平台优先级按实测：抖音>视频号>快手；B站/小红书适配即可不重投入。
PLATFORM_ORDER = ("抖音", "视频号", "快手", "小红书", "B站")

PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "抖音": {
        "cover_ratio": (9, 16), "title_max": 20,
        "ai_declaration": "发布页勾选「内容由 AI 生成」声明入口（平台对 AI 合成内容有标注要求）",
    },
    "视频号": {
        "cover_ratio": (6, 7), "title_max": 20,
        "ai_declaration": "发布时勾选 AI 生成内容声明；未声明的 AI 内容平台可能自行加注",
    },
    "快手": {
        "cover_ratio": (9, 16), "title_max": 20,
        "ai_declaration": "发布页勾选 AI 生成声明入口",
    },
    "小红书": {
        "cover_ratio": (3, 4), "title_max": 20,
        "ai_declaration": "笔记设置勾选「内容疑似 AI 生成」声明",
    },
    "B站": {
        "cover_ratio": (16, 10), "title_max": 20,
        "ai_declaration": "投稿勾选创作声明中的「AI 生成」项",
    },
}

#: 实测高频话题（§2.2），注入顺序即频次降序。
MEASURED_TOPICS = ("好剧推荐", "短剧推荐", "因为一个片段看了整部剧", "短剧")
_TAG_CAP = 8


def inject_topics(tags: list[str]) -> list[str]:
    """LLM 标签尾部补实测高频话题（去重、帽 8）：槽满不注入，不挤掉用户标签。"""
    merged = list(tags)
    for topic in MEASURED_TOPICS:
        if len(merged) >= _TAG_CAP:
            break
        if topic not in merged:
            merged.append(topic)
    return merged


def build_pack(
    titles: list[dict[str, Any]], caption: str | None, tags: list[str]
) -> dict[str, Any]:
    """只读快照 → 逐平台包；选用标题优先，无选用取第一条。"""
    selected = next((str(t.get("text", "")) for t in titles if t.get("selected")), "")
    if not selected and titles:
        selected = str(titles[0].get("text", ""))
    merged_tags = inject_topics(tags)
    platforms: dict[str, Any] = {}
    for name in PLATFORM_ORDER:
        spec = PLATFORM_SPECS[name]
        platforms[name] = {
            "title": selected,
            "title_fits": len(selected) <= int(spec["title_max"]),
            "caption": caption,
            "tags": merged_tags,
            "cover_ratio": list(spec["cover_ratio"]),
            "ai_declaration": spec["ai_declaration"],
        }
    return {"title": selected, "caption": caption, "tags": merged_tags, "platforms": platforms}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_publish_pack.py -v`
Expected: PASS（5 个用例）

- [ ] **Step 5: 写失败测试（RPC + 封面重裁）**

创建 `service/tests/api/test_narration_publish_pack.py`：

```python
"""narration.publish_pack RPC：与详情页同一份库快照，规格与注入在服务端。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dramaclip.api import narration as narration_api
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcRequest


def _seed(memory_db: sqlite3.Connection, tmp_path: Path) -> str:
    project_id = str(projects_repo.create(memory_db, "发布剧", str(tmp_path))["id"])
    plan_id = str(
        plans_repo.create(
            memory_db, project_id, "full_narration", ["ep1"],
            {"mode": "full_narration", "timeline": []},
        )["id"]
    )
    plans_repo.set_titles(
        memory_db, plan_id,
        json.dumps([{"text": "当选标题", "selected": True}], ensure_ascii=False),
    )
    plans_repo.set_publish_meta(
        memory_db, plan_id,
        json.dumps({"caption": "文案", "tags": ["爽剧"]}, ensure_ascii=False),
    )
    return plan_id


def test_publish_pack_rpc(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    plan_id = _seed(memory_db, tmp_path)
    context = SimpleNamespace(conn=memory_db, settings={})
    router = Router()
    narration_api.register(router, context)  # type: ignore[arg-type]
    response = router.dispatch(
        RpcRequest(id="1", method="narration.publish_pack", params={"plan_id": plan_id})
    )
    assert response.error is None
    result: dict[str, Any] = response.result
    assert result["title"] == "当选标题"
    assert "好剧推荐" in result["tags"]
    assert result["platforms"]["小红书"]["cover_ratio"] == [3, 4]


def test_publish_pack_missing_plan(memory_db: sqlite3.Connection, tmp_path: Path) -> None:
    context = SimpleNamespace(conn=memory_db, settings={})
    router = Router()
    narration_api.register(router, context)  # type: ignore[arg-type]
    response = router.dispatch(
        RpcRequest(id="1", method="narration.publish_pack", params={"plan_id": "nope"})
    )
    assert response.error is not None
```

创建 `service/tests/api/test_export_platform_covers.py`：

```python
"""export_covers.generate_platform_covers：画幅重裁命令形状 + 成片回退 + 幂等。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import export_covers


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(conn=None, data_dir=tmp_path)


def test_composition_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")
    row = {"output_path": str(film), "narration_plan_id": "", "project_id": "p1"}
    seen: list[str | None] = []

    def fake_extract(
        video: Path, out: Path, *, seek_s: float = 1.5,
        title: str | None = None, composition_vf: str | None = None,
    ) -> bool:
        seen.append(composition_vf)
        out.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(export_covers.ffmpeg_cover, "extract_cover", fake_extract)
    result = export_covers.generate_platform_covers(_context(tmp_path), "e1", row)
    assert set(result["covers"]) == {"视频号", "小红书", "B站"}, "9:16 平台用基础封面"
    assert "scale=1080:1440:force_original_aspect_ratio=increase,crop=1080:1440" in seen
    assert "scale=1080:675:force_original_aspect_ratio=increase,crop=1080:675" in seen
    assert "scale=1080:1260:force_original_aspect_ratio=increase,crop=1080:1260" in seen


def test_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")
    covers_dir = tmp_path / "covers" / "exports"
    covers_dir.mkdir(parents=True)
    (covers_dir / "e1.小红书.jpg").write_bytes(b"old")
    row = {"output_path": str(film), "narration_plan_id": "", "project_id": "p1"}
    calls: list[str] = []

    def fake_extract(video: Path, out: Path, **_kw: object) -> bool:
        calls.append(out.name)
        out.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(export_covers.ffmpeg_cover, "extract_cover", fake_extract)
    result = export_covers.generate_platform_covers(_context(tmp_path), "e1", row)
    assert "e1.小红书.jpg" not in calls, "已存在不重截"
    assert result["covers"]["小红书"].endswith("e1.小红书.jpg")


def test_failure_goes_to_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    row = {"output_path": str(tmp_path / "missing.mp4"), "narration_plan_id": "", "project_id": "p1"}
    monkeypatch.setattr(export_covers.ffmpeg_cover, "extract_cover", lambda *a, **k: False)
    result = export_covers.generate_platform_covers(_context(tmp_path), "e1", row)
    assert result["covers"] == {}
    assert set(result["skipped"]) == {"视频号", "小红书", "B站"}
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_narration_publish_pack.py tests/api/test_export_platform_covers.py -v`
Expected: FAIL（RPC 未注册 / generate_platform_covers 不存在）

- [ ] **Step 7: RPC 与封面重裁实现**

修改 `service/dramaclip/api/narration.py`：

register() 内 `narration.update_titles` 行之后加：
```python
    router.register("narration.publish_pack", lambda params: publish_pack(context, params))
```

`update_titles` 函数定义之前插入：
```python
def publish_pack(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """逐平台发布包（只读）：标题/文案/标签与详情页同一份库快照。"""
    from dramaclip.engines.narration import publish_pack as pack_engine

    plan_id = str(params.get("plan_id", ""))
    row = plans_repo.get(context.conn, plan_id)
    if row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    meta = row.get("publish_meta") or {}
    return pack_engine.build_pack(
        row.get("titles") or [], meta.get("caption"), meta.get("tags") or []
    )
```

修改 `service/dramaclip/api/export_covers.py`：

import 区（`from dramaclip.infra.storage.repos import analysis as analysis_repo` 附近）加：
```python
from dramaclip.infra.storage.repos import episodes as episodes_repo
```

`ensure_covers` 函数定义之前插入：
```python
def generate_platform_covers(
    context: AppContext, export_id: str, row: dict[str, Any]
) -> dict[str, Any]:
    """逐平台封面重裁（增强项永不 raise）：源素材重截帧 → 成片回退 → skipped。

    不裁现有封面：基础封面字层在底部（cover.py y=h-text_h-h/16），居中裁切
    会把字切掉——从源按目标画幅 increase 填充 + 居中裁切重截，字层重烧。
    9:16 平台（抖音/快手）直接用基础封面，不进重裁。
    """
    from dramaclip.engines.narration.publish_pack import PLATFORM_ORDER, PLATFORM_SPECS

    out_path = Path(str(row.get("output_path") or ""))
    covers_dir = context.data_dir / "covers" / "exports"
    covers_dir.mkdir(parents=True, exist_ok=True)
    title: str | None = None
    plan_data: PlanData | None = None
    episode_paths: dict[str, str] = {}
    plan_id = str(row.get("narration_plan_id") or "")
    if plan_id:
        plan_row = plans_repo.get(context.conn, plan_id)
        if plan_row is not None:
            title = _cover_title(context, plan_row)
            try:
                plan_data = PlanData.model_validate(plan_row["plan_data"])
            except ValidationError:
                plan_data = None
    if plan_data is not None:
        episode_paths = {
            str(ep["id"]): str(ep["source_path"])
            for ep in episodes_repo.list_by_project(context.conn, str(row["project_id"]))
        }
    covers: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for name in PLATFORM_ORDER:
        ratio = PLATFORM_SPECS[name]["cover_ratio"]
        if tuple(ratio) == (9, 16):
            continue
        width = 1080
        height = round(width * ratio[1] / ratio[0])
        target = covers_dir / f"{export_id}.{name}.jpg"
        if target.is_file():
            covers[name] = str(target)
            continue
        composition = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
        ok = False
        if plan_data is not None:
            try:
                frame = _cover_source_frame(context.conn, plan_data, episode_paths, (width, height))
            except Exception as exc:  # noqa: BLE001 - 增强项自诊断失败退回成片截
                _note_degraded(context, "平台封面源截帧", f"{name} 封面改从成片截", exc)
                frame = None
            if frame is not None:
                source, seek_s, _base = frame
                ok = ffmpeg_cover.extract_cover(
                    source, target, seek_s=seek_s, title=title, composition_vf=composition
                )
        if not ok and out_path.is_file():
            ok = ffmpeg_cover.extract_cover(
                out_path, target, title=title, composition_vf=composition
            )
        if ok:
            covers[name] = str(target)
        else:
            skipped[name] = "截帧失败"
    return {"ok": True, "covers": covers, "skipped": skipped}
```

修改 `service/dramaclip/api/export.py`：

import 区：`from dramaclip.api.export_covers import ...` 一行（找到既有 import，把 `generate_platform_covers` 加入）；若 export_covers 的 import 是分散函数名列表，追加该名。

register() 内 `export.ensure_covers` 行之后加：
```python
    router.register("export.platform_covers", lambda params: platform_covers(context, params))
```

`ensure_covers` 包装函数附近（文件中段，与 submit 同级的公开函数区）加：
```python
def platform_covers(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """逐平台封面重裁：记录不存在拒收；截帧失败进 skipped（增强项不挡发布）。"""
    export_id = str(params.get("export_id", ""))
    row = exports_repo.get(context.conn, export_id)
    if row is None:
        raise RpcDomainError(_ERR_EXPORT_NOT_FOUND, f"导出记录不存在: {export_id}")
    return generate_platform_covers(context, export_id, row)
```

- [ ] **Step 8: 跑后端测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_narration_publish_pack.py tests/api/test_export_platform_covers.py tests/engines/narration/test_publish_pack.py -v`
Expected: PASS（10 个用例）

- [ ] **Step 9: protocol 类型 + client 方法**

修改 `protocol/ts/index.ts`，`SafeZoneMask` 之后加：

```typescript
/** 逐平台发布包条目（narration.publish_pack）：规格与话题注入在服务端单持。 */
export interface PlatformPackEntry {
  readonly title: string;
  readonly title_fits: boolean;
  readonly caption: string | null;
  readonly tags: string[];
  readonly cover_ratio: readonly [number, number];
  readonly ai_declaration: string;
}

export interface PlatformPack {
  readonly title: string;
  readonly caption: string | null;
  readonly tags: string[];
  readonly platforms: Record<string, PlatformPackEntry>;
}
```

修改 `desktop/src/services/client.ts`：

type import 列表加入 `PlatformPack`。`titlesApi` 对象内加：
```typescript
  publishPack: (planId: string): Promise<PlatformPack> =>
    rpc<PlatformPack>('narration.publish_pack', { plan_id: planId }),
```

`exportApi` 对象内加：
```typescript
  /** 逐平台封面重裁（小红书 3:4/B站 16:10/视频号 6:7）；失败进 skipped 不挡发布。 */
  platformCovers: (
    exportId: string,
  ): Promise<{ ok: boolean; covers: Record<string, string>; skipped: Record<string, string> }> =>
    rpc<{ ok: boolean; covers: Record<string, string>; skipped: Record<string, string> }>(
      'export.platform_covers', { export_id: exportId }),
```

- [ ] **Step 10: PlatformPackSection 组件 + 挂载**

创建 `desktop/src/features/works/PlatformPackSection.tsx`：

```tsx
/** 逐平台发布包：平台切换 → 标题适配/文案/话题/AI 声明指引 + 封面重裁 + 一键复制。
 *  规格与话题注入在服务端（publish_pack），本组件只渲染与搬运。 */
import { CopyOutlined, PictureOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Select } from 'antd';
import { useEffect, useState, type ReactElement } from 'react';
import type { PlatformPack } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { exportApi, mediaUrl, titlesApi } from '../../services/client';
import { errorText } from '../engines/errorText';
import { tokens } from '../../styles/theme';

const PLATFORMS = ['抖音', '视频号', '快手', '小红书', 'B站'];

export function PlatformPackSection({
  planId,
  exportId,
}: {
  planId: string;
  exportId: string;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [platform, setPlatform] = useState('抖音');
  const [pack, setPack] = useState<PlatformPack | null>(null);
  const [covers, setCovers] = useState<Record<string, string>>({});
  const [cropping, setCropping] = useState(false);
  useEffect(() => {
    if (planId === '') return;
    void titlesApi.publishPack(planId).then(setPack).catch(() => undefined);
  }, [planId]);
  const entry = pack?.platforms[platform];
  const copy = (): void => {
    if (entry === undefined) return;
    const text = [entry.title, entry.caption ?? '', entry.tags.map((t) => `#${t}`).join(' ')]
      .filter((part) => part !== '')
      .join('\n');
    void navigator.clipboard.writeText(text).then(() => message.success(`${platform}发布包已复制`));
  };
  const crop = (): void => {
    setCropping(true);
    void exportApi
      .platformCovers(exportId)
      .then((result) => {
        setCovers(result.covers);
        const skippedNames = Object.keys(result.skipped);
        if (skippedNames.length > 0) {
          message.warning(`部分平台封面未生成：${skippedNames.join('、')}`);
        } else {
          message.success('平台封面已生成');
        }
      })
      .catch((error: unknown) => message.error(errorText(error, '封面重裁失败')))
      .finally(() => { setCropping(false); });
  };
  const coverPath = covers[platform];
  return (
    <PageSection
      title="逐平台发布包"
      extra={
        <span style={{ display: 'flex', gap: tokens.spaceSm }}>
          <Select
            size="small"
            value={platform}
            onChange={setPlatform}
            options={PLATFORMS.map((name) => ({ value: name, label: name }))}
            style={{ width: 96 }}
          />
          <Button size="small" icon={<CopyOutlined />} disabled={entry === undefined} onClick={copy}>
            复制
          </Button>
          <Button size="small" icon={<PictureOutlined />} loading={cropping} onClick={crop}>
            生成平台封面
          </Button>
        </span>
      }
      dense
    >
      {entry === undefined ? (
        <div style={{ padding: tokens.spaceMd, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          {planId === '' ? '方案已删除，发布包无从生成' : '发布包加载中…（先生成候选标题）'}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
          <div style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textSecondary }}>
            {entry.title === '' ? '（无标题）' : entry.title}
            {!entry.title_fits && (
              <span style={{ marginLeft: tokens.spaceXs, color: tokens.errorText }}>
                超出该平台标题字数上限
              </span>
            )}
          </div>
          {entry.caption !== null && entry.caption !== '' && (
            <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
              {entry.caption}
            </div>
          )}
          <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
            {entry.tags.map((t) => `#${t}`).join(' ')}
          </div>
          <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
            AI 声明：{entry.ai_declaration}
          </div>
          {coverPath !== undefined && (
            <img
              src={mediaUrl(coverPath)}
              alt={`${platform}封面`}
              style={{ maxWidth: 240, borderRadius: 4, display: 'block' }}
            />
          )}
        </div>
      )}
    </PageSection>
  );
}
```

修改 `desktop/src/features/works/WorksDetailPage.tsx`：

import 区加：
```typescript
import { PlatformPackSection } from './PlatformPackSection';
```

`<TitlesSection ... />` 块之后、`<PublishDataSection ... />` 之前插入：
```tsx
            <PlatformPackSection planId={detail.planId} exportId={detail.job.id} />
```

（`ExportJob.id` 字段存在——protocol/ts/index.ts:471 `readonly id: string`。）

- [ ] **Step 11: 类型检查 + lint + 回归**

Run: `cd desktop && npm run typecheck && npx vitest run`
Expected: 全绿
Run: `cd service && ../.venv/Scripts/ruff check dramaclip tests && ../.venv/Scripts/python -m pytest tests/api/test_export.py tests/api/test_export_cover_title.py tests/api/test_export_cover_source_frame.py -q`
Expected: 全绿（封面族既有用例不被新函数破坏）

- [ ] **Step 12: Commit**

```bash
git add service/dramaclip/engines/narration/publish_pack.py service/dramaclip/api/narration.py service/dramaclip/api/export_covers.py service/dramaclip/api/export.py service/tests/engines/narration/test_publish_pack.py service/tests/api/test_narration_publish_pack.py service/tests/api/test_export_platform_covers.py protocol/ts/index.ts desktop/src/services/client.ts desktop/src/features/works/PlatformPackSection.tsx desktop/src/features/works/WorksDetailPage.tsx
git commit -m "feat(publish): 逐平台发布包——画幅重裁/字数校验/实测话题注入/AI 声明指引"
```

---

### Task 4: 剧名常驻层（报告项 ④）

**Files:**
- Create: `service/dramaclip/engines/exporter/drama_name_layer.py`
- Modify: `service/dramaclip/infra/config.py`（DEFAULTS，aigc 键之后）
- Modify: `service/dramaclip/engines/exporter/encoder.py`（import；cut_segment_args 签名 ~295 + filters ~373；export_plan 签名/转发；_export_plan_once 签名/prepare/inputs/cut 调用）
- Modify: `service/dramaclip/api/export.py`（import + export_plan 调用）
- Modify: `desktop/src/features/settings/sections.ts`（EXPORT_SECTION）
- Test: `service/tests/engines/exporter/test_drama_name_layer.py`（新建）

**Interfaces:**
- Consumes: `ffmpeg_cover.bundled_font_face() -> Path | None`；`ffmpeg_cover.filter_path(path) -> str`；config.get_bool。
- Produces: `drama_name_layer.enabled(settings) -> bool`；`drama_name_layer.layer_vf(face, textfile, out_size) -> str`；`drama_name_layer.prepare(work_dir, out_size, drama_name) -> DramaNameSpec(vf, fingerprint, textfile)`；`DramaNameLayerError`；encoder 新关键字参数 `burn_drama_name: str | None`（剧名文本，None/空=关）；cut_segment_args 新参数 `drama_name_vf: str | None`。Task 5 清单文案引用开关名 `export.drama_name_layer`。

**背景（实现者必读）**：镜像 ai_label.py 的全部纪律（段滤镜而非整片后处理、textfile 绕 CJK 转义、内容摘要进段签名、缺失硬失败）。位置左上角（`x=w*0.03, y=h*0.03`），与右上角 AI 标注避让，两者可同时开。字号除数 40（比 AI 标注的 34 小一号：剧名可长达十余字，56px×12 字=672px 仍安全但视觉过重，48px 更克制）。剧名取项目名（api/export.py:811 `project_name` 已在渲染核心可用）。

- [ ] **Step 1: 写失败测试**

创建 `service/tests/engines/exporter/test_drama_name_layer.py`：

```python
"""engines.exporter.drama_name_layer：剧名常驻层（settings export.drama_name_layer，默认关闭）。

业主裁决 2026-11-09：默认关、用户可开（报告「推广模式默认开」不采纳）。
镜像 test_ai_label.py 的钉法：默认关/滤镜形状（左上角避让 AI 角标）/
空剧名与缺字体硬失败/段滤镜/签名键缺席兼容。
"""

from __future__ import annotations

import inspect
import random
from pathlib import Path

import pytest

from dramaclip.engines.exporter import drama_name_layer, encoder
from dramaclip.infra import config


def test_default_is_off() -> None:
    assert config.DEFAULTS["export.drama_name_layer"] == "false"
    assert drama_name_layer.enabled({}) is False
    assert drama_name_layer.enabled({"export.drama_name_layer": "true"}) is True


def test_encoder_param_defaults_off() -> None:
    for fn in (encoder.export_plan, encoder._export_plan_once):
        param = inspect.signature(fn).parameters["burn_drama_name"]
        assert param.default is None
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
    param = inspect.signature(encoder.cut_segment_args).parameters["drama_name_vf"]
    assert param.default is None


def _drawtext_options(vf: str) -> dict[str, str]:
    body = vf[len("drawtext="):]
    opts: dict[str, str] = {}
    buf = ""
    in_quotes = False
    for ch in body:
        if ch == "'":
            in_quotes = not in_quotes
            buf += ch
        elif ch == ":" and not in_quotes:
            key, sep, value = buf.partition("=")
            if sep:
                opts[key] = value
            buf = ""
        else:
            buf += ch
    key, sep, value = buf.partition("=")
    if sep:
        opts[key] = value
    return opts


def test_layer_vf_top_left() -> None:
    vf = drama_name_layer.layer_vf(Path("C:/fonts/Noto.otf"), Path("C:/tmp/name.txt"), (1080, 1920))
    opts = _drawtext_options(vf)
    assert opts["fontfile"] == "'C\\:/fonts/Noto.otf'"
    assert opts["textfile"] == "'C\\:/tmp/name.txt'"
    assert opts["fontsize"] == "48", "1920/40=48，比 AI 标注小一号"
    assert opts["x"] == "w*0.03", "左上角：与右上角 AI 标注避让"
    assert opts["y"] == "h*0.03"


def _stub_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    face = tmp_path / "NotoSansSC-Regular.otf"
    face.write_bytes(b"fake-font")
    monkeypatch.setattr(drama_name_layer.ffmpeg_cover, "bundled_font_face", lambda: face)
    return face


def test_prepare_textfile_and_fingerprint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_font(monkeypatch, tmp_path)
    work = tmp_path / "work"
    spec = drama_name_layer.prepare(work, (1080, 1920), " 大明王朝 ")
    assert spec.textfile == work / ".drama-name.txt"
    assert spec.textfile.read_text(encoding="utf-8") == "大明王朝", "strip 后写入"
    assert len(spec.fingerprint) == 64
    assert str(spec.textfile) not in spec.fingerprint


def test_prepare_tracks_name_and_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    face = _stub_font(monkeypatch, tmp_path)
    first = drama_name_layer.prepare(tmp_path / "w", (1080, 1920), "剧A")
    second = drama_name_layer.prepare(tmp_path / "w", (1080, 1920), "剧B")
    assert first.fingerprint != second.fingerprint
    face.write_bytes(b"another-font")
    third = drama_name_layer.prepare(tmp_path / "w", (1080, 1920), "剧A")
    assert first.fingerprint != third.fingerprint


def test_empty_name_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_font(monkeypatch, tmp_path)
    with pytest.raises(drama_name_layer.DramaNameLayerError, match="剧名"):
        drama_name_layer.prepare(tmp_path, (1080, 1920), "  ")


def test_missing_font_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(drama_name_layer.ffmpeg_cover, "bundled_font_face", lambda: None)
    with pytest.raises(drama_name_layer.DramaNameLayerError, match="字体"):
        drama_name_layer.prepare(tmp_path, (1080, 1920), "大明王朝")


def test_is_segment_filter() -> None:
    args = encoder.cut_segment_args(
        "src.mp4", "out.mp4", start=0, end=1, audio="original", tts_audio=None,
        rng=random.Random(7), drama_name_vf="drawtext=textfile=name",
    )
    vf = args[args.index("-vf") + 1]
    assert "drawtext=textfile=name" in vf


def test_fingerprint_enters_signature(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from dramaclip.engines.narration.models import PlanData, TimelineSegment

    _stub_font(monkeypatch, tmp_path)
    source = tmp_path / "ep.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=1.0, audio="original")],
    )
    monkeypatch.setattr(
        encoder, "_run_cut", lambda args, *_a, **_k: Path(args[-1]).write_bytes(b"seg")
    )
    monkeypatch.setattr(encoder, "_concat", lambda _files, out: Path(out).write_bytes(b"film"))

    on_work = tmp_path / "on"
    encoder._export_plan_once(
        plan, {"ep1": str(source)}, tmp_path / "on.mp4", on_work, burn_drama_name="大明王朝"
    )
    on_sig = encoder._read_sig(on_work / "seg_000.mp4")
    assert on_sig is not None
    assert len(str(on_sig["inputs"]["drama_name"])) == 64

    off_work = tmp_path / "off"
    encoder._export_plan_once(plan, {"ep1": str(source)}, tmp_path / "off.mp4", off_work)
    off_sig = encoder._read_sig(off_work / "seg_000.mp4")
    assert off_sig is not None
    assert "drama_name" not in off_sig["inputs"], "关闭时键缺席，旧缓存不失效"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter/test_drama_name_layer.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现模块 + 登记键**

创建 `service/dramaclip/engines/exporter/drama_name_layer.py`：

```python
"""成片剧名常驻层（settings ``export.drama_name_layer``，默认关闭）。

业主裁决（2026-11-09）：默认关、用户可开。出品方要求推广切片全程带剧名；
开启后每段左上角烧剧名（项目名）——与右上角 AI 标注（ai_label）避让，
两者可同时开。实现镜像 ai_label：段滤镜 + textfile + 内容摘要进段签名；
字体缺失/剧名为空硬失败——用户明示要的东西不能静默缺席。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg import cover as ffmpeg_cover

_MARGIN_RATIO = 0.03
#: 比 AI 标注（/34）小一号：剧名可长达十余字，48px 视觉更克制。
_FONTSIZE_DIVISOR = 40
_FONTSIZE_MIN = 24


class DramaNameLayerError(RuntimeError):
    """剧名层准备失败（用户已开启，不能静默交付无剧名成片）。"""


@dataclass(frozen=True)
class DramaNameSpec:
    """一次导出共用的剧名层：滤镜串、段签名摘要与共享 textfile。"""

    vf: str
    fingerprint: str
    textfile: Path


def enabled(settings: config.Settings) -> bool:
    return config.get_bool(settings, "export.drama_name_layer")


def layer_vf(face: Path, textfile: Path, out_size: tuple[int, int]) -> str:
    """左上角 drawtext（纯函数）；x=w*3% 与 AI 标注的右上角镜像避让。"""
    _, height = out_size
    fontsize = max(_FONTSIZE_MIN, round(height / _FONTSIZE_DIVISOR))
    opts = [
        f"fontfile={ffmpeg_cover.filter_path(face)}",
        f"textfile={ffmpeg_cover.filter_path(textfile)}",
        f"fontsize={fontsize}",
        "fontcolor=white",
        "borderw=3",
        "bordercolor=black@0.9",
        f"x=w*{_MARGIN_RATIO:g}",
        f"y=h*{_MARGIN_RATIO:g}",
    ]
    return "drawtext=" + ":".join(opts)


def prepare(work_dir: Path, out_size: tuple[int, int], drama_name: str) -> DramaNameSpec:
    """准备剧名层（空剧名/缺字体抛 DramaNameLayerError）。

    摘要覆盖剧名 + 滤镜串 + 字体内容；textfile 路径不进摘要（随 work_dir 变）。
    """
    name = drama_name.strip()
    if not name:
        raise DramaNameLayerError("剧名为空，无法烧制剧名常驻层")
    face = ffmpeg_cover.bundled_font_face()
    if face is None:
        raise DramaNameLayerError("随包字体不可用，无法烧制剧名常驻层")
    work_dir.mkdir(parents=True, exist_ok=True)
    textfile = work_dir / ".drama-name.txt"
    textfile.write_text(name, encoding="utf-8")
    vf = layer_vf(face, textfile, out_size)
    payload = [name, vf, hashlib.sha256(face.read_bytes()).hexdigest()]
    fingerprint = hashlib.sha256("\0".join(payload).encode("utf-8")).hexdigest()
    return DramaNameSpec(vf=vf, fingerprint=fingerprint, textfile=textfile)
```

修改 `service/dramaclip/infra/config.py`，在 `"export.aigc_producer_code": "",` 之后插入：

```python
    # 剧名常驻层（业主裁决 2026-11-09）：默认关、用户可开；开启后每段左上角
    # 烧剧名（项目名），与右上角 AI 标注避让。出品方要求推广切片全程带剧名。
    "export.drama_name_layer": "false",
```

- [ ] **Step 4: encoder 接线**

修改 `service/dramaclip/engines/exporter/encoder.py`：

import 行改为：
```python
from dramaclip.engines.exporter import ai_label, aigc_metadata, drama_name_layer, loudness
```

`cut_segment_args` 签名：`ai_label_vf: str | None = None,` 之后加：
```python
    drama_name_vf: str | None = None,
```

filters 装配区：在 `if ai_label_vf:` 块**之前**插入：
```python
    if drama_name_vf:
        # 剧名层在 AI 标注之前挂（左上/右上各占一角，顺序稳定供单测钉形状）。
        filters.append(drama_name_vf)
```

`export_plan` 签名：`aigc_stamp: tuple[str, str] | None = None,` 之后加：
```python
    burn_drama_name: str | None = None,
```

`export_plan` 内两处 `_export_plan_once` 调用：`aigc_stamp=aigc_stamp,` 之后各加：
```python
            burn_drama_name=burn_drama_name,
```

`_export_plan_once` 签名：`aigc_stamp: tuple[str, str] | None = None,` 之后加：
```python
    burn_drama_name: str | None = None,
```

`_export_plan_once` 内 `label_spec = ...` 行之后加：
```python
    drama_spec = (
        drama_name_layer.prepare(work_dir, out_size, burn_drama_name)
        if burn_drama_name
        else None
    )
```

inputs 签名区：`if label_spec is not None:` 块之后加：
```python
        if drama_spec is not None:
            # 只在开启时入签名：关闭的旧缓存逐字节兼容（键缺席 == 未开启）。
            inputs["drama_name"] = drama_spec.fingerprint
```

cut_segment_args 调用处：`ai_label_vf=None if label_spec is None else label_spec.vf,` 之后加：
```python
                    drama_name_vf=None if drama_spec is None else drama_spec.vf,
```

- [ ] **Step 5: api/export.py 接线 + 设置页**

修改 `service/dramaclip/api/export.py`：

import 行改为：
```python
from dramaclip.engines.exporter import ai_label, aigc_metadata, drama_name_layer, encoder, loudness, selfcheck
```

`encoder.export_plan(...)` 调用内 `burn_ai_label=ai_label.enabled(context.settings),` 之后加：
```python
        # 剧名常驻层（业主裁决 2026-11-09：默认关、用户可开）：剧名取项目名。
        burn_drama_name=(
            project_name if drama_name_layer.enabled(context.settings) else None
        ),
```

修改 `desktop/src/features/settings/sections.ts`，EXPORT_SECTION 的 AIGC 编码字段之后加：

```typescript
    // 剧名常驻层（业主裁决 2026-11-09）：默认关、用户可开；出品方要求推广切片全程带剧名。
    {
      key: 'export.drama_name_layer',
      label: '剧名常驻层',
      type: 'switch',
      help: '开启后成片全程左上角烧制剧名（项目名），与右上角 AI 标注避让；出品方要求推广切片全程带剧名。默认关闭',
    },
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter/test_drama_name_layer.py tests/engines/exporter/test_ai_label.py -v`
Expected: PASS（新 9 用例 + ai_label 既有 8 用例全绿——段滤镜顺序变化不影响 ai_label 断言）

- [ ] **Step 7: 全量回归 + lint + 类型**

Run: `cd service && ../.venv/Scripts/python -m pytest && ../.venv/Scripts/ruff check dramaclip tests`
Expected: 全绿
Run: `cd desktop && npm run typecheck`
Expected: 无错误

- [ ] **Step 8: Commit**

```bash
git add service/dramaclip/engines/exporter/drama_name_layer.py service/dramaclip/infra/config.py service/dramaclip/engines/exporter/encoder.py service/dramaclip/api/export.py service/tests/engines/exporter/test_drama_name_layer.py desktop/src/features/settings/sections.ts
git commit -m "feat(export): 剧名常驻层——左上角段滤镜镜像 AI 标注（默认关，业主裁决 2026-11-09）"
```

---

### Task 5: 发布前自查清单（报告项 ⑤）

**Files:**
- Create: `desktop/src/features/works/publishCopy.ts`
- Create: `desktop/src/features/works/PublishChecklistSection.tsx`
- Modify: `desktop/src/features/works/WorksDetailPage.tsx`（挂载）
- Test: `desktop/src/features/works/__tests__/publishCopy.test.ts`（新建）

**Interfaces:**
- Consumes: `TitleCandidate` / `PublishMeta`（protocol）；`detail.titles` / `detail.publish`（useWorkDetail 已有）；PageSection / Antd Checkbox。
- Produces: `CHECKLIST_ITEMS: readonly string[]`（5 条）；`buildPublishCopy(titles, publish) -> string`；`PublishChecklistSection` 组件。无后端改动——清单是动作输出物，不是数据（不做授权存证，裁决）。

**背景（实现者必读）**：五项清单来自报告（授权覆盖/挂载链接/标题封面相符/全程剧名/话题组）。勾选态仅本次访问有效（useState，不落库）——它是发布前的动作提醒，不是存证记录。一键复制把标题+文案+话题+未勾选清单拼成纯文本，粘贴进发布笔记即可逐项核对。

- [ ] **Step 1: 写失败测试**

创建 `desktop/src/features/works/__tests__/publishCopy.test.ts`：

```typescript
import { describe, expect, it } from 'vitest';
import { buildPublishCopy, CHECKLIST_ITEMS } from '../publishCopy';

describe('buildPublishCopy', () => {
  it('选用标题优先，拼接文案/话题/清单', () => {
    const text = buildPublishCopy(
      [{ text: '落选', selected: false }, { text: '当选', selected: true }],
      { caption: '一句文案', tags: ['好剧推荐'] },
    );
    expect(text).toContain('【标题】当选');
    expect(text).toContain('【文案】一句文案');
    expect(text).toContain('#好剧推荐');
    expect(text).toContain('□ 授权覆盖');
    expect(text.split('□').length - 1).toBe(CHECKLIST_ITEMS.length);
  });

  it('无选用取第一条；空物料仍输出清单', () => {
    expect(buildPublishCopy([{ text: '第一条', selected: false }], null)).toContain('【标题】第一条');
    expect(buildPublishCopy([], null).startsWith('【发布前自查】')).toBe(true);
  });

  it('清单五项齐备（报告项⑤）', () => {
    expect(CHECKLIST_ITEMS).toHaveLength(5);
    expect(CHECKLIST_ITEMS.join('|')).toContain('挂载链接');
    expect(CHECKLIST_ITEMS.join('|')).toContain('全程剧名');
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd desktop && npx vitest run src/features/works/__tests__/publishCopy.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现纯函数 + 组件 + 挂载**

创建 `desktop/src/features/works/publishCopy.ts`：

```typescript
/** 发布前自查清单 + 发布包一键复制文本（纯函数）。
 *  清单是动作提醒不是存证数据——不落库（授权存证否决裁决 2026-09-10）。 */
import type { PublishMeta, TitleCandidate } from '@dramaclip/protocol';

export const CHECKLIST_ITEMS = [
  '授权覆盖：确认本剧推广授权覆盖目标平台与切片用途',
  '挂载链接：确认挂载组件/小程序链接已配置且指向正确剧集',
  '标题封面相符：封面帧与标题卖的是同一亮点，不做点击错位',
  '全程剧名：已开「剧名常驻层」开关，或标题/文案含剧名',
  '话题组：含实测高频话题（#好剧推荐 #因为一个片段看了整部剧）',
] as const;

export function buildPublishCopy(titles: TitleCandidate[], publish: PublishMeta | null): string {
  const selected = titles.find((t) => t.selected)?.text ?? titles[0]?.text ?? '';
  const caption = publish?.caption ?? '';
  const tags = publish?.tags.length ? publish.tags.map((t) => `#${t}`).join(' ') : '';
  const parts = [
    selected !== '' ? `【标题】${selected}` : '',
    caption !== '' ? `【文案】${caption}` : '',
    tags !== '' ? `【话题】${tags}` : '',
    `【发布前自查】\n${CHECKLIST_ITEMS.map((item) => `□ ${item}`).join('\n')}`,
  ];
  return parts.filter((part) => part !== '').join('\n');
}
```

创建 `desktop/src/features/works/PublishChecklistSection.tsx`：

```tsx
/** 发布前自查清单（报告项⑤）：动作清单 + 发布包一键复制；勾选态仅本次访问有效。 */
import { CopyOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Checkbox } from 'antd';
import { useState, type ReactElement } from 'react';
import type { PublishMeta, TitleCandidate } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { buildPublishCopy, CHECKLIST_ITEMS } from './publishCopy';

export function PublishChecklistSection({
  titles,
  publish,
}: {
  titles: TitleCandidate[];
  publish: PublishMeta | null;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [checked, setChecked] = useState<boolean[]>(CHECKLIST_ITEMS.map(() => false));
  const copy = (): void => {
    void navigator.clipboard.writeText(buildPublishCopy(titles, publish)).then(() => {
      message.success('发布包与自查清单已复制');
    });
  };
  return (
    <PageSection
      title="发布前自查"
      extra={
        <Button size="small" icon={<CopyOutlined />} onClick={copy}>
          一键复制发布包
        </Button>
      }
      dense
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
        {CHECKLIST_ITEMS.map((item, index) => (
          <Checkbox
            key={item}
            checked={checked[index]}
            onChange={(event) => {
              setChecked(checked.map((value, i) => (i === index ? event.target.checked : value)));
            }}
          >
            <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
              {item}
            </span>
          </Checkbox>
        ))}
      </div>
      <div style={{ marginTop: tokens.spaceXs, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        勾选态仅本次访问有效；清单是动作提醒，不是授权存证
      </div>
    </PageSection>
  );
}
```

修改 `desktop/src/features/works/WorksDetailPage.tsx`：

import 区加：
```typescript
import { PublishChecklistSection } from './PublishChecklistSection';
```

`<PlatformPackSection ... />` 之后、`<PublishDataSection ... />` 之前插入：
```tsx
            <PublishChecklistSection titles={detail.titles} publish={detail.publish} />
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd desktop && npx vitest run src/features/works/__tests__/publishCopy.test.ts`
Expected: PASS（3 个用例）

- [ ] **Step 5: 类型检查 + 全量前端测试**

Run: `cd desktop && npm run typecheck && npx vitest run`
Expected: 全绿（worksDetail.test.tsx 渲染详情页——新增两个分区会拉 RPC；该测试的 bridge mock 需覆盖新方法。若红：读 `__tests__/worksDetail.test.tsx` 的 mock setup，给 `narration.publish_pack` 返回 `{title:'',caption:null,tags:[],platforms:{}}`、`subtitle.safe_zone` 返回几何常量、`export.platform_covers` 返回 `{ok:true,covers:{},skipped:{}}`。）

- [ ] **Step 6: Commit**

```bash
git add desktop/src/features/works/publishCopy.ts desktop/src/features/works/PublishChecklistSection.tsx desktop/src/features/works/WorksDetailPage.tsx desktop/src/features/works/__tests__/publishCopy.test.ts
git commit -m "feat(publish): 发布前自查清单——五项动作提醒+发布包一键复制（不落库存证）"
```

---

## 真机 DoD（批次一验收，单测绿不替代）

在开发机用真实素材走一遍（无头 RPC 或桌面端均可；写 live 库前确认项目可弃）：

1. **隐式标识**：设置开 `export.aigc_metadata` + 填编码 → 导出 → `ffprobe -v error -show_entries format_tags=comment -of json <成片>` 读回 comment，Base64 解码验证 `AIGC=` 前缀与三字段；再开 BGM 导出一次验证后置遍不丢标；单段方案（一集一条）导出验证 copyfile 分支同样有标。编码留空提交 → submit 即拒。
2. **安全区**：预览弹层开「安全区」开关，三条遮罩位置与 9:16 画面贴合；含源字幕带的成片自检成绩单出现 safe_zone 灰项且 overall_state 不变红。**真机校验遮罩像素值**（对照抖音/视频号真实发布页截图），偏差记入 `docs/research/` 后续固化参数表——本批先按推断值交付。
3. **发布包**：生成候选标题后打开逐平台发布包，切换五平台；「生成平台封面」产出三张重裁 jpg，目视标题字层完整（不被裁切）；复制文本含注入的实测话题。
4. **剧名层**：开 `export.drama_name_layer` 导出 → 左上角全程剧名、右上角无冲突；同时开 AI 标注验证两角共存；断点续跑：改剧名（项目改名）重导 → 段签名失效重编。
5. **清单**：勾选态刷新后重置；一键复制文本五项齐全。
6. **回归**：`scripts/verify_modes.py` 真机门禁跑一轮（默认关状态下两条新开关不改变既有出片字节——ai_label 同款验收口径）。

## Self-Review 记录

- **Spec 覆盖**：项①Task 1（含逐平台 AI 声明指引在 Task 3 的 ai_declaration 字段）；项②Task 2；项③Task 3；项④Task 4；项⑤Task 5。报告项①「发布物料附逐平台 AI 声明指引」由 Task 3 PLATFORM_SPECS.ai_declaration 落地——跨任务依赖已在 Interfaces 标注。
- **占位符扫描**：无 TBD/TODO；所有代码步给出完整代码；两处「实现时读…确认」是条件分支指引（SelfCheckBadge.key 联合类型、worksDetail mock），非占位。
- **类型一致性**：`aigc_stamp: tuple[str, str] | None` 在 encoder/api/测试三处同名；`burn_drama_name: str | None` 同；`generate_platform_covers(context, export_id, row)` 签名在实现与测试一致；`SafeZoneMask`/`PlatformPack` 在 protocol/client/组件三处同名；RPC 方法名 `subtitle.safe_zone`/`narration.publish_pack`/`export.platform_covers` 前后端逐字一致。