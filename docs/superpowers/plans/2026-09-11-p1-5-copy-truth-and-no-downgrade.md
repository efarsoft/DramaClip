# P-1.5 文案真值化 + 禁止降级 + 响度目标 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每一条解说成片的所有文字都出自编剧模型、让每一处质量缺陷都以失败收场而不是静默降档，并把成片响度钉在统一目标上。

**Architecture:** 三层切分——**结构层**（各模式编排器只产出时间轴与"文案槽位"，不再自带任何成稿句子）、**语言层**（新增 `copywriter.py` 一次 LLM 调用填满全部槽位，`planner` 由此翻成 `llm_script`）、**执行层**（TTS 与混音/响度不再容忍缺件：任一段旁白拿不到合格音频即整条方案失败）。出口判据由 `scripts/verify_modes.py` 真机门禁持有：九模式重跑，除 `raw_clip`/`subtitle_flow` 外 `planner` 全为 `llm_script`，且每条成片实测响度落在目标窗口内。

**Tech Stack:** Python 3.12 / pydantic v2 / stdlib urllib（ADR-005 统一 OpenAI 协议）/ ffmpeg（`amix`、`loudnorm` 两遍法、`ebur128` 测量）/ pytest。

规格出处：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §12（批次定义）、§3.3.1（降级裁决表，Task 1 入库）、§11（服务对接清单）、§3.3（静默禁止清单）。

---

## 唯一需要产品拍板的数值（已给默认值，不必等）

**响度目标 `export.loudness_target_lufs = -14`、`export.loudness_true_peak_dbtp = -1.5`。**

依据：九模式实测带旁白成片 −22~−30 dB、纯原声 −12 dB，六个样本同向；−14 LUFS 是移动端短视频通行落点，也与现状"纯原声模式本来就在 −12 dB"最接近，不会让老片突然变轻。两个键在设置页可达（Task 8），改主意就是改一个数字，不用改代码。

---

## 降级分类表（本计划的裁决依据，Task 1 落进规格）

§12 引用了"§11 那张降级分类表"，但 §11 是服务对接清单，**降级分类表从未被写出**——这是规格自身的空洞，Task 1 补上。下表是本计划对每一处降级的裁决，后续任务的"改抛错/保留"全部由此导出：

| 降级点 | 位置 | 裁决 | 理由 |
|---|---|---|---|
| 解说文案 → 硬编码模板池 | `modes_w5._CROSS_NARRATIONS`、`modes_w8.narration_texts_for`、`modes_p2` 两模式、`pipeline.intro_text` | **禁止 → 抛错** | 成片"说了什么"被换成一句假话，是质量本体的塌方 |
| 剧本驱动失败 → 规则编排 | `pipeline.build_from_script_dialogue`（死）、`script_driver` 返回 `None`、`_generate_one` 回落 `build_plan` | **禁止 → 抛错** | 同上，且失败会伪装成"这个模式本来就是这版" |
| TTS 单段失败 → 该段回退原声 | `pipeline.synthesize_narration_texts` | **禁止 → 抛错** | 半条旁白的片子不可交付；失败粒度=单条方案，不整批停摆 |
| `amix` 默认归一化把音量砍半 | `encoder.cut_segment_args` | **禁止 → 关掉归一化** | 声明的 0.2/0.12 是假的，响度失控无人负责 |
| 成片响度实测超容差 → 放行 | `exporter/loudness.py`（P-1.5 新建） | **禁止 → 抛错** | 响度观众听得见；两遍法后的实测复核就是它的验收线 |
| 口味层 LLM 选题失败 → 题材静态映射 | `script_driver`（现）/ `resolve_run_style`（后） | **允许，但必须留痕** | 兜底值仍是人写的风格指令，不是假文案 |
| 分析层 LLM → 关键词打分 | `semantic/conflict.py`、`genre.py` | **允许，界面必须可见** | 影响选段而非文案；可见性归 §3.3，界面在 P-3 |
| CUDA → CPU | `analysis/transcriber.py` | **允许** | 同结果，只慢 |
| 下载多源降级 | `model_manager/downloader.py` | **允许** | 同一个文件 |
| 同名 `.srt` 缺失 → 库内 ASR 保护区 | `encoder.export_plan` | **允许** | 两个都是保护区来源，等价 |
| `raw_clip` 冲突分不足 → 放宽取全部场景 | `modes.build_raw_clip` | **允许** | 素材可得性问题，不改变观众听到的内容 |
| `ass` 路径跨盘 → 双转义保底 | `encoder._escape_filter_path` | **允许，但记为已知缺陷** | 工程兜底；跨盘转义脆弱性需根治，`docs/05` 的 Backlog 无此条且该文件用户自维护，**本行即登记处** |

---

## 文件结构

**新建**
- `service/dramaclip/engines/narration/copywriter.py` —— 语言层：槽位 → 一条 LLM 调用 → 全部文案。
- `service/dramaclip/engines/exporter/loudness.py` —— Phase C：两遍 `loudnorm` + 响度复核。
- `service/tests/engines/narration/test_copywriter.py`
- `service/tests/engines/exporter/test_loudness.py`
- `service/tests/api/test_narration_no_downgrade.py`

**修改**
- `service/dramaclip/engines/narration/models.py` —— `NarrationText` 槽位化（`slot` / `window`），`text` 默认空。
- `service/dramaclip/engines/narration/modes/__init__.py`、`modes_w5.py`、`modes_w8.py`、`modes_p2.py` —— 删模板池，建槽位并写 `narration_id`。
- `service/dramaclip/engines/narration/pipeline.py` —— 删 `intro_text` / `build_from_script_dialogue`；回填改为按 `narration_id` 取用且失败即抛。
- `service/dramaclip/engines/narration/scriptwriter.py` —— `FUNDAMENTALS` 转公开、失败改抛错、`dump_trace` 转公开。
- `service/dramaclip/engines/narration/script_driver.py` —— 风格解析上提为 `resolve_run_style`，本模块不再返回 `None`。
- `service/dramaclip/api/narration.py` —— 任务级注入（风格一次、跨集输入一次）、七模式统一走语言层、删死码。
- `service/dramaclip/engines/exporter/encoder.py` —— `amix … :normalize=0`、Phase C 接入。
- `service/dramaclip/infra/config.py` —— `get_float` + 两个响度键。
- `desktop/src/features/settings/sections.ts` —— 出片区新增响度两字段。
- `scripts/verify_modes.py` —— LUFS/真峰值测量、`planner` 断言、LLM 预检。
- `docs/service/02-引擎设计.md`、`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md`

**不动**：`docs/05-开发路线图.md`（用户自维护）、`service/dramaclip/api/engine_configs.py` 及其数据文件（他人所有）、`data/data.db`（只读，门禁跑副本）。

**提交纪律**：只 `git add` 显式路径，禁止 `git add -A`/`.`——同树同分支另有工程师在提交，宽 add 会卷走别人的暂存。

### 实现定案修正（Task 2/3 落地后经两轮审查确定，后续任务以此为准）

**本文件 Task 2/3 代码块里的 `NarrationText.slot` 与 `.window` 已经不存在。pydantic 默认忽略未知 kwargs——照抄旧字段名不会报错，只会静默丢字段。** 定案：

| 项 | 定案 | 原因 |
|---|---|---|
| 槽位职责字段 | **`brief`**（不是 `slot`）；辅助函数 `_slot_brief` | `NarrationText` 本身就是槽位，字段再叫 `slot` 读不通；仓内一度 `slot`/`role`/`职责` 三名并存；`role` 与 `dual_host` 的 `speaker` 撞意 |
| 槽位画面区间 | **无独立字段**，由 `narration_id` 反查 `TimelineSegment.start/end` | `window` 是段区间的第三份拷贝，而 `synthesize_narration_texts` 回填时会改写段 `end`，两份答案必然打架。文案恒在回填之前生成，故段区间即计划区间 |
| 段↔槽位配对 | 反查不到即 `raise ValueError("槽位 X 没有配对画面段")` | 原 `window is None` 静默降级分支，等于用一句"别编造"去回答一个编排器 bug |
| 时间戳格式化 | `scriptwriter.clock`（公开，与 `FUNDAMENTALS`/`dump_trace` 同批） | 曾与 `copywriter._clock` 逐字重复 |
| TTS 测试替身 | **空文案必须抛**，与真引擎一致（`tts/base.py` 的 ffprobe `check=True` 会死在 0 字节文件上） | 否则"`text` 默认空串"这个最该炸的情形被替身判成通过——实测已证明旧替身确实掩盖过一次 |
| 配对断言 | `tests/engines/narration/conftest.py::assert_slots_paired`，六个模式测试共用 | 同一条不变量原先有五种写法 |
| LLM 拒绝分支 | 未知 id、空答复、超长、漏槽 + 配对缺失，共五条，**每条都做过"删掉这行分支看它红不红"** | 见 Task 3 实测修正节 |

`copywriter.write_plan_copy` 的 `mode_label` 已改为**必填**关键字参数。
`service/pyproject.toml` 一度带着他人未提交的 lint 配置，本批次的 ruff/mypy/pytest 读数均含其工作区改动。

---

## Task 1: 降级分类表入规格 + 三处失效文案更正

纯文档任务，但必须排在最前：Task 5/6 的每一处"改抛错"都引用这张表，实施者没有表就只能猜。

**Files:**
- Modify: `docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md`（§3.3 之后、§4.2、§12）
- Modify: `docs/service/02-引擎设计.md`（§3 表、§8 表、`llm_client` 行）

- [x] **Step 1: 在 §3.3 之后插入"降级分类表"**

把上文《降级分类表》整节（含全部 12 行）作为 `### 3.3.1 降级裁决表（P-1.5 定案）` 插入 §3.3 之后，并在表前加一句：

> **裁决口径**：改变观众所听所见内容的降级一律禁止（抛错，失败粒度=单条方案）；只改变成本或可用素材的降级允许，但必须留痕。

- [x] **Step 2: 修掉 §12 的空引用**

`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md:444` 的 ②：

```markdown
② 把 §3.3.1「降级裁决表」里**禁止级**的全部改为抛错（失败粒度是单条方案，不整批停摆）；
```

- [x] **Step 3: 修 §12 出口判据的口径（7 个模式，不是 4 个）**

§12 P-1.5「内容」① 只点了 cross/ultra_short/full/intro，但 `modes_p2.py` 的双人对谈与内心独白同样是模板池，出口判据却要求"除 raw_clip/subtitle_flow 外全为 llm_script"。把 ① 改为：

```markdown
- **内容**：① 把 intro/cross/ultra_short/full/dual_host/inner_monologue 六个模板池模式的文案接上真 LLM 通路
  （与 dialogue 已跑通的编剧链共用同一个语言层模块 `narration/copywriter.py`）；
```

- [x] **Step 4: 修 §4.2 空态第②步的假承诺**

`docs/.../design.md:145` 现写「跳过则文案走关键词降级」——P-1.5 之后这句话不成立了。改为：

```markdown
② 配 LLM（**解说类模式必需**：七个解说模式的文案由编剧模型产出，未配置则这些模式逐条失败并说明原因，
   仅「纯原片剪辑」「字幕金句流」不依赖 LLM）
```

- [x] **Step 5: 同步 `docs/service/02-引擎设计.md`**

三处：

1. `llm_client.py` 行的「调用方走关键词降级（W3 DoD）」改为「分析层走关键词降级；**解说文案不降级，未配置即失败**（§3.3.1）」。
2. §3 表 `scriptwriter.py` 行之后新增一行：

```markdown
| `copywriter.py` | 逐槽文案编剧（P-1.5） | 编排器只产出槽位（`slot` 职责 + `window` 素材区间），一次 LLM 调用填满全部槽位置 `planner=llm_script`；漏槽/超长/空文即抛，**无模板兜底**（承接原 `hook_generator.py` 职责） |
```

3. §8 `encoder.py` 行补 Phase C：

```markdown
| `loudness.py` | 成片响度归一（Phase C） | 拼接完成后整片两遍 `loudnorm` 至 `export.loudness_target_lufs/-true_peak_dbtp`，视频流复制；复核实测超容差即抛（降级禁止） |
```

- [x] **Step 6: 校验无残留**

Run: `grep -rn "关键词降级" docs/service/02-引擎设计.md docs/superpowers/specs/`
Expected: 只剩分析层一处（`llm_client.py` 行里"分析层走关键词降级"），解说文案处不再出现该说法。
Run: `grep -rn "§11 那张" docs/superpowers/specs/`
Expected: 无输出（空引用已改掉）。
Run: `grep -rn "hook_generator" docs/service/02-引擎设计.md`
Expected: 仅剩 `copywriter.py` 行里"承接原 hook_generator.py 职责"这一处提及。

- [x] **Step 7: 提交**

```bash
git add docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md docs/service/02-引擎设计.md docs/superpowers/plans/2026-09-11-p1-5-copy-truth-and-no-downgrade.md
git commit -m "docs(spec): 补降级裁决表并修正 P-1.5 出口口径（七模式模板池、LLM 非可跳过项）"
```

---

## Task 2: 结构层——旁白槽位化，删空模板池

把"选了哪几段画面 + 每段该说什么话"留在编排器里，把"话本身"赶出去。本任务结束后六个模式的 `narration_texts[*].text` 全是空串，`planner` 仍是 `rule`——**这是有意的中间态**，Task 3 才补上语言层；因此本任务必须与 Task 3 连续实施，中间不得发布。

**Files:**
- Modify: `service/dramaclip/engines/narration/models.py:27-34`
- Modify: `service/dramaclip/engines/narration/modes/__init__.py:50-67`
- Modify: `service/dramaclip/engines/narration/modes_w5.py:22-30,64-77,96-129`
- Modify: `service/dramaclip/engines/narration/modes_w8.py`
- Modify: `service/dramaclip/engines/narration/modes_p2.py`
- Test: `service/tests/engines/narration/test_modes.py`、`test_modes_w5.py`、`test_modes_w8.py`、`test_modes_p2.py`

- [x] **Step 1: 写失败测试——槽位结构**

在 `service/tests/engines/narration/test_modes_w5.py` 末尾新增（既有 `test_ultra_short_structure` 的文案断言到 Step 9 一并改）：

```python
def test_cross_slots_carry_role_and_window() -> None:
    """编排器只负责"这里要说什么"，句子本身归编剧：text 必须为空、槽位信息必须齐。"""
    plan = build_cross("ep1", _scenes(), _STRATEGY)
    assert plan.narration_texts, "至少要有一个旁白槽位"
    for text in plan.narration_texts:
        assert text.text == "", "文案池已删除，编排器不得再自带任何成稿句子"
        assert text.slot, "槽位职责缺失 → 编剧无从下笔"
        assert text.window is not None and text.window[1] > text.window[0]
    by_id = {segment.narration_id: segment for segment in plan.timeline if segment.narration_id}
    assert set(by_id) == {text.id for text in plan.narration_texts}, "段与文案必须按 id 两两配对"
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_modes_w5.py -q`
Expected: FAIL —— `AssertionError` 于 `text.text == ""`（当前是模板句）。

- [x] **Step 3: `NarrationText` 槽位化**

`service/dramaclip/engines/narration/models.py`，整块替换 `NarrationText`：

```python
class NarrationText(BaseModel):
    """旁白槽位：编排器定"在哪段画面、以什么职责说话"，编剧填 `text`，配音回填音频与时长。"""

    id: str
    text: str = ""
    voice: str | None = None
    audio_path: str | None = None
    duration: float | None = None
    # 槽位职责，进编剧 prompt：如「原声之间的串联：承接上一幕、留下一幕的悬念」
    slot: str = ""
    # 该槽位覆盖的素材区间（其所在集内秒）：编剧据此读台词，不做位置推断
    window: tuple[float, float] | None = None
```

- [x] **Step 4: `modes.build_intro` 建槽位**

`service/dramaclip/engines/narration/modes/__init__.py`：在常量区加 `_INTRO_SLOT_ID = "intro-1"`，并把 `build_intro` 换成：

```python
def build_intro(
    intro_episode_id: str,
    body_scenes: list[ConflictScore],
    strategy: StrategySpec,
) -> PlanData:
    """片头解说编排（原案 6.4）：引子旁白段（画面为正文首镜）+ 正片高光（原声）。

    引子文案由编剧层填充；段时长在导出阶段由 TTS 实际时长回填。
    """
    ordered = sorted(body_scenes, key=lambda s: s.start)
    timeline = _fit_duration(intro_episode_id, ordered, strategy, intro_first=True)
    if not timeline:
        return PlanData(mode="intro_narration", timeline=timeline, strategy=strategy)
    opener = timeline[0].model_copy(update={"narration_id": _INTRO_SLOT_ID})
    timeline[0] = opener
    return PlanData(
        mode="intro_narration",
        timeline=timeline,
        narration_texts=[
            NarrationText(
                id=_INTRO_SLOT_ID,
                slot="片头钩子：两三句把最大冲突抛出来，收尾留悬念，不要复述剧情梗概",
                window=(opener.start, opener.end),
            )
        ],
        strategy=strategy,
    )
```

同时删除 `_fit_duration` 里的 `_ = intro_first` 空转行（`intro_first` 已在函数内被使用，注释也过期）。

- [x] **Step 5: `modes_w5` 删池、建槽位**

`service/dramaclip/engines/narration/modes_w5.py`：

1. 删除 `_CROSS_NARRATIONS` 整块（含其上注释「旁白串联文案池」）。
2. 文件 docstring 第 3 行改为 `"""W5 模式编排：交叉解说（原案 6.3）与超短悬念版（原案 6.9）。\n\n编排只产出画面结构与旁白槽位，文案一律由 narration.copywriter 生成（无模板兜底）。`
3. `build_cross` 循环体里，旁白段改为先建文案再建段（两路共用一个 id）：

```python
        anchor = picked[index + 1] if index + 1 < len(picked) else scene
        slot_id = f"cross-{index + 1}"
        texts.append(
            NarrationText(
                id=slot_id,
                slot="原声片段之间的串联：承接上一幕，给下一幕留半句钩",
                window=(anchor.start, anchor.start + narration_seconds),
            )
        )
        segments.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(anchor.start, 3),
                end=round(anchor.start + narration_seconds, 3),
                audio="narration",
                narration_id=slot_id,
            )
        )
```

（`subtitle_text=` 一并删除：解说字幕在配音回填时写入，编排期无文案可写。）

4. `build_ultra_short` 换体（去掉 `project_name` 形参——项目名是文案的语言材料，属于编剧层）：

```python
def build_ultra_short(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
) -> PlanData:
    """超短悬念版（10-20s）：钩子旁白 → 最高冲突原声画面 → 收尾引导。"""
    if not scenes:
        return PlanData(mode="ultra_short_hook", strategy=strategy)
    best = max(scenes, key=lambda s: s.score)
    scene_span = min(best.end - best.start, _ULTRA_CONFLICT_S)
    slots = (
        ("hook-1", "开场钩子：一句，最大反差或最狠的悬念，不超过 20 字",
         (best.start, best.start + _HOOK_TTS_FALLBACK_S)),
        ("cta-1", "收尾引导：一句，指向"结局更狠"并引导点击，不超过 15 字",
         (best.end - _HOOK_TTS_FALLBACK_S, best.end)),
    )
    timeline = [
        TimelineSegment(
            episode_id=episode_id,
            start=round(slots[0][2][0], 3),
            end=round(slots[0][2][1], 3),
            audio="narration",
            narration_id=slots[0][0],
        ),
        TimelineSegment(
            episode_id=episode_id,
            start=round(best.start, 3),
            end=round(best.start + scene_span, 3),
            audio="original",
        ),
        TimelineSegment(
            episode_id=episode_id,
            start=round(slots[1][2][0], 3),
            end=round(slots[1][2][1], 3),
            audio="narration",
            narration_id=slots[1][0],
        ),
    ]
    texts = [NarrationText(id=sid, slot=slot, window=window) for sid, slot, window in slots]
    return PlanData(
        mode="ultra_short_hook", timeline=timeline, narration_texts=texts, strategy=strategy
    )
```

- [x] **Step 6: `modes_w8` 删池**

`service/dramaclip/engines/narration/modes_w8.py`：删除 `narration_texts_for` 整个函数，`build_full` 换成（同时去掉 `project_name` / `genre` 两个形参）：

```python
def _slot_role(index: int, count: int, score: int) -> str:
    """按场景在叙事弧中的位置给编剧下达职责指令（位置是真信息，模板把它丢掉了）。"""
    if index == 0:
        return "开篇：一句话把人推到冲突跟前，交代处境但不解释设定"
    if index == count - 1:
        return "收尾：留结局缺口 + 一句点击引导"
    if score >= 85:
        return "高潮：只讲这一幕最狠的那个信息点"
    return "推进：承接上一幕，说清冲突又升级了什么"


def build_full(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
) -> PlanData:
    """全片解说编排：场景按时间线全程覆盖，全部原声压低（ducked）。"""
    ranked = sorted(scenes, key=lambda s: -s.score)[:_MAX_SCENES]
    picked = sorted(ranked, key=lambda s: s.start)
    if not picked:
        return PlanData(mode="full_narration", strategy=strategy)

    count = len(picked)
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        slot_id = f"full-{index + 1}"
        window = (scene.start, round(min(scene.start + _FULL_SCENE_S, scene.end), 3))
        timeline.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(scene.start, 3),
                end=window[1],
                audio="ducked",
                narration_id=slot_id,
            )
        )
        texts.append(
            NarrationText(id=slot_id, slot=_slot_role(index, count, scene.score), window=window)
        )
    return PlanData(
        mode="full_narration", timeline=timeline, narration_texts=texts, strategy=strategy
    )
```

- [x] **Step 7: `modes_p2` 删池（双音色保留）**

`service/dramaclip/engines/narration/modes_p2.py`：两个 `build_*` 都去掉 `project_name` 形参，槽位职责替代模板句，音色仍由编排层决定：

```python
def build_dual_host(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
) -> PlanData:
    """双人对谈（原案 6.10）：A 抛话题、B 推剧情，交替对谈 + 原声压低。"""
    picked = _pick(scenes)
    if not picked:
        return PlanData(mode="dual_host_chat", strategy=strategy)

    count = len(picked)
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        slot_id = f"dual-{index + 1}"
        voice = _VOICE_A if index % 2 == 0 else _VOICE_B
        speaker = "主持人 A" if index % 2 == 0 else "嘉宾 B"
        if index == 0:
            role = f"{speaker} 开场抛话题：用剧名点出这片为什么值得看"
        elif index == count - 1:
            role = f"{speaker} 收尾：放狠话评结局并引导看全集"
        elif index % 2 == 1:
            role = f"{speaker} 接话：情绪反应 + 补一个刚才没说的细节"
        else:
            role = f"{speaker} 抛下一层：把冲突往更狠处推一句"
        window = (scene.start, round(min(scene.start + _SCENE_S, scene.end), 3))
        timeline.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(scene.start, 3),
                end=window[1],
                audio="narration",
                narration_id=slot_id,
            )
        )
        texts.append(NarrationText(id=slot_id, slot=role, voice=voice, window=window))
    return PlanData(
        mode="dual_host_chat", timeline=timeline, narration_texts=texts, strategy=strategy
    )


def build_monologue(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
) -> PlanData:
    """角色内心独白（原案 6.11）：主角第一人称 OS 贯穿，情绪内收。"""
    picked = _pick(scenes)
    if not picked:
        return PlanData(mode="inner_monologue", strategy=strategy)

    count = len(picked)
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        slot_id = f"mono-{index + 1}"
        if index == 0:
            role = "第一人称开场：主角此刻的处境与误判，一句话"
        elif index == count - 1:
            role = "第一人称收尾：态度反转落定 + 一句点击引导"
        elif scene.score >= 85:
            role = "第一人称高潮：这一刻主角想明白了什么，短促、带情绪"
        else:
            role = "第一人称推进：忍让如何一点点失效"
        window = (scene.start, round(min(scene.start + _SCENE_S, scene.end), 3))
        timeline.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(scene.start, 3),
                end=window[1],
                audio="narration",
                narration_id=slot_id,
            )
        )
        texts.append(NarrationText(id=slot_id, slot=role, voice=_VOICE_A, window=window))
    return PlanData(
        mode="inner_monologue", timeline=timeline, narration_texts=texts, strategy=strategy
    )
```

- [x] **Step 8: 改 `pipeline.build_plan` 的调用面**

`service/dramaclip/engines/narration/pipeline.py`：

1. 删除 `intro_text` 整个函数（第 247-255 行）与 `build_plan` 里的 `text = intro_text(...)`。
2. 分支体改为（`dialogue_narration` 分支 Task 5 才删，此处不动）：

```python
    if mode == "intro_narration":
        return modes.build_intro(episode_id, conflict_scores, strategy)
    if mode == "cross_narration":
        return modes_w5.build_cross(episode_id, conflict_scores, strategy)
    if mode == "ultra_short_hook":
        return modes_w5.build_ultra_short(episode_id, conflict_scores, strategy)
    if mode == "full_narration":
        return modes_w8.build_full(episode_id, conflict_scores, strategy)
    if mode == "subtitle_flow":
        return modes_w9.build_subtitle_flow(
            episode_id, conflict_scores, asr_segments, strategy
        )
    if mode == "dual_host_chat":
        return modes_p2.build_dual_host(episode_id, conflict_scores, strategy)
    if mode == "inner_monologue":
        return modes_p2.build_monologue(episode_id, conflict_scores, strategy)
```

3. 模块 docstring 第 3 行改为：
   `编排层只产出画面结构与旁白槽位；文案由 narration.copywriter 生成，TTS 由本模块回填。`

- [x] **Step 9: 更新既有单测的调用签名与断言**

四个测试文件里所有 `build_*` 调用去掉被删形参，并把断言文案的语句改为断言槽位：

- `test_modes.py::test_intro_marks_first_segment_as_narration` → `build_intro("ep1", _scenes(), _STRATEGY)`，追加
  `assert plan.narration_texts[0].id == "intro-1" and plan.narration_texts[0].window`。
- `test_modes_w5.py::test_ultra_short_structure` → `build_ultra_short("ep1", _scenes(), _STRATEGY)`；把
  `plan.narration_texts[0].text.startswith("透视眼")` 与 `"全集" in plan.narration_texts[1].text` 两行换成
  `assert [t.id for t in plan.narration_texts] == ["hook-1", "cta-1"] and all(not t.text for t in plan.narration_texts)`。
- `test_modes_w8.py` → 删除 `narration_texts_for` 的 import 与其测试函数；`build_full(...)` 去掉 `"透视眼"` / `None` 两个实参；新增
  `assert [s.narration_id for s in plan.timeline] == [t.id for t in plan.narration_texts]`。
- `test_modes_p2.py` → `build_dual_host` / `build_monologue` 去掉 `"剧名"` 实参；文案断言改断言 `voice` 交替与 `slot` 非空。

- [x] **Step 10: 跑测试**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration -q`
Expected: PASS（`test_ducked_narration.py` 若因 `build_full` 签名报错，同法去掉多余实参）。

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api -q`
Expected: 此时 `tests/api/test_narration_audio_chain.py` 会有失败——它直接 `build_full` 后合成，而文案已空。
这是 Task 6 要重写的对象，本任务先给它一个测试替身（不碰生产代码）：在该文件 `_full_plan` 里补一行——

```python
    plan = build_full(episode_id, _scenes(), StrategySpec(min_duration_s=10))
    # 文案槽位由编剧层填充（Task 6 前先用替身模拟其产出）
    plan = plan.model_copy(update={
        "narration_texts": [
            t.model_copy(update={"text": f"第 {i} 段解说文案"})
            for i, t in enumerate(plan.narration_texts)
        ]
    })
    return pipeline.synthesize_narration_texts(plan, {"tts.engine": "edge"}, tts_dir)
```

**同一个替身还要打第二处**（计划原稿漏了）：`tests/engines/narration/test_ducked_narration.py:153`
的 `test_full_narration_plan_maps_every_segment_to_own_text` 也走 `build_full` + 直接合成，
空文案会让 `subtitle_text` 变成 `""` 而断言失败。两处的标记注释必须逐字一致，Task 6 靠它检索。

重跑 `tests/api/test_narration_audio_chain.py` 与 `tests/engines/narration` 至 PASS。

- [x] **Step 11: 提交**

```bash
git add service/dramaclip/engines/narration/models.py service/dramaclip/engines/narration/modes/__init__.py service/dramaclip/engines/narration/modes_w5.py service/dramaclip/engines/narration/modes_w8.py service/dramaclip/engines/narration/modes_p2.py service/dramaclip/engines/narration/pipeline.py service/tests/engines/narration service/tests/api/test_narration_audio_chain.py
git commit -m "refactor(narration): 编排层退成槽位，六个模板文案池删除"
```

### Task 2 落地后的实测修正

- **Step 5 的 `build_ultra_short` 代码块无法通过 `ast.parse`**：cta 槽位串 `"...指向"结局更狠"并引导点击..."` 把 ASCII 双引号嵌在了双引号串里（6 个 ASCII 引号）。实施改用中文引号 `「结局更狠」`——与本仓其余文案一致，也是 `modes_p2.py:3`/`api/jobs.py:30`/`export.py:169` 的既有约定。**照抄本块的人会在第一个字符就撞语法错**。
- `_ = intro_first` 确认是纯 no-op（`intro_first` 在函数内另有两处真实使用），删该行、留形参。
- `modes_w8` 的模块 docstring 原写「模板降级，LLM 精修后替换」，删 `narration_texts_for` 后该句为假，一并改口。
- 被删的 `test_modes_w8::narration_texts_for` 用例覆盖着一条真实不变量（`score>=85` 的**高潮**分支优先于位置性的**推进**分支），已移植为 `test_full_slot_roles_follow_narrative_position`。**注意位置算绪**：`build_full` 先按分数取 top-8 再按时间排序，所以"第 3 个场景"不等于"第 3 个槽位"——该用例首版断 index 2 即红（那格确实是高潮），正确值是 index 3。
- `copywriter.py` 的 `_LOGGER`（本计划 Step 4 代码块自带）无任何使用者，与 `import logging` 一并删除。失败路径已抛完整信息、日志归 api 层，不留占位代码。
- `test_ducked_narration.py::_plan` 与 `test_backfilled_plan_still_round_trips_through_json` 补了 `window` 的落库往返断言（`model_dump_json → model_validate_json` 才是 `repos/plans.py` 的真实路径；只做 python-mode `model_dump` 证不出什么）。

---

## Task 3: 语言层——`copywriter.py` 一次调用填满全部槽位

**Files:**
- Create: `service/dramaclip/engines/narration/copywriter.py`
- Modify: `service/dramaclip/engines/narration/scriptwriter.py:25-54`（`_FUNDAMENTALS`→`FUNDAMENTALS`、`_dump_trace`→`dump_trace`）
- Test: `service/tests/engines/narration/test_copywriter.py`

- [x] **Step 1: 写失败测试**

`service/tests/engines/narration/test_copywriter.py`：

```python
"""narration.copywriter：槽位 → LLM → 文案。降级禁止，故所有失败路径都必须是异常。"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import copywriter
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.semantic.llm_client import LlmUnavailable
from dramaclip.engines.semantic.models import ConflictScore

_SETTINGS = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
    "_project_name": "透视眼",
    "_genre": "复仇",
    "_style_directives": "强节奏，多用短句砸爽点",
}

_SCENES = [
    ConflictScore(scene_index=i, start=i * 12.0, end=i * 12.0 + 10.0, score=s)
    for i, s in enumerate([60, 85, 45, 90])
]

_SEGMENTS = [
    AsrSegment(start=i * 12.0 + 1, end=i * 12.0 + 5, text=f"第 {i} 幕的原话")
    for i in range(4)
]


class FakeLlm:
    """按队列应答 chat_json，记录每次 user prompt 供断言。"""

    calls: list[str] = []
    queue: list[Any] = []

    def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    def chat_json(self, _system: str, user: str) -> Any:
        FakeLlm.calls.append(user)
        item = FakeLlm.queue.pop(0) if len(FakeLlm.queue) > 1 else FakeLlm.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def _plan():
    return build_full("ep1", _SCENES, StrategySpec(min_duration_s=10))


def _lines() -> dict[str, Any]:
    return {
        "lines": [
            {"id": f"full-{i + 1}", "text": f"第 {i + 1} 条解说"}
            for i in range(len(_SCENES))
        ]
    }


@pytest.fixture()
def llm(monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeLlm.calls = []
    FakeLlm.queue = []
    monkeypatch.setattr(copywriter, "LlmClient", FakeLlm)
    return FakeLlm


def test_fills_every_slot_and_flips_planner(llm: Any) -> None:
    llm.queue = [_lines()]
    plan = copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)
    assert plan.planner == "llm_script"
    assert [t.text for t in plan.narration_texts] == [
        "第 1 条解说", "第 2 条解说", "第 3 条解说", "第 4 条解说"
    ]


def test_prompt_carries_slot_window_and_transcript(llm: Any) -> None:
    llm.queue = [_lines()]
    copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)
    prompt = llm.calls[0]
    assert "透视眼" in prompt and "复仇" in prompt
    assert "强节奏" in prompt, "口味层指令未注入"
    assert "[full-2]" in prompt and "高潮" in prompt, "槽位职责未进 prompt"
    assert "第 1 幕的原话" in prompt, "素材台词未进 prompt"


def test_missing_slot_raises(llm: Any) -> None:
    llm.queue = [{"lines": [{"id": "full-1", "text": "只写了一条"}]}]
    with pytest.raises(ValueError, match="漏了 3 个槽位"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)


def test_retries_once_then_raises(llm: Any) -> None:
    llm.queue = [LlmUnavailable("网关 502"), {"lines": []}]
    with pytest.raises(ValueError, match="编剧"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)
    assert len(llm.calls) == 2, "应重试一次"


def test_unconfigured_llm_raises_before_prompt(llm: Any) -> None:
    settings = dict(_SETTINGS)
    settings["llm.model"] = ""
    with pytest.raises(LlmUnavailable, match="文案必须由编剧模型产出"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, settings)
    assert llm.calls == []


def test_oversize_line_rejected(llm: Any) -> None:
    """超出 60 字 ×1.2 容忍即判没答：重试一次仍超长就抛，不得把长句塞进成片。"""
    over = "长" * 80
    llm.queue = [
        {"lines": [{"id": f"full-{i + 1}", "text": over} for i in range(len(_SCENES))]}
    ]
    with pytest.raises(ValueError, match="未产出合格文案"):
        copywriter.write_plan_copy(_plan(), _SEGMENTS, _SETTINGS)
    assert len(llm.calls) == 2, "超长应触发一次重问"
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_copywriter.py -q`
Expected: `ModuleNotFoundError: No module named 'dramaclip.engines.narration.copywriter'`

- [x] **Step 3: 把编剧基本功转成可复用常量**

`service/dramaclip/engines/narration/scriptwriter.py`：`_FUNDAMENTALS` → `FUNDAMENTALS`、`_dump_trace` → `dump_trace`（含各自唯一引用点：`_SYSTEM_PROMPT` 末尾的 `+ _FUNDAMENTALS`、`write_script_episodes` 里的 `_dump_trace(...)`）。改完执行
`grep -rn "_FUNDAMENTALS\|_dump_trace" service/ --include=*.py` 确认无残留。

- [x] **Step 4: 写 `copywriter.py`**

```python
"""逐槽文案编剧：编排器给出"在哪段画面、以什么职责说话"，本模块让模型把话说出来。

降级禁止（规格 §3.3.1）：LLM 未配置、槽位漏答、答非所问、句子超长，一律抛出，
不再有模板池。失败粒度是单条方案——api 层逐模式捕获，其余模式继续出片。

单集槽位模式（intro/cross/ultra_short/full/dual_host/inner_monologue）共用本模块；
跨集剧本驱动（dialogue_narration）走 scriptwriter，两条链共享 FUNDAMENTALS。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import scriptwriter
from dramaclip.engines.narration.models import NarrationText, PlanData
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

_LOGGER = logging.getLogger(__name__)

COPY_LLM_TIMEOUT_S = 240.0  # 与编剧同量级：多槽位成稿实测可达 100s+
_MAX_LINE_CHARS = 60
_OVERSIZE_TOLERANCE = 1.2  # 容忍 20% 溢出，再长即判不合格重问
_ATTEMPTS = 2

_SYSTEM_PROMPT = (
    "你是短剧推广解说编剧。下面给出若干旁白槽位，每个槽位标注了它在成片里的位置、"
    "承担的职责、覆盖的画面区间，以及该区间内的原片台词。为每个槽位各写一条解说文案。\n"
    '只输出 JSON：{"lines": [{"id": "槽位id", "text": "解说文案"}]}，不要其他文字。\n'
    f"硬性要求：lines 必须覆盖全部槽位 id（数量与 id 一字不差）；每条不超过 {_MAX_LINE_CHARS} 字；"
    "按给定顺序书写，相邻两条要能连读成一条故事线；"
    "情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件。\n"
    + scriptwriter.FUNDAMENTALS
)


def _clock(seconds: float) -> str:
    minutes, secs = divmod(max(int(seconds), 0), 60)
    return f"{minutes:02d}:{secs:02d}"


def _slot_block(
    texts: list[NarrationText],
    asr_segments: list[AsrSegment],
) -> str:
    """每个槽位一段：职责 + 画面区间 + 区间内台词。台词为编剧唯一的事实来源。"""
    lines: list[str] = []
    for text in texts:
        lines.append(f"[{text.id}] 职责：{text.slot}")
        if text.window is not None:
            start, end = text.window
            lines.append(f"  画面区间：{start:.1f}-{end:.1f}s")
            inside = [
                seg for seg in asr_segments if seg.start < end and seg.end > start
            ]
        else:
            inside = []
        if inside:
            lines.append("  区间内台词：")
            lines.extend(
                f"    {_clock(seg.start)}-{_clock(seg.end)} {seg.text.strip()}"
                for seg in inside
            )
        else:
            lines.append("    （该区间无台词转写：只按职责与前后槽位写，不得编造具体情节）")
    return "\n".join(lines)


def _sanitize(raw: Any, texts: list[NarrationText]) -> dict[str, str]:
    """按 id 取用，绝不按位置推断；漏答、空答、超长都算没答，交由调用方重试或抛。"""
    lines = raw.get("lines") if isinstance(raw, dict) else None
    if not isinstance(lines, list):
        raise ValueError("编剧未返回 lines 数组")
    wanted = {text.id for text in texts}
    limit = int(_MAX_LINE_CHARS * _OVERSIZE_TOLERANCE)
    got: dict[str, str] = {}
    for item in lines:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id", "")).strip()
        value = str(item.get("text", "")).strip()
        if key not in wanted or value == "":
            continue
        if len(value) > limit:
            raise ValueError(f"槽位 {key} 文案 {len(value)} 字，超过上限 {limit} 字")
        got[key] = value
    missing = [text.id for text in texts if text.id not in got]
    if missing:
        raise ValueError(f"编剧漏了 {len(missing)} 个槽位：{', '.join(missing)}")
    return got


def write_plan_copy(
    plan: PlanData,
    asr_segments: list[AsrSegment],
    settings: dict[str, str],
    *,
    mode_label: str = "",
    trace_dir: Path | None = None,
) -> PlanData:
    """填满 plan 的全部旁白槽位并置 planner=llm_script；任何不合格都抛异常。"""
    if not plan.narration_texts:
        return plan
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            "LLM 未配置：解说文案必须由编剧模型产出（已取消模板兜底），请在「引擎」页配置文本模型"
        )
    project_name = str(settings.get("_project_name") or "").strip()
    if not project_name:
        raise ValueError("缺少项目名：编剧需要剧名作为称谓")
    genre = str(settings.get("_genre") or "").strip()
    directives = str(settings.get("_style_directives") or "").strip()
    user_prompt = (
        f"项目：{project_name}"
        + (f"（题材：{genre}）" if genre else "")
        + (f"\n模式：{mode_label}" if mode_label else "")
        + f"\n文案槽位：\n{_slot_block(plan.narration_texts, asr_segments)}"
        + (f"\n\n解说风格要求：{directives}" if directives else "")
    )
    llm = LlmClient(config, timeout_s=COPY_LLM_TIMEOUT_S)
    attempts: list[dict[str, Any]] = []
    filled: dict[str, str] | None = None
    for _ in range(_ATTEMPTS):
        try:
            raw = llm.chat_json(_SYSTEM_PROMPT, user_prompt)
            filled = _sanitize(raw, plan.narration_texts)
        except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append({"raw": raw, "accepted": True})
        break
    if trace_dir is not None:
        stamp = time.strftime("%m%d_%H%M%S")
        scriptwriter.dump_trace(
            Path(trace_dir) / f"llm_copy_{plan.mode}_{stamp}.json",
            {"system": _SYSTEM_PROMPT, "user": user_prompt, "attempts": attempts},
        )
    if filled is None:
        detail = "；".join(str(item["error"]) for item in attempts)
        raise ValueError(f"编剧未产出合格文案（{'，'.join(t.id for t in plan.narration_texts)}）：{detail}")
    return plan.model_copy(update={
        "narration_texts": [
            text.model_copy(update={"text": filled[text.id]}) for text in plan.narration_texts
        ],
        "planner": "llm_script",
    })
```

- [x] **Step 5: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_copywriter.py -q`
Expected: PASS（6 项）。若 `_slot_block` 的台词断言失败，检查 `AsrSegment` 是否真有 `start/end/text` 三字段（`engines/analysis/models.py`）。

- [x] **Step 6: 变异检查（防止断言空转）**

依次手工破坏以下三项，每项跑测试必须变红，改回后绿：
1. `_sanitize` 的 `missing` 检查改成 `if False:` → `test_missing_slot_raises` 必须红。
2. `_sanitize` 的超长 `raise` 删掉 → `test_oversize_line_rejected` 必须红。
3. `write_plan_copy` 的 `planner` 改成 `"rule"` → `test_fills_every_slot_and_flips_planner` 必须红。

Run（每轮）: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_copywriter.py -q`

- [x] **Step 7: 提交**

```bash
git add service/dramaclip/engines/narration/copywriter.py service/dramaclip/engines/narration/scriptwriter.py service/tests/engines/narration/test_copywriter.py
git commit -m "feat(narration): copywriter 逐槽编剧，模板兜底就此没有去处"
```

### Task 3 落地后的实测修正

`_sanitize` 有**四条**拒绝分支：(a) 未知槽位 id、(b) 空答复、(c) 超长、(d) 漏槽。
**本计划原稿给的六条用例只覆盖了 (c)(d)**——把 `key not in wanted` 或 `value == ""` 删掉，全套测试照绿。
已补 `test_unknown_ids_never_count_as_answers` 与 `test_empty_answer_counts_as_no_answer` 两条。

补用例时踩到一个值得记下的事实：**普通的"全部 id 都是垃圾"构造并不变异敏感**——`missing` 是拿我们自己的 id 去查表算的，
未知 id 无论 filter 在不在都填不上槽位，删掉 filter 分支测试仍绿。真正能观察到该分支的唯一形态是
**让某条垃圾 id 的行同时超长**：filter 在时它被丢弃、报错点名我们的槽位；filter 没了它就去抢报错、
把失败原因换成一句关于我们从未请求过的 id 的长度抱怨。

**规矩**：新增拒绝分支的用例必须当场做"删掉这行分支看它红不红"的验证，否则它只是把 happy path 又跑了一遍。
另：`build_ultra_short` 的引号问题与 `_LOGGER` 之死见 Task 2 的实测修正节。

---

## Task 4: 装配层——任务级注入风格与跨集输入，清死码

风格选题从"每模式一次"提到"每任务一次"（一次 produce 少 6 次 LLM 往返），跨集转写同样只取一次。顺手拔掉四处早就没人走的路径。

**Files:**
- Modify: `service/dramaclip/api/narration.py`
- Modify: `service/dramaclip/engines/narration/script_driver.py`
- Modify: `service/dramaclip/engines/narration/pipeline.py:36-46`
- Test: `service/tests/engines/narration/test_script_driver.py`、`service/tests/api/test_produce.py`

- [ ] **Step 1: 写失败测试——每任务只选题一次**

追加到 `service/tests/api/test_produce.py`（文件顶部需补 `import pytest`；`Harness`、`_seed_project_with_analysis`、`narration_api` 均已在该文件内）：

```python
def test_style_selection_runs_once_per_job(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """produce 一次跑多个模式，口味层选题只该付一次 LLM 往返。"""
    from dramaclip.engines.narration import script_driver

    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings["narration.style_id"] = "auto"

    calls: list[int] = []
    monkeypatch.setattr(
        script_driver,
        "resolve_run_style",
        lambda *_a, **_k: calls.append(1) or {"style_id": "shuanggan", "directives": "砸爽点"},
    )
    # 编排本体与本题无关：桩掉它，免得为一个计数等七次真实 LLM 成稿
    monkeypatch.setattr(narration_api, "_generate_one", lambda *_a, **_k: None)

    produce = harness.rpc(
        "narration.produce",
        {"project_id": project_id,
         "modes": ["intro_narration", "cross_narration", "full_narration"]},
    )
    harness.wait_job(str(produce["job_id"]))
    assert len(calls) == 1, f"选题被调 {len(calls)} 次，应为每任务一次"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_produce.py -q -k style_selection`
Expected: FAIL —— `AttributeError: <module 'dramaclip.engines.narration.script_driver'> has no attribute 'resolve_run_style'`

- [ ] **Step 3: `script_driver.resolve_run_style`**

`service/dramaclip/engines/narration/script_driver.py`：新增函数（放在 `script_dialogue_plan` 之前），并把 `script_dialogue_plan` 内的选题块整体删除：

```python
def resolve_run_style(
    settings: dict[str, str],
    episode_inputs: list[dict[str, Any]],
    *,
    log: LogFn,
) -> dict[str, Any]:
    """口味层解析，每个任务只跑一次（原状是每模式一次，produce 白付 6 次 LLM 往返）。

    auto + 已配置 LLM 才让模型选题；未配置时静默走题材映射——真正的失败留给
    文案层报（那里才是非有 LLM 不可的地方，报两次只会混淆原因）。
    """
    preferred = settings.get("narration.style_id")
    genre = settings.get("_genre")
    style_id = styles.resolve_style_id(preferred, genre)
    reason = ""
    if (
        (preferred in (styles.AUTO_STYLE_ID, None, ""))
        and episode_inputs
        and LlmConfig.from_settings(settings).configured
    ):
        selector = LlmClient(LlmConfig.from_settings(settings), timeout_s=_SELECT_TIMEOUT_S)
        selection = styles.select_style_with_reason(selector, _excerpt(episode_inputs))
        if selection is None:
            log("warn", "AI 风格选题失败，按题材静态映射兜底")
        else:
            style_id, reason = selection
    style = styles.get_style(style_id)
    log("info", _style_log_line(preferred, style, genre, reason))
    return style
```

`script_dialogue_plan` 内第 48-64 行（`genre = settings.get("_genre")` 到 `style = styles.get_style(style_id)`）整块替换为一行：

```python
    style_directives = str(settings.get("_style_directives") or "")
```

同函数内 `write_script_episodes(..., style_directives=str(style.get("directives", "")), ...)` 改为
`style_directives=style_directives`；紧随其后的 `log("info", _style_log_line(...))` 一行删除（风格日志已随选题进 `resolve_run_style`，每任务打一次即可）。
`_style_log_line` 与 `_excerpt`、`_SELECT_TIMEOUT_S` 都仍被 `resolve_run_style` 使用，留在本文件；`_SELECT_LINES_PER_EPISODE` 全仓库无引用，删除。

- [ ] **Step 4: `api/narration.py` 任务级注入**

`service/dramaclip/api/narration.py`：

1. import 增 `from dramaclip.engines.narration import script_driver`（替换原有 `from ... import script_dialogue_plan`）。
2. `_NO_TTS_MODES` 改为 `frozenset({"raw_clip", "subtitle_flow"})`，其注释改为：
   `# 与 TTS 合成并行的两组：剧情解说已由 LLM 剧本驱动，每段都要配音，不再属"无 TTS"。`
3. `_mode_label` 函数删除，`_MODE_LABELS` 在 `pipeline.py` 改为公开常量 `MODE_LABELS`（同批改 `_generate_one` 与 `_run_*` 里所有 `_mode_label(mode)` 为 `pipeline.MODE_LABELS.get(mode, mode)`）。
4. 新增注入助手：

```python
def _inject_run_settings(
    context: AppContext,
    settings: dict[str, str],
    episodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """任务级一次性注入：项目名、题材、跨集转写、口味层风格。返回跨集输入。"""
    project_id = str(episodes[0]["project_id"])
    project = projects_repo.get(context.conn, project_id)
    if project is None:
        raise ValueError(f"项目不存在: {project_id}")
    settings["_project_name"] = str(project["name"])
    record = analysis_repo.get(context.conn, str(episodes[0]["id"]))
    if record is not None and record["genre"]:
        settings["_genre"] = str(record["genre"])
    episode_inputs = _collect_episode_inputs(context, episodes)
    if episode_inputs:
        settings["_style_directives"] = str(
            script_driver.resolve_run_style(
                settings, episode_inputs, log=context.notifier.log
            ).get("directives", "")
        )
    return episode_inputs
```

5. `_run_generation_parallel` 与 `_run_produce` 中，原先各自手写的"取 project / 取 genre"三行统一换成：

```python
    settings = dict(context.settings)
    episode_inputs = _inject_run_settings(context, settings, episodes)
```

并把循环里的 `_generate_one(context, mode, episodes, dict(settings))` 改为
`_generate_one(context, mode, episodes, episode_inputs, dict(settings))`。
6. 删除 `_run_generation`（第 153-186 行，全仓库无引用，已确认死码）。

- [ ] **Step 5: `_generate_one` 收形参，删重复取数**

```python
def _generate_one(
    context: AppContext,
    mode: str,
    episodes: list[dict[str, Any]],
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
) -> None:
    """生成单模式编排：剧情解说走跨集剧本，其余模式走规则编排 + 逐槽文案。"""
    project_id = str(episodes[0]["project_id"])
    plan: PlanData | None = None
    used_ids = [str(episodes[0]["id"])]

    if mode == "dialogue_narration":
        if not episode_inputs:
            raise ValueError("没有带转写的已完成集，无法生成解说剧本")
        context.notifier.log(
            "info",
            f"跨集输入：{len(episode_inputs)} 集 → "
            f"每集约 {scriptwriter.transcript_sampling_quota(len(episode_inputs))} 段摘录",
        )
        plan, used_ids = script_driver.script_dialogue_plan(
            episode_inputs,
            settings,
            log=context.notifier.log,
            trace_dir=context.data_dir / "logs" / "llm",
        )

    if plan is None:
        episode = episodes[0]
        episode_id = str(episode["id"])
        used_ids = [episode_id]
        record = analysis_repo.get(context.conn, episode_id)
        if record is None:
            raise ValueError("分析记录缺失")
        conflicts = _parse_conflicts(record["conflict_scores"])
        highlights = _parse_highlights(record["highlights"])
        asr_segments = narration_pipeline.parse_asr_segments(record["asr_segments"])
        audio = narration_pipeline.parse_audio_features(record["audio_features"])
        plan = narration_pipeline.build_plan(
            mode, episode_id, conflicts, highlights, asr_segments, audio, settings
        )
        if plan.narration_texts:
            plan = copywriter.write_plan_copy(
                plan,
                asr_segments,
                settings,
                mode_label=narration_pipeline.MODE_LABELS.get(mode, mode),
                trace_dir=context.data_dir / "logs" / "llm",
            )

    if plan.narration_texts:
        tts_dir = context.work_dir / "tts"
        models_dir = context.data_dir / "models"
        plan = narration_pipeline.synthesize_narration_texts(plan, settings, tts_dir, models_dir)
    plans_repo.create(context.conn, project_id, mode, used_ids, plan.model_dump())
```

（import 增 `from dramaclip.engines.narration import copywriter`。`if plan is None` 本任务仍保留——Task 5 让剧本链改抛错后，它天然只剩"非 dialogue 模式"一条路。）

- [ ] **Step 6: 跑测试**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_produce.py tests/engines/narration/test_script_driver.py tests/api -q`
Expected: `test_style_selection_runs_once_per_job` PASS。
`test_script_driver.py` 里两条选题用例（`test_manual_style_skips_selection_call`、`test_selection_failure_falls_back_to_genre`）会失败——选题已不在 `script_dialogue_plan` 内。把它们移到 `resolve_run_style` 上，并在 `script_dialogue_plan` 的用例里以 `settings["_style_directives"]` 直接给定风格：

```python
def test_resolve_run_style_falls_back_to_genre_mapping(monkeypatch) -> None:
    FakeLlmClient.queue = [RuntimeError("选题服务不可用")]
    monkeypatch.setattr(script_driver, "LlmClient", FakeLlmClient)
    logs: list[tuple[str, str]] = []
    style = script_driver.resolve_run_style(
        dict(_SETTINGS), _EPISODES, log=lambda lv, msg: logs.append((lv, msg))
    )
    assert style["style_id"] == "shuanggan", "_SETTINGS 的 _genre=逆袭 应映射爽感"
    assert any("题材静态映射" in msg for _lv, msg in logs)


def test_resolve_run_style_manual_skips_llm(monkeypatch) -> None:
    FakeLlmClient.queue = [{"style_id": "sweet", "reason": "x"}]
    monkeypatch.setattr(script_driver, "LlmClient", FakeLlmClient)
    settings = dict(_SETTINGS)
    settings["narration.style_id"] = "suspense"
    style = script_driver.resolve_run_style(settings, _EPISODES, log=lambda *_a: None)
    assert style["style_id"] == "suspense"
    assert FakeLlmClient.calls == [], "手动指定风格不该发选题请求"
```

- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/api/narration.py service/dramaclip/engines/narration/script_driver.py service/dramaclip/engines/narration/pipeline.py service/tests/api/test_produce.py service/tests/engines/narration/test_script_driver.py
git commit -m "refactor(narration): 口味层与跨集输入上提到任务级，删除三处死路"
```

### Task 4 落地后的实测修正

- 九模式在仓里有**三面镜子**：`narration_api.SUPPORTED_MODES`、`pipeline.MODE_LABELS`、`desktop/src/components/modeMeta.ts` 的 `MODE_INFO`。已加 `test_every_supported_mode_has_a_chinese_label` 钉住前两面（漏标签会让队列页露出英文模式名，本任务实测踩过）；第三面是 TS，service 侧的 pytest 够不着——**P-3 已知接受项**，随全站重排一并收口。

---

## Task 5: 禁止降级（一）——编剧链失败即抛，删规则编排退路

**Files:**
- Modify: `service/dramaclip/engines/narration/scriptwriter.py:206-273`
- Modify: `service/dramaclip/engines/narration/script_driver.py:28-97`
- Modify: `service/dramaclip/engines/narration/pipeline.py:101-160`（删 `build_from_script_dialogue`）、`:75-77`（删 dialogue 规则分支）
- Modify: `service/dramaclip/api/narration.py`（`_generate_one` 去掉 `if plan is None` 对 dialogue 的兜底）
- Delete: `service/dramaclip/engines/narration/dialogue_selector.py` → 改名 `line_scoring.py`（只剩打分函数）
- Test: `service/tests/engines/narration/test_scriptwriter.py`、`test_script_driver.py`、`test_dialogue.py`→`test_line_scoring.py`

- [ ] **Step 1: 写失败测试——未配置与非法输出都必须抛**

追加到 `service/tests/engines/narration/test_script_driver.py`（文件顶部补
`from dramaclip.engines.semantic.llm_client import LlmUnavailable`；本任务会删掉 `script_dialogue_plan` 的 `log` 形参，故新用例一律不传）：

```python
def test_unconfigured_llm_raises_not_none() -> None:
    """降级禁止：LLM 未配置时报错并说明去配什么，绝不悄悄出一版规则编排。"""
    settings = dict(_SETTINGS)
    settings["llm.base_url"] = ""
    with pytest.raises(LlmUnavailable, match="引擎"):
        script_driver.script_dialogue_plan(_EPISODES, settings)


def test_no_script_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script_driver, "LlmClient", FakeLlmClient)
    FakeLlmClient.queue = [{"hook": "", "segments": []}]
    with pytest.raises(ValueError, match="剧本"):
        script_driver.script_dialogue_plan(_EPISODES, dict(_SETTINGS))
```

`service/tests/engines/narration/test_scriptwriter.py` 里四条「降级返回 None」的用例就是本任务要改的行为——整块替换（`_run` 返回类型改 `Script`，`assert ... is None` 全改 `pytest.raises`）：

```python
def _run(llm: FakeLLM) -> Script:
    return write_script_episodes(
        llm, _EPISODES, target_min_s=30, target_max_s=300, project_name="测试剧"
    )


def test_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="未产出合法剧本"):
        _run(FakeLLM([ValueError("非法 JSON")]))


def test_too_few_segments_raises() -> None:
    """清洗后不足 `_MIN_SEGMENTS` 段：越界集号被丢光，等同没写。"""
    payload = dict(
        _VALID_PAYLOAD,
        segments=[{"episode": 9, "start": 1.0, "end": 10.0, "text": "集号不存在"}],
    )
    with pytest.raises(ValueError, match="未产出合法剧本"):
        _run(FakeLLM([payload]))


def test_retries_once_before_raising() -> None:
    llm = FakeLLM([ValueError("第一次失败"), dict(_VALID_PAYLOAD)])
    _run(llm)
    assert llm.calls == 2, "第一次失败必须重问一次"


@pytest.mark.parametrize(
    "payload",
    [
        {"hook": "", "segments": _VALID_PAYLOAD["segments"]},
        {"hook": "x", "segments": [{"episode": 1, "start": "abc", "end": 2, "text": "t"}] * 3},
        {"segments": [{"episode": 1, "start": 1.0, "end": 2.0, "text": "无钩子"}]},
    ],
)
def test_malformed_payloads_raise(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="未产出合法剧本"):
        _run(FakeLLM([payload]))


def test_no_transcript_raises() -> None:
    """所有集都没有转写：无米下锅要直说，不能返回 None 让上层以为是自己降级了。"""
    empty = [{"number": 1, "duration": 40.0, "segments": []}]
    with pytest.raises(ValueError, match="无米下锅"):
        write_script_episodes(
            FakeLLM([dict(_VALID_PAYLOAD)]), empty,
            target_min_s=30, target_max_s=300, project_name="测试剧",
        )
```

文件 docstring 的「重试降级」同步改为「重试与失败即抛」。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/narration/test_script_driver.py tests/engines/narration/test_scriptwriter.py -q`
Expected: FAIL —— 返回 `None` 而非抛（`TypeError: argument of type 'NoneType' is not iterable` / 直接返回 None 不匹配 match）。

- [ ] **Step 3: `write_script_episodes` 改抛错**

`service/dramaclip/engines/narration/scriptwriter.py`：

1. 签名 `-> Script | None` → `-> Script`。
2. 空转写分支：

```python
    transcript_block = _format_transcript_episodes(episode_inputs)
    if not transcript_block:
        raise ValueError("编剧无米下锅：所有集都没有台词转写")
```

3. 收尾（替换现有 `if trace_path is not None: ... return script`）：

```python
    if trace_path is not None:
        dump_trace(trace_path, {"system": _SYSTEM_PROMPT, "user": user_prompt, "attempts": attempts})
    if script is None:
        detail = "；".join(str(item.get("error", "清洗后片段不足")) for item in attempts)
        raise ValueError(
            f"编剧未产出合法剧本（{len(attempts)} 次尝试）：{detail}"
            + (f"；完整往返见 {trace_path}" if trace_path else "")
        )
    return script
```

4. docstring 第 219 行「失败返回 None，调用方降级规则编排」→「失败抛异常；降级被禁止（规格 §3.3.1）」。
5. 模块 docstring 第 4-5 行「LLM 不可用或输出非法时返回 None，调用方降级到规则预算编排」→
   「LLM 不可用或输出非法一律抛异常——降级到模板文案已被 P-1.5 取消（规格 §3.3.1）」。

- [ ] **Step 4: `script_dialogue_plan` 改抛错、去风格内解**

`service/dramaclip/engines/narration/script_driver.py`：

```python
def script_dialogue_plan(
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    *,
    trace_dir: Any = None,
) -> tuple[PlanData, list[str]]:
    """跨集剧本驱动的对话解说。LLM 未配置或剧本不合格一律抛（降级已禁止）。

    口味层由调用方经 resolve_run_style 注入 settings["_style_directives"]，
    本函数不再自行选题——一个任务只该付一次选题成本。
    """
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            "LLM 未配置：剧情解说由编剧模型成稿，请先在「引擎」页配置文本模型"
        )
    strategy = StrategySpec(
        platform="douyin",
        min_duration_s=float(settings.get("strategy.min_duration_s", "30")),
        max_duration_s=float(settings.get("strategy.max_duration_s", "300")),
    )
    llm = LlmClient(config, timeout_s=SCRIPT_LLM_TIMEOUT_S)
    trace_path = None
    if trace_dir is not None:
        trace_dir = Path(trace_dir)
        trace_path = trace_dir / f"llm_script_{time.strftime('%m%d_%H%M%S')}.json"
    script = scriptwriter.write_script_episodes(
        llm,
        episode_inputs,
        target_min_s=strategy.min_duration_s,
        target_max_s=strategy.max_duration_s,
        project_name=str(settings.get("_project_name") or "这部剧"),
        style_directives=str(settings.get("_style_directives") or ""),
        trace_path=trace_path,
    )
    episode_map = {
        int(ep["number"]): (
            str(ep["episode_id"]),
            [AsrSegment.model_validate(seg) for seg in ep["segments"]],
        )
        for ep in episode_inputs
    }
    durations = {int(ep["number"]): float(ep.get("duration") or 0.0) for ep in episode_inputs}
    plan = narration_pipeline.build_from_script_episodes(
        episode_map, durations, script, strategy
    )
    return plan, sorted({seg.episode_id for seg in plan.timeline})
```

**`log` 形参就此从 `script_dialogue_plan` 消失**（函数内已无使用者，`LogFn` 类型仍服务 `resolve_run_style`）。同步改三处调用点：
`api/narration._generate_one` 删 `log=context.notifier.log` 实参；`tests/engines/narration/test_script_driver.py`
与 `test_script_episodes.py` 里所有 `script_dialogue_plan(..., log=...)` 调用删掉该关键字；`_noop_log` 若仅它们在用则一并删除。

- [ ] **Step 5: 删 `build_from_script_dialogue` 与 dialogue 规则分支**

`service/dramaclip/engines/narration/pipeline.py`：
1. 删除 `build_from_script_dialogue`（第 101-160 行，全仓库无引用）。
2. `build_plan` 删除 dialogue 分支，改为在函数末尾的 `raise` 之前不列它；并在 `raise` 文案前加一行显式说明：

```python
    if mode == "dialogue_narration":
        raise ValueError("剧情解说为剧本驱动，不经规则编排（走 script_driver.script_dialogue_plan）")
```

3. 删除文件顶部 `dialogue_selector` 的 import（第 15 行），改为不再引用。

- [ ] **Step 6: `dialogue_selector.py` 瘦身为 `line_scoring.py`**

```bash
cd service && git mv dramaclip/engines/narration/dialogue_selector.py dramaclip/engines/narration/line_scoring.py
git mv tests/engines/narration/test_dialogue.py tests/engines/narration/test_line_scoring.py
```

- 删除 `select_dialogue_lines`、`build_dialogue`、`_has_clear_gap`、`_MIN_LINE_S/_MAX_LINE_S/_GAP_TOLERANCE_S/_SCORE_FLOOR`（仅 `score_line` 及其词表被 `modes_w9` 复用；`_MIN_LINE_S`/`_MAX_LINE_S` 若仍被 `score_line` 的长度加分项引用则保留）。
- 模块 docstring 改为一行职责：`对白质量打分（0-100）：字幕金句流用它挑每段最强一句。`
- 更新引用：`service/dramaclip/engines/narration/modes_w9.py:29` 的函数内 import 改为
  `from dramaclip.engines.narration.line_scoring import score_line`，并把它提到文件顶部常规 import 区（函数内 import 当初只为避开循环依赖，现无环）。
- `test_line_scoring.py` 删除 `select_dialogue_lines`/`build_dialogue` 两组用例，保留 `score_line` 用例。
- 校验无残留：`grep -rn "dialogue_selector" service/ --include=*.py` → 无输出。

- [ ] **Step 7: 跑测试**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines tests/api -q`
Expected: PASS。若 `test_script_episodes.py`/`test_scriptwriter.py` 有用例断言"失败返回 None"，按本任务口径改成 `pytest.raises`——那是本次要改的行为，不是回归。

- [ ] **Step 8: 提交**

```bash
git add service/dramaclip/engines/narration service/dramaclip/api/narration.py service/tests/engines/narration service/tests/api
git commit -m "fix(narration): 编剧链失败改为抛错，删除剧情解说的规则编排退路"
```

---

## Task 6: 禁止降级（二）——配音缺件即方案失败，回填按 id 取用

**Files:**
- Modify: `service/dramaclip/engines/narration/pipeline.py:258-318`
- Test: `service/tests/api/test_narration_audio_chain.py`、`service/tests/engines/narration/test_ducked_narration.py`、新建 `service/tests/api/test_narration_no_downgrade.py`

- [ ] **Step 1: 写失败测试**

新建 `service/tests/api/test_narration_no_downgrade.py`：

```python
"""降级禁止的可执行定义：文案为空、配音失败、段与文案对不上，三种情况都必须炸。

回归动机：这三条路过去全都"悄悄继续"——空文案照样排、合成失败照样回退原声、
旁白段与文案表按位置硬配。门禁测的是成片，这里测的是"坏片为什么没能被拦住"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.narration.models import NarrationText, PlanData, StrategySpec, TimelineSegment
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.semantic.models import ConflictScore

_SCENES = [
    ConflictScore(scene_index=i, start=i * 12.0, end=i * 12.0 + 10.0, score=s)
    for i, s in enumerate([60, 85, 45, 90])
]


class _StubTts:
    def __init__(self, fail_ids: tuple[str, ...] = ()) -> None:
        self.fail_ids = fail_ids

    def synthesize(self, text: str, voice: Any, out_path: Path) -> Path:
        if any(bad in str(out_path) for bad in self.fail_ids):
            raise RuntimeError("云端不可达")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp3")
        return out_path


def _plan_with_copy() -> PlanData:
    plan = build_full("ep1", _SCENES, StrategySpec(min_duration_s=10))
    return plan.model_copy(update={
        "narration_texts": [
            t.model_copy(update={"text": f"第 {i} 段解说文案"})
            for i, t in enumerate(plan.narration_texts)
        ]
    })


def _synth(monkeypatch, plan, engine, duration=1.25) -> PlanData:
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: duration)
    return pipeline.synthesize_narration_texts(plan, {"tts.engine": "edge"}, Path("tts"))


def test_empty_copy_raises_before_tts(monkeypatch) -> None:
    plan = build_full("ep1", _SCENES, StrategySpec(min_duration_s=10))
    with pytest.raises(RuntimeError, match="文案为空"):
        _synth(monkeypatch, plan, _StubTts())


def test_one_failed_segment_fails_whole_plan(monkeypatch, tmp_path: Path) -> None:
    plan = _plan_with_copy()
    with pytest.raises(RuntimeError, match="full-2"):
        _synth(monkeypatch, plan, _StubTts(fail_ids=("full-2",)))


def test_zero_duration_fails(monkeypatch) -> None:
    plan = _plan_with_copy()
    with pytest.raises(RuntimeError, match="时长"):
        _synth(monkeypatch, plan, _StubTts(), duration=0.0)


def test_segment_without_narration_id_fails(monkeypatch) -> None:
    plan = _plan_with_copy()
    broken = plan.model_copy(update={
        "timeline": [s.model_copy(update={"narration_id": None}) for s in plan.timeline]
    })
    with pytest.raises(RuntimeError, match="narration_id"):
        _synth(monkeypatch, broken, _StubTts())


def test_backfill_writes_duration_subtitle_and_id(monkeypatch) -> None:
    plan = _synth(monkeypatch, _plan_with_copy(), _StubTts())
    assert all(s.narration_id for s in plan.timeline)
    assert all(s.subtitle_text for s in plan.timeline)
    assert all(abs((s.end - s.start) - 1.25) < 0.01 for s in plan.timeline)
    assert all(t.audio_path and t.duration == 1.25 for t in plan.narration_texts)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_narration_no_downgrade.py -q`
Expected: 5 条里至少 4 条 FAIL（现状是回退原声、静默继续）。

- [ ] **Step 3: 重写 `synthesize_narration_texts`**

`service/dramaclip/engines/narration/pipeline.py`，整函数替换：

```python
def synthesize_narration_texts(
    plan: PlanData,
    settings: dict[str, str],
    work_dir: Path,
    models_dir: Path | None = None,
) -> PlanData:
    """逐段合成旁白并按 narration_id 回填时长与解说字幕。

    降级禁止（规格 §3.3.1）：任一段没有合格音频，整条方案失败——
    半条旁白的片子不可交付。段↔文案只认 id，绝不按位置推断。
    """
    if not plan.narration_texts:
        return plan
    engine = create_tts(settings.get("tts.engine", "edge"), models_dir)
    default_voice = settings.get("tts.voice", "")
    voiced: dict[str, tuple[str, str, float]] = {}  # id → (audio_path, text, duration)
    for item in plan.narration_texts:
        if not item.text.strip():
            raise RuntimeError(
                f"旁白 {item.id} 文案为空——编剧链未执行，这条方案不该往下走配音"
            )
        try:
            audio_path = engine.synthesize(item.text, item.voice or default_voice, work_dir / f"{item.id}.mp3")
            duration = tts_base.audio_duration_s(audio_path)
        except Exception as exc:
            raise RuntimeError(
                f"旁白 {item.id} 合成失败（引擎={settings.get('tts.engine', 'edge')}）："
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not duration or duration <= 0:
            raise RuntimeError(f"旁白 {item.id} 合成后音频时长无效（{duration}s）")
        voiced[item.id] = (str(audio_path), item.text, float(duration))

    timeline = [segment.model_dump() for segment in plan.timeline]
    for segment in timeline:
        if segment["audio"] not in ("narration", "ducked"):
            continue
        key = segment.get("narration_id")
        if key not in voiced:
            raise RuntimeError(
                f"编排自相矛盾：旁白段 {segment['episode_id']}@{segment['start']} "
                f"的 narration_id={key!r} 在文案表里不存在"
            )
        _audio_path, text, duration = voiced[key]
        segment["end"] = round(segment["start"] + duration, 3)
        segment["subtitle_text"] = text
    updated = [
        item.model_copy(update={"audio_path": voiced[item.id][0], "duration": voiced[item.id][2]})
        for item in plan.narration_texts
    ]
    return PlanData.model_validate(
        {**plan.model_dump(), "narration_texts": updated, "timeline": timeline}
    )
```

（`model_copy` 在此安全：塞进去的是模型实例与标量，不是裸 dict——当年把裸 dict 塞进 `timeline` 的是另一处。校验仍由 `PlanData.model_validate` 兜底。）

- [ ] **Step 4: 给剧本链补 `narration_id`**

`build_from_script_episodes` 与 `build_from_script_dialogue` 已在 Task 5 删掉后者；前者内三处 `narration_span(...)`／`TimelineSegment(...)` 与对应 `texts.append(NarrationText(id=...))` 必须把同一个 id 写进段：

```python
    hook_id = "n0"
    timeline.append(narration_span(first.episode, script.hook, hook_start, narration_id=hook_id))
    texts.append(NarrationText(id=hook_id, text=script.hook, brief="开场钩子：抛出全片最大悬念"))
```

**字段名按本文件「实现定案修正」节：`brief`，不是 `slot`；没有 `window`。** 槽位的画面区间唯一的真相源是它 `narration_id` 指到的那条 `TimelineSegment`——这里不要再算一遍 `hook_start + estimate_duration(...)`，那正是 `window` 被删掉的原因（回填会改写段 `end`，两份答案必然打架）。

`narration_span` 增加形参 `narration_id: str` 并在 `TimelineSegment(...)` 里带上；正文段与 CTA 段同法（正文 id 已是 `f"n{order}"`，CTA 用 `f"n{len(script.segments) + 1}"`，两处保持一致）。

- [ ] **Step 5: 更新既有断言（旧行为写进了测试）**

- `tests/api/test_narration_audio_chain.py`：删掉 Step 10 的替身（`_filled` 那段临时注释）改由真实链路语义：
  把 `_full_plan` 里 `text=f"第 {i} 段解说文案"` 的注释改成「编剧层产出（见 test_narration_no_downgrade 对空文案的守卫）」；
  将 `test_failed_tts_renders_no_mix_branch_and_no_stale_mapping` 整函数替换为：

```python
def test_failed_tts_fails_the_plan(
    monkeypatch: pytest.MonkeyPatch, memory_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """配音失败 = 方案失败：不再有"回退原声继续渲染"这条路。"""
    _stub_tts(monkeypatch, _BrokenTts())
    with pytest.raises(RuntimeError, match="合成失败"):
        _render(monkeypatch, memory_db, tmp_path, _full_plan)
```

- `tests/engines/narration/test_ducked_narration.py` 三处改动：

1. `_plan(roles)` 目前只按位置造文案、段上不写 `narration_id`——回填语义改成按 id 取用后整个文件都会失效。换成写 id 的版本（**旁白段按出现顺序取 n0/n1/…**，这样文件里 `[None, "n0"]`、`"旁白0"`、`["n0", "n1"]` 等既有断言全部照旧成立）：

```python
def _plan(roles: list[str]) -> PlanData:
    """按角色序列造编排：旁白段按出现顺序拿到自己的文案，配对靠 id 不靠位置。"""
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    order = 0
    for index, role in enumerate(roles):
        if role == "original":
            timeline.append(
                TimelineSegment(episode_id="ep1", start=float(index), end=float(index) + 1.0,
                                audio=role)
            )
            continue
        slot = f"n{order}"
        timeline.append(
            TimelineSegment(episode_id="ep1", start=float(index), end=float(index) + 1.0,
                            audio=role, narration_id=slot)
        )
        texts.append(NarrationText(id=slot, text=f"旁白{order}"))
        order += 1
    return PlanData(mode="full_narration", timeline=timeline, narration_texts=texts)
```

2. 两条锁"降级后行为"的用例整体换成抛错断言（`_BrokenTts` 保留复用）：

```python
def test_failed_tts_fails_the_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """合成失败 = 方案失败：不再有"回退原声继续出片"这条路（规格 §3.3.1）。"""
    _broken_tts(monkeypatch)
    with pytest.raises(RuntimeError, match="合成失败"):
        pipeline.synthesize_narration_texts(
            _plan(["narration", "ducked"]), {"tts.engine": "edge"}, tmp_path
        )


def test_zero_duration_fails_the_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """探测到 0 长音频同样不许继续——它和"没合成出来"是同一件事。"""
    _stub_tts(monkeypatch, None)
    with pytest.raises(RuntimeError, match="时长"):
        pipeline.synthesize_narration_texts(
            _plan(["ducked"]), {"tts.engine": "edge"}, tmp_path
        )
```

（`test_stale_id_cleared_when_later_synthesis_fails` 整条删除：它验的是"第二轮回填清掉陈旧映射"，而第一轮失败已经不允许存在。）

3. `test_full_narration_plan_maps_every_segment_to_own_text` 里 `build_full("ep1", scenes, StrategySpec(...), "透视眼")` 去掉 `"透视眼"` 实参（Task 2 已删该形参）。

Run: `cd service && ../.venv/Scripts/python -m pytest tests/api/test_narration_no_downgrade.py tests/api/test_narration_audio_chain.py tests/engines/narration -q`
Expected: PASS

- [ ] **Step 6: 全量单测**

Run: `cd service && ../.venv/Scripts/python -m pytest -q`
Expected: 全绿，但 `tests/api/test_analysis.py` 的隔离污染 flake 是已知既有问题（两种失效模式，由其属主处理）——**不要在本任务里修它、不要给它加 sleep、不要扩大它**。若它红了，单独跑 `pytest tests/api/test_analysis.py -q` 判断是否与本改动相关，无关则记录后继续。

- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/engines/narration/pipeline.py service/tests/api/test_narration_no_downgrade.py service/tests/api/test_narration_audio_chain.py service/tests/engines/narration/test_ducked_narration.py
git commit -m "fix(narration): 配音缺件与空文案改为整条方案失败，段↔文案只认 id"
```

---

## Task 7: 混音不再偷偷改音量（`amix normalize=0`）

**Files:**
- Modify: `service/dramaclip/engines/exporter/encoder.py:51-52,87-95`
- Test: `service/tests/engines/exporter/test_mix.py`（`test_encoder.py` 的 `amix` 断言是子串匹配，本任务无需改动）

- [ ] **Step 1: 写失败测试**

`service/tests/engines/exporter/test_mix.py` 追加（文件已有 `random`、`encoder` 与 `_args(audio, tts)` 助手，直接复用）：

```python
def test_amix_does_not_normalize_inputs() -> None:
    """amix 默认把每路除以输入数（此处各砍 6dB），声明的 0.2/0.12 会变成假数字。"""
    joined = " ".join(_args("narration", "n1.mp3"))
    assert "amix=inputs=2:duration=first:normalize=0" in joined
    assert "volume=0.2," in joined, "narration 段原声须真压到 20%"
    joined_ducked = " ".join(_args("ducked", "n1.mp3"))
    assert "volume=0.12," in joined_ducked and "normalize=0" in joined_ducked
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter/test_mix.py -q`
Expected: FAIL —— `assert 'amix=inputs=2:duration=first:normalize=0' in ...`

- [ ] **Step 3: 改 encoder**

`service/dramaclip/engines/exporter/encoder.py`：

```python
            "[bg][tts]amix=inputs=2:duration=first:normalize=0[a]",
```

并把该分支注释补一句约束来源：

```python
        # normalize=0 必须显式给：ffmpeg 的 amix 默认把每路除以输入数（此处各砍 6dB），
        # 那样上面的 bg_volume 声明值与实际听感差一倍，响度无人负责。最终响度由 Phase C 统一收口。
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter tests/api/test_narration_audio_chain.py -q`
Expected: PASS
Run: `cd service && ../.venv/Scripts/python -m pytest -q`
Expected: PASS（`test_encoder.py:59` 的 `"amix=inputs=2" in joined` 是子串断言，不受影响）

- [ ] **Step 5: 提交**

```bash
git add service/dramaclip/engines/exporter/encoder.py service/tests/engines/exporter/test_mix.py
git commit -m "fix(export): amix 关闭输入归一化，声明的 duck 音量与实际听感对齐"
```

---

## Task 8: Phase C——整片响度归一到目标

**Files:**
- Create: `service/dramaclip/engines/exporter/loudness.py`
- Modify: `service/dramaclip/infra/config.py`（`get_float` + 两个键）
- Modify: `service/dramaclip/engines/exporter/encoder.py`（`export_plan` 尾部）
- Modify: `service/dramaclip/api/export.py`（传目标值）
- Modify: `desktop/src/features/settings/sections.ts`
- Test: `service/tests/engines/exporter/test_loudness.py`

- [ ] **Step 1: 写失败测试（纯命令构建 + 解析）**

`service/tests/engines/exporter/test_loudness.py`：

```python
"""Phase C 响度归一：命令构建、测量解析、复核超差即抛。ffmpeg 在此不真跑。"""

from __future__ import annotations

import pytest

from dramaclip.engines.exporter import loudness

_TARGET = loudness.LoudnessTarget(integrated_lufs=-14.0, true_peak_dbtp=-1.5)

_STDERR = """
[Parsed_loudnorm @ 0x...] Input Integrated: -23.7 LUFS
{
	"input_i" : "-23.72",
	"input_tp" : "-3.15",
	"input_lra" : "8.40",
	"input_thresh" : "-34.10",
	"output_i" : "-14.02",
	"target_thresh" : "-24.50",
	"offset" : "0.50"
}
size=N/A time=00:01:30.00
"""


def test_measure_args_target_and_print_format() -> None:
    args = loudness.measure_args("in.mp4", _TARGET)
    joined = " ".join(args)
    assert "loudnorm=I=-14.0:TP=-1.5:LRA=11.0:print_format=json" in joined
    assert "-f null" in joined and "-map 0:a:0" in joined


def test_parse_measurements() -> None:
    m = loudness.parse_measurements(_STDERR)
    assert (m.integrated_lufs, m.true_peak_dbtp, m.lra) == (-23.72, -3.15, 8.40)
    assert m.threshold == -34.10 and m.target_threshold == -24.50
    assert m.offset_lu == 0.50, "两遍法的补偿量必须回喂，丢掉它等于二次偏移"


def test_parse_missing_block_raises() -> None:
    with pytest.raises(RuntimeError, match="未输出"):
        loudness.parse_measurements("nothing here")


def test_silent_audio_raises() -> None:
    with pytest.raises(RuntimeError, match="无声"):
        loudness.parse_measurements('{"input_i": "-inf", "input_tp": "-inf", "input_lra": "0.0", "input_thresh": "-inf", "target_thresh": "-inf"}')


def test_normalize_args_copies_video_and_resamples() -> None:
    m = loudness.parse_measurements(_STDERR)
    args = loudness.normalize_args("in.mp4", "out.mp4", _TARGET, m)
    joined = " ".join(args)
    assert "-c:v copy" in args, "视频流必须复制：重编码会让 Phase A 的消重参数白做"
    assert "measured_I=-23.72" in joined and "measured_TP=-3.15" in joined
    assert "offset=0.5" in joined, "第一遍自报的 offset 必须回喂"
    assert "linear=true" in joined
    assert "-ar" in args and "48000" in args, "loudnorm 内部 192k，必须落回 48k"
    assert "-map_metadata" in args and "-1" in args
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python -m pytest tests/engines/exporter/test_loudness.py -q`
Expected: `ModuleNotFoundError: No module named 'dramaclip.engines.exporter.loudness'`

- [ ] **Step 3: 配置源**

`service/dramaclip/infra/config.py`：`DEFAULTS` 增两键（放在 `export.width` 之前）：

```python
    # 成片响度目标（EBU R128）：Phase C 整片两遍 loudnorm 收口，见 engines/exporter/loudness.py
    "export.loudness_target_lufs": "-14",
    "export.loudness_true_peak_dbtp": "-1.5",
```

并新增（与 `get_int` 同构，别在调用方各抄一份默认值）：

```python
def get_float(settings: Settings, key: str) -> float:
    """按 float 读取；缺失/非法回退 DEFAULTS（与 get_int 同一约定）。"""
    try:
        return float(settings[key])
    except (KeyError, ValueError, TypeError):
        return float(DEFAULTS[key])
```

- [ ] **Step 4: 写 `loudness.py`**

```python
"""Phase C：整片响度归一。

为什么放在拼接之后而不是段内：段内逐段归一会让相邻段之间忽大忽小（响度泵动），
而混音阶段的目标只是"比例正确"（旁白 vs 原声），绝对响度由这一层统一负责。
两遍法（先测后线性归一）是 ffmpeg 官方推荐路径；测完再复核一遍，超差即抛——
静默出一版"响度没到位"的片子等同于降级。
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # noqa: S404 - 参数为受控列表
from dataclasses import dataclass
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

_SAMPLE_RATE = 48000
_LRA = 11.0
_TOLERANCE_LU = 2.0  # 复核容差：线性模式受真峰值钳制，允许 2 LU 残差
_TIMEOUT_S = 600.0

_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


class LoudnessError(RuntimeError):
    """响度链路失败：测不出、近乎无声、或归一后仍偏离目标超容差。"""


@dataclass(frozen=True)
class LoudnessTarget:
    integrated_lufs: float
    true_peak_dbtp: float

    @classmethod
    def from_settings(cls, settings: config.Settings) -> "LoudnessTarget":
        return cls(
            integrated_lufs=config.get_float(settings, "export.loudness_target_lufs"),
            true_peak_dbtp=config.get_float(settings, "export.loudness_true_peak_dbtp"),
        )

    def filter(self, **extra: object) -> str:
        params = {"I": self.integrated_lufs, "TP": self.true_peak_dbtp, "LRA": _LRA}
        params.update(extra)
        return "loudnorm=" + ":".join(f"{k}={v}" for k, v in params.items())


@dataclass(frozen=True)
class LoudnessMeasurement:
    integrated_lufs: float
    true_peak_dbtp: float
    lra: float
    threshold: float
    target_threshold: float
    # 第一遍 loudnorm 自报的补偿量；两遍法必须回喂，否则第二遍会二次偏移
    offset_lu: float


def measure_args(source: str, target: LoudnessTarget) -> list[str]:
    return [
        "-hide_banner",
        "-nostats",
        "-i",
        source,
        "-map",
        "0:a:0",
        "-af",
        target.filter(print_format="json"),
        "-f",
        "null",
        "-",
    ]


def normalize_args(
    source: str,
    out_path: str,
    target: LoudnessTarget,
    measurement: LoudnessMeasurement,
) -> list[str]:
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-filter_complex",
        f"[0:a]{target.filter(**{
            'measured_I': measurement.integrated_lufs,
            'measured_TP': measurement.true_peak_dbtp,
            'measured_LRA': measurement.lra,
            'measured_thresh': measurement.threshold,
            'offset': measurement.offset_lu,
            'linear': 'true',
            'print_format': 'summary',
        })}[a]",
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        str(_SAMPLE_RATE),
        "-map_metadata",
        "-1",
        "-avoid_negative_ts",
        "make_zero",
        out_path,
    ]


def _parse_number(raw: str, field: str) -> float:
    value = raw.strip().strip('"')
    if value in ("-inf", "inf", "nan"):
        raise LoudnessError(
            f"响度测量 {field} 为 {value}：音轨近乎无声，这样的片子不该交付"
        )
    try:
        return float(value)
    except ValueError as exc:
        raise LoudnessError(f"响度测量 {field} 无法解析：{raw!r}") from exc


def parse_measurements(stderr: str) -> LoudnessMeasurement:
    match = _JSON_BLOCK.search(stderr)
    if match is None:
        raise LoudnessError(f"响度测量未输出 JSON（stderr 尾部：{stderr[-400:]}）")
    data = json.loads(match.group(0))
    missing = [k for k in ("input_i", "input_tp", "input_lra", "input_thresh") if k not in data]
    if missing:
        raise LoudnessError(f"响度测量缺字段：{missing}")
    return LoudnessMeasurement(
        integrated_lufs=_parse_number(str(data["input_i"]), "input_i"),
        true_peak_dbtp=_parse_number(str(data["input_tp"]), "input_tp"),
        lra=_parse_number(str(data["input_lra"]), "input_lra"),
        threshold=_parse_number(str(data["input_thresh"]), "input_thresh"),
        target_threshold=_parse_number(str(data.get("target_thresh", "0")), "target_thresh"),
        offset_lu=_parse_number(str(data.get("offset", "0")), "offset"),
    )


def _run(args: list[str]) -> str:
    proc = subprocess.run(  # noqa: S603
        [resolve_ffmpeg(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise LoudnessError(f"ffmpeg 退出码 {proc.returncode}：{(proc.stderr or '')[-400:]}")
    return proc.stderr or ""


def normalize_in_place(file_path: Path, *, target: LoudnessTarget, work_dir: Path) -> LoudnessMeasurement:
    """两遍法归一，原地替换 `file_path`，返回归一后的复核实测。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    measurement = parse_measurements(_run(measure_args(str(file_path), target)))
    staged = work_dir / "loudnorm_stage.mp4"
    _run(normalize_args(str(file_path), str(staged), target, measurement))
    if not staged.is_file() or staged.stat().st_size == 0:
        raise LoudnessError("响度归一未产出文件")
    os.replace(staged, file_path)
    checked = parse_measurements(_run(measure_args(str(file_path), target)))
    drift = abs(checked.integrated_lufs - target.integrated_lufs)
    if drift > _TOLERANCE_LU:
        raise LoudnessError(
            f"响度归一后仍偏离目标 {drift:.1f} LU"
            f"（实测 {checked.integrated_lufs:.1f} / 目标 {target.integrated_lufs:.1f}）"
        )
    if checked.true_peak_dbtp > target.true_peak_dbtp + 0.5:
        raise LoudnessError(f"真峰值超标：{checked.true_peak_dbtp:.1f} dBTP")
    return checked
```

- [ ] **Step 5: 接入 `export_plan`**

`service/dramaclip/engines/exporter/encoder.py`：

1. import `from dramaclip.engines.exporter import loudness`（同包，无环）。
2. `export_plan` 形参增 `loudness_target: loudness.LoudnessTarget | None = None`（**默认 `None` 仅用于"零加工模式不做归一"的显式关闭，不是兼容垫片**；生产调用点必传）。
3. `_concat` 之后：

```python
    segment_files = sorted(work_dir.glob("seg_*.mp4"))
    _concat(segment_files, out_path)
    if loudness_target is not None:
        loudness.normalize_in_place(
            out_path, target=loudness_target, work_dir=work_dir / "loudnorm"
        )
    if on_progress is not None:
        on_progress(100.0, "导出完成")
    return out_path
```

4. 文件 docstring 的「Phase B 拼接」之后加一行：`Phase C 响度：整片两遍 loudnorm 归一到 settings 目标（见 loudness.py）。`

`service/dramaclip/api/export.py:255` 的 `encoder.export_plan(...)` 调用增实参：

```python
        loudness_target=loudness.LoudnessTarget.from_settings(context.settings),
```

并在文件顶部 import `from dramaclip.engines.exporter import loudness`。

- [ ] **Step 6: 补桩与回归**

`tests/api/test_narration_audio_chain.py` 的 `_render` 里已有 `monkeypatch.setattr(encoder, "_concat", ...)`，再补一行：

```python
    monkeypatch.setattr(encoder.loudness, "normalize_in_place", lambda *_a, **_k: None)
```

新增 Phase C 接线证明（`tests/engines/exporter/test_loudness.py` 追加；该文件顶部需补 `from pathlib import Path`、`from dramaclip.engines.exporter import encoder, loudness`、`from dramaclip.engines.narration.models import PlanData, StrategySpec, TimelineSegment`）：

```python
def _one_segment_plan(tmp_path: Path) -> tuple[PlanData, str]:
    source = tmp_path / "ep1.mp4"
    source.write_bytes(b"x")
    plan = PlanData(
        mode="raw_clip",
        strategy=StrategySpec(),
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0)],
    )
    return plan, str(source)


def test_export_plan_runs_loudness_after_concat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase C 必须真被调用：它是成片响度的唯一负责人，漏调等于回到没人管响度的状态。"""
    plan, source = _one_segment_plan(tmp_path)
    out = tmp_path / "final.mp4"
    calls: list[str] = []
    monkeypatch.setattr(encoder, "_run_cut", lambda _args: None)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(
        encoder.loudness,
        "normalize_in_place",
        lambda path, **_kw: calls.append(Path(path).name),
    )
    encoder.export_plan(
        plan,
        {"ep1": source},
        out,
        tmp_path / "work",
        loudness_target=loudness.LoudnessTarget(integrated_lufs=-14.0, true_peak_dbtp=-1.5),
    )
    assert calls == ["final.mp4"]


def test_export_plan_skips_loudness_when_target_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`loudness_target=None` 是显式关闭位（今天只有测试用它）——生产调用方必须传值。"""
    plan, source = _one_segment_plan(tmp_path)
    monkeypatch.setattr(encoder, "_run_cut", lambda _args: None)
    monkeypatch.setattr(
        encoder, "_concat", lambda _files, target: Path(target).write_bytes(b"film")
    )
    monkeypatch.setattr(
        encoder.loudness,
        "normalize_in_place",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("归一不该被调用")),
    )
    encoder.export_plan(plan, {"ep1": source}, tmp_path / "final.mp4", tmp_path / "work")
```

- [ ] **Step 7: 设置页两字段**

`desktop/src/features/settings/sections.ts` 的 `EXPORT_SECTION.fields` 追加：

```ts
    {
      key: 'export.loudness_target_lufs',
      label: '成片响度目标 (LUFS)',
      type: 'number',
      min: -24,
      max: -6,
      help: '整片两遍归一的落点；移动端短剧建议 -16 ~ -12。数值越大越响，过大只会让平台压得更狠',
    },
    {
      key: 'export.loudness_true_peak_dbtp',
      label: '真峰值上限 (dBTP)',
      type: 'number',
      min: -6,
      max: 0,
      help: '防爆音的天花板，一般不用改',
    },
```

（AntD `InputNumber` 的 `min` 默认为 `-Infinity`，这里显式给负区间即可输入负数。）

- [ ] **Step 8: 校验设置页真的把负值写回**

Run: `cd desktop && npm run dev`（或该仓既有启动命令），进 设置 → 出片，把目标改成 `-12`，保存后
Run: `cd service && ../.venv/Scripts/python -c "import sqlite3;print(sqlite3.connect('../data/data.db').execute(\"select key,value from settings where key like 'export.loudness%'\").fetchall())"`
Expected: `[('export.loudness_target_lufs', '-12'), ('export.loudness_true_peak_dbtp', '-1.5')]`
（只读查询，不写库；改值走应用自己的设置页。）

- [ ] **Step 9: 跑测试 + 提交**

Run: `cd service && ../.venv/Scripts/python -m pytest -q`
Expected: PASS

```bash
git add service/dramaclip/engines/exporter/loudness.py service/dramaclip/engines/exporter/encoder.py service/dramaclip/infra/config.py service/dramaclip/api/export.py service/tests/engines/exporter/test_loudness.py service/tests/api/test_narration_audio_chain.py desktop/src/features/settings/sections.ts
git commit -m "feat(export): Phase C 整片两遍响度归一，目标值进设置页"
```

---

## Task 9: 门禁升级——量响度、验 `planner`、预检 LLM

**Files:**
- Modify: `scripts/verify_modes.py`

- [ ] **Step 1: 加 `EXPECT_PLANNER` 与 R128 测量**

在 `EXPECT_NARRATION` 之后：

```python
# 编排来源预期：文案真值化（P-1.5）之后，除零加工两模式外必须是 LLM 成稿。
EXPECT_PLANNER = {
    "raw_clip": "rule",
    "subtitle_flow": "rule",
    "intro_narration": "llm_script",
    "cross_narration": "llm_script",
    "ultra_short_hook": "llm_script",
    "dialogue_narration": "llm_script",
    "full_narration": "llm_script",
    "dual_host_chat": "llm_script",
    "inner_monologue": "llm_script",
}

# 响度窗口（LU）：实测 integrated 与目标的允许偏差，与 Phase C 复核容差同源
LOUDNESS_TOLERANCE_LU = 2.5
```

在 `mean_volume_db` 之后新增（`ebur128` 才是 R128 权威量法；`volumedetect` 的 mean_volume 只是平均样本幅值，不能与 LUFS 混谈）：

```python
def ebur128(video: Path) -> tuple[float | None, float | None]:
    """(integrated LUFS, true peak dBFS)；解析失败返回 (None, None)。"""
    proc = sh([FFMPEG, "-hide_banner", "-nostats", "-i", str(video),
               "-filter_complex", "ebur128=peak=true", "-map", "0:a:0",
               "-f", "null", "-"])
    lines = proc.stderr.splitlines()
    integrated = peak = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Integrated loudness:"):
            for cand in lines[i + 1:i + 4]:
                if cand.strip().startswith("I:"):
                    try:
                        integrated = float(cand.split("I:")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
        if line.strip().startswith("True peak:"):
            for cand in lines[i + 1:i + 4]:
                if cand.strip().startswith("Peak:"):
                    try:
                        peak = float(cand.split("Peak:")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
    return integrated, peak
```

- [ ] **Step 2: LLM 预检（与 TTS 预检同构）**

在 TTS 预检块之后追加。没有它，"七模式全失败"会被误读成产品崩了，而实际只是没配 LLM：

```python
    from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig

    llm_config = LlmConfig.from_settings(ctx.settings)
    if not llm_config.configured:
        print("预检失败：LLM 未配置（llm.base_url/llm.model）——"
              "P-1.5 后解说文案不降级，七个解说模式必然全红", file=sys.stderr)
        return 2
    try:
        took = LlmClient(llm_config, timeout_s=30.0).ping()
    except Exception as exc:  # noqa: BLE001 - 预检就是要吞下一切环境问题
        print(f"预检失败：LLM 不可达（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 2
    print(f"预检通过：LLM={llm_config.model} 往返 {took:.2f}s")
```

- [ ] **Step 3: 记录与断言**

`rec.update({...})` 之前先量一次（`ebur128` 每调一遍就要整片解码一次音频，取两个值不该跑两遍），并在 `rec.update` 里加两个键：

```python
        integrated, true_peak = ebur128(clip)
```

```python
            "integrated_lufs": integrated,
            "true_peak_dbtp": true_peak,
```

断言区把原 `MIN_MEAN_VOLUME_DB` 一条替换为响度窗口 + planner 两条：

```python
        expected_planner = EXPECT_PLANNER.get(mode, "rule")
        if rec["planner"] != expected_planner:
            failures.append(f"{mode}: 文案来源 planner={rec['planner']}，预期 {expected_planner}"
                            "（说明该模式仍在走模板或剧本链没接上）")
        target = float(ctx.settings.get("export.loudness_target_lufs", "-14"))
        got_lufs = rec["integrated_lufs"]
        if got_lufs is None:
            failures.append(f"{mode}: ebur128 未测出 integrated 响度（门禁本身不可信，先修测量）")
        elif abs(got_lufs - target) > LOUDNESS_TOLERANCE_LU:
            failures.append(f"{mode}: 响度 {got_lufs:.1f} LUFS 偏离目标 {target:.1f} 超过 "
                            f"{LOUDNESS_TOLERANCE_LU} LU")
        if rec["mean_volume_db"] is None or rec["mean_volume_db"] < MIN_MEAN_VOLUME_DB:
            failures.append(f"{mode}: 近乎静音（mean_volume={rec['mean_volume_db']} dB）")
```

（`MIN_MEAN_VOLUME_DB` 保留：它防的是"整条音轨没声"，与响度窗口是两件事，删掉会丢一层保险。）

表头加 `LUFS` 与 `峰dB` 两列，行内对应输出 `rec.get('integrated_lufs')` / `rec.get('true_peak_dbtp')`（缺失打 `-`）。

- [ ] **Step 4: 冒烟：门禁必须能抓到假绿**

临时把 `EXPECT_PLANNER["full_narration"]` 改成 `"nope"`，只跑一个快模式：
Run: `.venv/Scripts/python scripts/verify_modes.py --modes full_narration > /tmp/gate.log 2>&1; echo REAL_EXIT=$?`
Expected: `REAL_EXIT=1` 且日志含「文案来源 planner=llm_script，预期 nope」。改回常量后重跑同一命令。
**不要**用 `| tail` 判退出码——那是上一轮真踩过的坑（管道退出码是 `tail` 的）。

- [ ] **Step 5: 提交**

```bash
git add scripts/verify_modes.py
git commit -m "test(gate): 响度按 R128 实测断言、planner 逐模式验源、补 LLM 预检"
```

---

## Task 10: 真机复验（P-1.5 出口）

不产新代码，只产证据。这一步是本批次的定义本身——P-1.5 的出口判据写在门禁上，没跑过就不算完成。

- [ ] **Step 1: 确认环境就绪**

Run: `ls resources/ffmpeg/ffmpeg.exe && ls data/models/tts/kokoro 2>/dev/null | head -3`
Expected: 文件存在。素材目录默认 `D:\BaiduNetdiskDownload\小小球神不好惹`（`--media` 可换）。

- [ ] **Step 2: 先跑单模式，确认文案真的换了**

Run: `.venv/Scripts/python scripts/verify_modes.py --modes full_narration > /tmp/gate-full.log 2>&1; echo REAL_EXIT=$?`
Expected: `REAL_EXIT=0`，表格里 `planner=llm_script`、`LUFS` 落在目标 ±2.5。
再人工看一条：`ls -t data/logs/llm/llm_script_*.json | head -1` 之后
Run: `.venv/Scripts/python -c "import json,sys,glob;p=sorted(glob.glob('data/logs/llm/llm_copy_*.json'))[-1];d=json.load(open(p,encoding='utf-8'));print(d['user'][:1200])"`
Expected: prompt 里能看到 `[full-1] 职责：开篇…` 与区间台词。**若 `llm_copy_*` 一个都没有，说明语言层根本没被调用，别往下走。**

- [ ] **Step 3: 九模式全跑**

Run: `.venv/Scripts/python scripts/verify_modes.py --modes all --out D:/tmp/dc-p15 > /tmp/gate-all.log 2>&1; echo REAL_EXIT=$?`
Expected: `REAL_EXIT=0`。九条全成、`planner` 除 raw_clip/subtitle_flow 外全 `llm_script`、响度全在窗口内、`max_freeze_s` 全部 <2。
耗时提示：LLM 成稿 7 次 + TTS 若干 + 渲染，单集素材约 15-25 分钟；用 `run_in_background`，不要中途判死。

- [ ] **Step 4: 用耳朵验收一条（不可省略）**

响度数字过关不等于好听。至少人工听 `full_narration`（旁白压原声最重）与 `dual_host_chat`（双音色）各一条，确认：
① 旁白没有被原声盖住；② 双人交替的音色区分仍在；③ 没有因 `normalize=0` 带来的爆音。
把这一步的结论写进 Step 5 的记录里——**写"已听，结论 X"，不接受"断言全绿所以应该没问题"**。

- [ ] **Step 5: 把实测写回计划并清理临时目录**

在本文档末尾追加 `## Task N 落地后的实测修正` 小节，记录：九模式实测表（planner/LUFS/峰/时长/冻结）、与预期不符之处、以及计划里被证伪的假设（如有）。

清理。临时目录由 `_same_drive_temp` 创建，**首选 `dir=REPO`，所以它们落在仓库根**（`.gitignore` 的 `/tmp_*` 正是为它们准备的）。
其中 `tmp_dc-verify-data_*` 里有一个名为 `models` 的目录联接，指向真实的 `data/models`——
**顺序不可颠倒**：先 `rmdir` 摘掉联接，再 `rm -rf` 目录；反过来 `rm -rf` 会顺着联接删掉开发者的模型。

```bash
cd D:/PersonProjects/DramaClip
for d in tmp_dc-verify-data_*; do cmd //c "rmdir $(cygpath -w "$PWD/$d/models")" 2>/dev/null || true; done
rm -rf tmp_dc-verify-data_* tmp_dc-verify_* D:/tmp/dc-p15
ls data/models/tts/kokoro/*/ | head -3   # 必须仍在：联接被删过一次就再也没有了
```

若最后一条 `ls` 为空，立刻停下并报出来——那说明联接连同模型被误删，需要从 `data/models` 的备份或重新下载恢复，不要继续提交。

- [ ] **Step 6: 提交**

```bash
git add docs/superpowers/plans/2026-09-11-p1-5-copy-truth-and-no-downgrade.md
git commit -m "docs(plan): 记录 P-1.5 真机复验结果与实测修正"
```

---

## 完成判据（全部满足才算 P-1.5 收口）

1. `cd service && ../.venv/Scripts/python -m pytest -q` 全绿（`test_analysis.py` 的既有隔离 flake 除外，且本批次未碰它）。
2. Task 10 九模式门禁 `REAL_EXIT=0`，实测表已写回本文件。
3. `grep -rn "_CROSS_NARRATIONS\|narration_texts_for\|intro_text\|build_dialogue\|dialogue_selector\|_run_generation\b" service/dramaclip --include=*.py` **无输出**——模板池与规则退路一个不剩。
4. `grep -rn "降级" service/dramaclip/engines/narration --include=*.py` 只剩 Task 1 分类表里被裁决为"允许"的两处（口味层选题、风格回退），且都在同一次运行内只发生一次并打了日志。
5. 设置页两个响度字段可改可存，且改一次目标值不需要改代码。

## 已知不做 / 不在本批

- 跨集化：intro/cross/full 等仍是单集素材（`episodes[0]`），跨集是 P-2 `narration.plan_variants` 的事。
- `subtitle_flow` 的 `_CTA_TEXT` 仍是硬编码——它是字幕卡片上的一句引导，不是解说文案，出口判据也没要求它。
- 分析层 LLM→关键词降级、`video` 域是否立项、说话人分离：均维持 §11 归属，本批不动。
- 跨盘 ASS 路径转义脆弱性（Task 8 之前发现的真实产品缺陷）留在 Backlog，Phase C 不掩盖它。
- 响度的"听感"验收（Step 4）只能由人做；断言过关不代表耳朵过关。
