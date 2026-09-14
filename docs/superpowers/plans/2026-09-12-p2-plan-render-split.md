# P-2a 规划/渲染解耦 实施计划

> ✅ **全计划已按「P-2a 做真跨集」的裁决审计完毕，Task 1–11 均可执行（2026-09-12）。**
> 本轮审计覆盖 **Task 6–11 与全部尾部章节**（Task 1–5、3b、3c 由上一轮重构完成，见《修订记录（2026-09-12 跨集裁决后）》C1–C13；本轮的改动记在 **C14–C23**）。逐条核过的东西：`_plan_one`/`_casting_for` 的按集取数、重叠度量与两道闸门都走 `(episode_id, start, end)` 三元组、`get_plan` 的取材集暴露与 `plan_cost` 的集数无关性、`export.submit` 守卫的逐集覆盖、九模式门禁**七个阈值逐条重新推导**（结论：一个字不改，依据在 Task 9 Step 2.8 的表）、全部 `Task N Step M` 交叉引用、以及"已作废的收窄"在全文的残留（《P-2c 取消记录》已就位，《开放问题》一节已补上——它原先被正文引用五处却根本不存在）。
> **唯一的开工前置**：《开放问题》#5 —— `raw_clip` 在 `--variants 1`（门禁默认口径）下会把 `_fit_duration` 的预算吃满，活库实测 planned **296.21s / 51 段 / 9 集**、成片预估 **≈303s** > 用户设的 **300s**。修法是给预算留一档编码漂移余量（落在 Task 3c 的 `_fit_duration`），**余量取多少是设计决定，本审计没有替业主拍**。Task 11 已把 `raw_clip` 那一跑挪到 `--variants 3`（不撞这条）并另加 Step 3d 用"只算不渲"的脚本量这个数；《完成判据》#10 要求收口前**要么改掉、要么明确接受并登记**，不许既不改也不记就签收。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `narration.produce` 拆成 `narration.plan_variants`（只规划）与 `export.submit`（只渲染），让阶段③ 能"只看方案、反复重掷、不付渲染成本"，并让一个模式的 K 条方案真的是 K 个互异的卖点角度。

**Architecture:** 四层切分——**选题层**（新增 `engines/narration/angles.py`：一个模式一次 LLM 调用产出 K 条卖点互异的取材角度，每条带角度名/理由/钩子首句/取材集）、**取材层**（新增 `engines/narration/casting.py`：给场景盖上集身份、给出跨集叙事顺序、按集分开台词表——**一条方案的时间轴因此可以横跨多集**，规格 §1 的「跨集方案」）、**成稿层**（既有 `copywriter` / `scriptwriter`，本批次多接一个"卖点角度"输入，并把槽位台词改成**按集取用**，不改其降级禁令）、**度量层**（新增 `engines/narration/overlap.py`：按源素材秒算 Jaccard 取材重叠，超 60% 的角度当场不出）。配音留在规划侧，故一条 `ready` 的方案行就是可渲染的成品输入，`export.submit` / `export.retry` 只读库、不做任何规划。

**Tech Stack:** Python 3.12 / pydantic v2 / SQLite（迁移 010）/ stdlib urllib（ADR-005 统一 OpenAI 协议）/ pytest / ruff / mypy strict；契约侧 JSON Schema + TypeScript（`protocol/`）。

规格出处：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §6（P-2 五项与出口判据）、§5 映射表 #16/#17/#18/#19/#20/#22、§4.3（剧空间③ 规格）、§3.3.1（降级裁决表）、§2.3（四阶段）。前批落地真相源：`docs/superpowers/plans/2026-09-11-p1-5-copy-truth-and-no-downgrade.md`（尤其《降级分类表》《实现定案修正》与四个 `### Task N 落地后的实测修正` 节）。

---

### 计划修订记录（2026-09-12 审查后）

本节是一次**逐条对代码/对真工具核验**的审查结果，不是风格意见。本批次已经为"编造出来的规格"付过两次账（`loudnorm` 的 JSON 键名被写成 `offset`/`target_thresh`，真机是 `target_offset`/`output_thresh`，于是偏移回喂从落地那天起恒为 0.0；`-filter_complex ebur128=…` 配 `-map 0:a:0` 在随包 ffmpeg 上直接失败，会让九个模式一起报"门禁不可信"）。**所以下面每一条修正都附了它据以修正的实测证据**，重审时请按同一标准复核。

审查基线：`git log --oneline -1` = `9b42f24`（TTS 音频文件名内容寻址）。SQLite 实测环境 = 本仓 `.venv` 自带 `sqlite3.sqlite_version 3.50.4` / pysqlite `2.6.0`。

#### 阻塞缺陷（B1–B12）

| # | 原计划错在哪 | 实测证据 | 改在哪 |
|---|---|---|---|
| **B1** | Task 9 Step 2 把 `verify_modes.py` 的派发改成 `export.submit`，但那个 `Router()` 是**循环内新建的、只注册了 `narration_api`**；`export_api` 连 import 都没有。`Router.dispatch` 会回 `-32601 方法不存在`，九个模式全红、门禁 exit 1——而这条门禁一小时前才 9/9 通过，是 P-1.5 的出口判据 | `scripts/verify_modes.py:456-457` 逐字是 `router = Router()` / `narration_api.register(router, ctx)`；`:39` 只有 `from dramaclip.api import narration as narration_api`，全文无 `export` 导入 | Task 9 Step 2 新增第 1 点（补 import + `export_api.register`）；Task 9 的 Files 行改为按锚点列举；Step 1 的触点清单补上这两行 |
| **B2** | Task 6 Step 7 第 11 点让 `_run_plan_variants` **对每个模式**都先调 `angles.select_angles`，而它在 LLM 未配置时抛 `LlmUnavailable`。这等于**悄悄推翻了用户定案**：规格 §4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」、§4.3 ④「解说类 = K，规则类 = 全剧 top-K 冲突窗（两者不同源，已由用户定案）」 | `api/narration.py:43` `_NO_TTS_MODES = frozenset({"raw_clip", "subtitle_flow"})`；`verify_modes.py:87-88` 的 `EXPECT_PLANNER` 把这两个模式钉在 `"rule"`；`modes_w9.py` 全文无 `NarrationText` | 新增《定案四》+ 新增 **Task 3b**（`pipeline.top_conflict_windows` 纯函数）+ Task 6 Step 7 第 11 点按模式族分流 + Step 3 补三条规则族用例 + Step 10 补变异检查；Task 9 Step 6 的迁移表逐条交代被打断的五个用例（见下）|
| **B2 附带** | 五个用例被 B2 打断而计划未提：`test_data_paths.py::test_export_output_lands_under_data_dir`、迁移后的 `test_plan_then_submit_renders_work_end_to_end`、`test_bookkeeping_error_never_replaces_the_original`、`test_plan_variants_bookkeeping_raise_releases_cancel_event`、`test_style_selection_only_paid_for_modes_that_narrate` | 前四条都打 `modes:["raw_clip"]`：规则模式被拖进选题后作业必 failed，而它们断言 `completed`。**第五条更糟**：它设了 `llm.base_url`（`test_produce.py:213`）却只桩了 `script_driver.LlmClient`（`:219`），`angles.LlmClient` 未桩 → 会朝 `http://llm.test/v1` 发**真出站请求**，`ANGLE_LLM_TIMEOUT_S = 240.0` × `_ATTEMPTS = 2` ≈ 8 分钟挂死 | Task 9 Step 5 加了前置说明；Step 6 的迁移表为这五条各写了一行处置（含"必须同时桩 `angles.LlmClient`"这条硬要求） |
| **B3** | Task 9 Step 6 让 `test_style_directives_reach_the_copy_prompt` 的落库断言从 `_newest_ready_plan` 换成 `plans_repo.list_by_project(...)[0]`，但 `_plan_one` **不落库**（`plans_repo.create` 在 `_run_plan_variants` 里），列表是空的 → `IndexError` | Task 6 Step 7 第 11 点给的 `_plan_one` 返回 `(PlanData, list[str])`，函数体内无任何 `plans_repo` 调用 | Task 9 Step 6 该行改为断言**返回的 `PlanData`**，并写明"落库文案与槽位 id 对应"这条不变量由 Task 6 的 `test_plan_variants_writes_k_plans_without_rendering` 承担 |
| **B4** | Task 1 的 `test_list_by_project_newest_first_still_carries_angles` 断言 `[:2] == ["新角度","旧角度"]`，靠 `ORDER BY created_at DESC`。背靠背插入时这个前提不成立 | **本机实测**：连续两次 `_now_ms()` 相同的比例 **2000/2000 = 100.0%**；并列时 `ORDER BY created_at DESC` 返回**先插入**那一行 **200/200**。计划自己在《定案三》里就引了 `infra/jobs.py:94-96`（那处为同一件事补过 `created_at, id` 兜底），却写了个假设相反的用例 | Task 1 Step 1 把该用例拆成两条：`test_list_by_project_still_carries_the_angle_columns`（只断集合成员与往返，**不断顺序**）+ `test_list_by_project_breaks_created_at_ties_by_id`（raw SQL 钉住并列时间戳）；Step 5 给 `list_by_project` 补同一个 `, id` 兜底；Step 7 加变异检查 #5。**没有用 sleep** |
| **B5a** | Task 1 Step 7 变异 #1 声称去掉 `_COLUMNS` 里的 `"overlap_max"` 会让 `zip(..., strict=True)` 因列数不符抛 `ValueError` | **实测**：SELECT 列表与 zip 用的是**同一个** `_COLUMNS`，去掉一列后两边都是 11 项，`zip(strict=True)` **不抛**；真正的失败是随后 `fetched["overlap_max"]` 抛 **`KeyError: 'overlap_max'`** | Task 1 Step 7 #1 的失败形态改成 `KeyError`，并写明"`strict=True` 在这里救不了你"的理由 |
| **B5b** | Task 1 Step 7 变异 #3 声称把 `ORDER BY narration_mode, variant_index` 改成 `ORDER BY created_at` 会红——不会 | **实测**：原夹具按 (batch-a,1),(batch-a,2),(batch-b,1) 顺序插入且全是 `full_narration`，升序 `created_at` 给出**完全相同**的结果。而 `narration_mode` 这半个排序键（也就是 docstring 里写的全部理由）**一条用例都没有** | Task 1 Step 1 把夹具重种为 `(batch-a, raw_clip, 1), (batch-a, full_narration, 2), (batch-a, full_narration, 1), (batch-b, full_narration, 1)` 并用 raw SQL 拉开 `created_at`。**实测**：正确排序 → `[(full_narration,1),(full_narration,2),(raw_clip,1)]`；`ORDER BY created_at` → `[(raw_clip,1),(full_narration,2),(full_narration,1)]`；`ORDER BY variant_index` → `[(raw_clip,1),(full_narration,1),(full_narration,2)]`——两条变异都红。Step 7 加 #3b 专钉 `narration_mode` 那半键 |
| **B6** | Task 7 Step 3 变异 #2 声称把 `tts_calls` 改成 `len(plan.timeline)` 会红 `test_get_plan_returns_row_and_cost`——不会，因为那条用例用 `full_narration`；而断言 `tts_calls == len(plan.narration_texts)` 是把实现自己的公式又算了一遍 | `modes_w8.py:46-58`：`build_full` 每个 `NarrationText` 恰好配一个 `ducked` 段，故 `len(timeline) == len(narration_texts)` **恒等**。对照组：`modes/__init__.py:60-75` 的 `build_intro` 是 3 段 1 槽、`modes_w5.py:40-72` 的 `build_cross` 是 6 段 3 槽 | Task 7 Step 1 的 `test_get_plan_returns_row_and_cost` 改用 `intro_narration`，断言**字面整数** `{"copy_llm_calls": 1, "tts_calls": 1}`，并加一条夹具前提断言 `len(plan.timeline) == 3 and len(plan.narration_texts) == 1`（前提塌了用例要自己说清楚） |
| **B7a** | Task 6 Step 7 第 12 点只列了 `ExportRun, render_export` 两个待删 import，漏了 `exports as exports_repo` → ruff **F401**，而 Step 9 的门禁写着"Expected: 无输出" | `api/narration.py:21` 导入 `exports_repo`，全文件唯一使用点是 `:377` 的 `exports_repo.create(...)`，它在 `_run_produce` 里，随该函数一起删 | Task 6 Step 7 第 12 点的待删 import 清单补上 `from dramaclip.infra.storage.repos import exports as exports_repo` |
| **B7b** | Task 6 Step 7 第 2 点让新增 `from dramaclip.engines.narration import angles, overlap` **单独一行** → ruff **I001** | 用本仓 `.venv/Scripts/ruff.exe`（`select = ["E","F","W","I","UP","B","SIM"]`、`line-length = 100`）实跑：isort 要求合并成 `from dramaclip.engines.narration import angles, copywriter, overlap, script_driver, scriptwriter`（**96 字符**）；`from dataclasses import dataclass` 必须插在 `from typing import Any` **之前**（同一 stdlib 块内 `import x` 先于 `from x import y`，且 dataclasses < typing） | Task 6 Step 7 第 2 点改成给出**合并后的整个 import 区**，不给"新增一行"这种指令。同类问题在测试文件侧也修了（Task 6 Step 3 的 import 说明、Task 5 Step 1） |
| **B8** | Task 4 Step 8 `git add … service/tests/engines/narration …` 暂存了**整个目录**，会卷走另一位工程师/另一个代理的文件，违反计划自己的《提交纪律》 | 《开工前置》末段逐字写着「只 `git add` 显式路径，**禁止 `git add -A` / `git add .` / `git commit -a`**」 | Task 4 Step 8 改为逐个列出本任务真改的四个测试文件 |
| **B9** | Task 10 Step 6 与《完成判据》#6 要求 `grep _run_generation_parallel …` **无输出**，但它现在有一处**永久散文命中**；执行者要么以为坏了、要么去改别人的文件 | `engines/narration/pipeline.py:236-237`（一小时前随 `9b42f24` 落地）：`_synthesize_into` 的 docstring 里写着「与并发写同名文件（`_run_generation_parallel` 双线程、produce 与 generate_plans 重叠）」——而 Task 6 正好删掉这三个名字 | Task 5 Step 5 新增"改 `_synthesize_into` docstring"这一步（它确实随三个函数消失而过期）；Task 10 Step 6 与《完成判据》#6 的 grep 拆成**定义清零**与**调用点清零**两条，后者带 `.mjs` 且 Expected 改成"恰好一条 `verify_e2e.mjs`"（见 R6）。**顺带查出同类三处**：`api/export.py:53,56`（`ExportRun` docstring 写 `start/retry/produce` 三处调用点）、`api/export.py:76`（`_submit_export` docstring 写 `start 与 retry`）、`scripts/verify_modes.py:382`（注释写 `_generate_one 就是这么拼路径的`）——分别由 Task 8 Step 3、Task 9 Step 2 接手 |
| **B10** | Task 11 Step 1 期望 `--variants 3` 能证明"规划阶段一条片都没渲"，但 Task 9 Step 2 的改写让门禁**总是**提交渲染 → 这个 Expected 是虚构的 | Task 9 Step 2 的替换块里有 `submit = router.dispatch(... "export.submit" ...)`，无条件执行 | Task 9 Step 2 新增 `--plan-only` 旗标（规划完就停，并**查库断言该 batch 的 `export_jobs` 行数为 0**）；Task 11 Step 1 改用 `--plan-only`，Expected 改成 `REAL_EXIT=0` + `phase=plan-only` + `plans=3` + `export_jobs=0` |
| **B11** | Task 11 Step 2 的期望数字（三条角度、`overlap_max` 首条 None 其余近 0）需要**至少 3 集已分析**，而门禁自己不分析任何东西，只读复制来的 `data/data.db` | 门禁的 `done` 计数在 `verify_modes.py:438-441`（只打印、不设卡）。若只有 1 集：`full_narration` 是单集模式（`_CROSS_EPISODE_MODES` 只含 `dialogue_narration`），三条角度全指向第 1 集 → 取材逐秒相同 → 重叠 1.0 → 第 2、3 条被拦 → 作业 **failed**，而不是"规划阶段没渲染" | Task 9 Step 2 在 `done` 打印之后加一条**前置条件停机分支**（`done < args.variants` → 打印原因 → `return 2`，与门禁既有的"环境未就绪"同一档）；Task 11 Step 2 的 Expected 补上"先确认这一行"的判据 |
| **B12** | Task 9 Step 4 说替换 `narrationApi` 整块（`:108-125`），Task 8 Step 6 说 `exportApi` 是 `:126-133`。两个范围都错，且错在**危险方向** | `desktop/src/services/client.ts` 实测：**108** 是 `listWorks` 的收尾 `}`，**109** 空行，`narrationApi` 是 **110–125**；**126** 空行，`exportApi` 是 **127–132**。按 `:108-125` 逐字替换会吃掉 `listWorks` 的右括号，文件当场语法错 | 两处都改成**按内容锚点描述**（"`export const narrationApi = {` 起、到它自己的 `} as const;` 止"），并把实测行号作为附注而非指令 |

#### 需求漏项（R1–R8）

| # | 漏了什么 | 改在哪 |
|---|---|---|
| **R1** | = B2。另外《自查》表里 §4.2 与 §4.3 ④ **两行都没有** | 《自查》表新增两行（§4.2 的"仅两模式不依赖 LLM"、§4.3 ④ 的"两族条数不同源"），落点指向《定案四》与 Task 3b |
| **R2** | 规格 §1「每模式产出 1..K 条卖点角度互异的**跨集**方案」被《定案二》收窄成"角度之间跨集、单条方案内仍限一集"，却写成了**已定的计划注记**。收窄的理由是站得住的（今天只有 `dialogue_narration` 能跨集拼；九模式门禁的时长/响度窗正压在现有成片形态上），但 §1 把跨集当成定义性属性，**这不是计划自己能定的** | 《定案二》末段与《P-2c 交接规格》都改成 **待业主签字**（明确写"未签字前不得当作已决"），并进《开放问题》#1 |
| **R3** | §5 #21 `serial_per_episode` 被丢出本批次，理由（规格 §5 挂在 `plan_variants` 上、§4.3 ④ 说它是提交时参数且不写 `project.settings`，两处不可能同时对）是对的，但计划把它写成了"已裁决不做" | 《已知不做》改成**悬空的业主问题（当前无人认领）**，保留 720 条（80 集 × 9 模式）的量级论证与"天然属 P-2.5"的结论，并进《开放问题》#2 |
| **R4** | `docs/03-IPC协议规范.md:86` 逐字是 `\| -32401 \| export \| 编排方案不存在 / 编排时间轴为空 \|`。Task 8 之后"时间轴为空"改判 `-32407`/`rejected`，而 Task 10 Step 2 只**加**行不改这一行 → 文档描述一个已不存在的行为，正是 §9.5 的假文案类 | Task 10 Step 2 新增第 5 点：把 `:86` 改成只写"编排方案不存在"，并注明空时间轴迁到 `-32407` |
| **R5** | `verify_modes.py:75-85` 用**散文**从 `_generate_one` 的行为推出 `EXPECT_PLANNER`（`:78` 逐字是「`_generate_one` 只在 `plan.narration_texts` 非空时才调 copywriter」），而 Task 6 删掉 `_generate_one`；Task 9 Step 2 只改 `:453-500` | Task 9 Step 2 新增第 4 点：重写 `:75-85` 的推导散文（改指 `_plan_one` / `_rule_variants`），并顺带修 `:382` 那条 `_generate_one` 注释 |
| **R6** | **漏了一个活的调用方，而且漏了两次**。Task 9 Step 1 的 grep 用 `--include=*.py --include=*.ts --include=*.tsx --include=*.json --include=*.md`，**没有 `.mjs`**；《完成判据》#6 同样没有。于是那句「逐条对账，一条都不许漏」正好漏掉它 | 实测 `scripts/verify_e2e.mjs` 有**两处**（不是一处）：`:152` 派发 `narration.generate_plans`、`:168` 派发 `export.start`。它是另一位工程师的文件，P-2a **不得编辑**。Task 9 Step 1 的 grep 加 `--include=*.mjs`、Expected 明确列出这两条命中；新增 **Task 9 Step 1b：书面移交该文件的属主**；《完成判据》#6 同步 |
| **R7** | `_plan_one`（一次成稿往返）跑在重叠闸门**之前**，被拦掉的角度照样付了成稿钱，而它不留行 → 这笔花费在库里无从重算 | 分成两半修：① **可判定的部分前置**——同模式同集的两条角度，其时间轴是 `(mode, episode)` 的纯函数（`_plan_one` 的非剧情解说分支里 `brief` 只进 `copywriter` 的 `angle_block`，**不进 `build_plan`**），故重叠必然 100%，成稿前即可判；Task 6 Step 7 第 11 点加这道前置闸门，配 `test_rejected_angle_does_not_pay_for_copy`。② **不可判定的部分如实记账**——`dialogue_narration` 的剧本由模型按角度现写，成稿前无从判定；写进 `plan_cost` 的 docstring 与《定案二》 |
| **R8** | `_MAX_REASON_CHARS = 60` 的 raise 分支**既无用例也无变异检查**；而 Step 6 声称"十三条拒绝分支" | 实数 `_sanitize` **13** 条 raise + `select_angles` **5** 条（`k<1`、`LlmUnavailable` 守卫、无已完成集、无转写、重试耗尽汇总）= **18** 处抛出点。Task 3 Step 2 补 `test_oversize_reason_raises`；Step 6 的表从 13 行扩到 **18 行**、计数句改成 18；《文件结构》里 `test_angles.py` 那行的"12 条变异检查"改成 18 |

#### Task 5 整段重写（前提一小时前已被修掉）

Task 5 原本的存在理由是"给每个作业单独一个 TTS 目录，免得 K 条变体互相覆盖"。**那个 bug 已经在 `9b42f24` 修掉了**，而且修在拥有路径的那一层：`pipeline._content_addressed_audio(work_dir, slot_id, text, voice, engine)` → `work_dir / f"{slot_id}-{sha1(text|voice|engine)[:12]}.mp3"`（`pipeline.py:213-227`），配 `_synthesize_into`（`:230-247`）的缓存优先、uuid 暂存名、`os.replace` 原子换入、`finally` 清理，由 `service/tests/engines/narration/test_tts_audio_isolation.py` 六例变异检验守着。后果逐条应用：

- 原 Task 5 的头条断言 `len(set(written)) == len(written)` **严格弱于**已落地的用例。那个文件的 docstring 第 9 行逐字写着：「只断言"两条路径不同"抓不住 stale-pointer 回归，内容断言才抓得住」。
- 原变异检查 #1（把 tts 目录改回 `context.work_dir / "tts"`）**是死的**：内容寻址单独就能让路径互异，改回去一条用例都不红。
- 原 `_voice` 的 docstring 会作为**一句关于代码的假话**被提交（"K 条同模式变体因此算出同一批文件名；共用一个 tts 目录时后一条会覆盖前一条的音频"）。这正是 `loudnorm` 键名那次的失败形态：一个说得通的故事被烤进注释，下游所有人都会信它。
- **目录分层被删除，而不是重新辩护**。按作业/按变体分目录会让 `pipeline` 的缓存优先在 api 层失效——`test_identical_copy_is_synthesised_once` 钉的正是"同文案不二次付费"，分目录之后整组重规划与重掷都要为没改过的槽位再付一次配音。Task 5 只保留 `_voice` 作为 `plan_variants` 唯一的配音出口（一个知道 tts 目录与 models 目录的地方），并把它**对内容寻址的接线**用内容断言钉住。
- 全部 `pipeline.py` 行号引用重新核过（内容寻址那次提交给它加了约 40 行）：`:232`→`:273`、`:249/:250`→`:292/:293`、`:251-256`→`:250-303`、`build_from_script_episodes` `:85-171`→`:88-174`、槽位 id `:126/141/157`→`:128/144/160`。计划里一律改成**函数名锚点优先、行号只作附注**。
- 新增 Task 5 Step 5：改 `_synthesize_into` 的 docstring（它点名了 Task 6 要删的三个函数），这同时清掉 B9。
- **新记一笔交给 P-3**：内容寻址意味着**文案相同的两条方案共用同一个音频文件**，而《定案一》把 `work_dir` 提升为承重存储。故未来任何按时间或按创建作业删除的回收站，都会静默作废另一条老方案的 `audio_path`。写进末尾《P-3 交接规格》。同时记下修复代理点出的残余：摘要覆盖 text+voice+engine **名**，不覆盖模型权重，所以 Kokoro 升级之后旧文件会一直被当成命中，直到有人删掉它。

#### 两条外部契约（本轮实测，非推断）

| 契约 | 实测结果 |
|---|---|
| `ALTER TABLE ADD COLUMN … NOT NULL DEFAULT ''` 打在**有数据的表**上 | 在 `D:/tmp` 的 scratch 库上跑真迁移（`db.migrate` 应用 001–009）+ 3 行按**旧 7 列** INSERT 写入的方案行，再 `executescript` 010 的五条 ALTER：合法；三行旧数据读回 `('', '', 1, None, None)`，即各列拿到迁移里的 DEFAULT；`pragma integrity_check` = `ok`；12 列 SELECT + `zip(strict=True)` 正常。**重复应用** 010 抛 `sqlite3.OperationalError: duplicate column name: angle`（响亮失败，不会静默损坏）。`migrate()` 按文件名记账，正常路径不会重放。**活库确认有数据**：`data/data.db` 只读查询得 `narration_plans` **52 行**、1 个项目、`episodes` 中 `status='done'` **10 集**，现有列仍是旧 8 列（`tts_segments` 在内，佐证它是死列）。结论写进 Task 1 Step 3 |
| 计划里的错误处理**静默依赖 Router 不做 JSON Schema 校验** | `transport/rpc.py:78-88` 的 `dispatch` 全文只有：查表 → `handler(request.params)` → 捕获 `RpcDomainError`/`Exception`。**没有任何 schema 校验**。所以 `-32303`（k=9 对 schema 的 `maximum: 8`）与 `-32302`（空 modes 对 `minItems: 1`）只因为校验是手写的才会触发；哪天有人"给 Router 加上 schema 校验"，这两个错就会变成 `-32602 INVALID_PARAMS`，而三条用例（`test_k_out_of_range_…`、`test_empty_modes_is_rejected`、`test_bad_plan_ids_…`）会一起改判。这条依赖写进《定案三》末尾，并在 Task 6 Step 5 的 schema 注释里点名 |

#### 本轮另外查出、审查清单里没有的三处

1. **Task 3 Step 1 的 grep 门禁会假红**：它要求 `grep -rn "_format_transcript_episodes" . --include=*.py` **无输出**，但 `scriptwriter.py:220` 的 docstring 里也写着这个名字，而 Step 1 明说"函数体与 docstring 一字不动"。同时 `tests/engines/narration/test_script_input_budget.py` **确实**引用旧名 5 次（`:25,32,38,47,53`），Step 1 却写成"**若**引用了旧名"。已改成确定语气并把 docstring 那处一并改掉（与 B9 同一类）。
2. **`api/export.py` 的两处 docstring 会随 Task 8 过期**：`ExportRun`（`:53,56`）写着 `start/retry/produce → _run_export → render_export` 与"三处调用点"、"produce 路径复用 render_export"；`_submit_export`（`:76`）写着"start 与 retry 曾各写一遍这四步"。Task 8 之后调用点是 `submit`/`retry` 两处、且不再有 produce 路径。已加进 Task 8 Step 3。
3. **Task 9 Step 4 的 `useProduceJob.ts` 改写会让进度条在规划期冻在 0**，而它的 docstring 声称"进度条、文案、成功/失败提示全部沿用原样"。原实现每 1.5 s 读 `status.progress` 并 `setPercent`；改写后的 `waitJob` 把进度丢了。三模式 × K=3 的规划期是数分钟量级，冻结的进度条正是 §3.3 要消灭的静默。已给 `waitJob` 加 `onTick` 回调，两阶段都驱动 percent/stageText，并把 docstring 改成如实描述。

---

### 修订记录（2026-09-12 跨集裁决后）

**触发**：业主**拒绝**给《定案二》那次对规格 §1 的收窄签字，裁决 P-2a 就做真跨集——一条方案可以从多集取画面拼在同一条时间轴上。本节记的是这次裁决引起的全部改动、每条改动据以成立的实测/代码证据、以及它**作废**了本文件里的哪些原文。证据标准与上一节相同：每条都能被复核，不接受"看起来对"。

实测环境：活库 `data/data.db` 只读查询（1 个项目、`status='done'` **10 集**、`narration_plans` 52 行、`episode_analysis` 十行齐全）；代码基线 `9b42f24`；lint/类型读数出自本仓 `.venv/Scripts/ruff.exe`（`select = ["E","F","W","I","UP","B","SIM"]`、`line-length = 100`）与 `mypy --strict`，跑在 `D:/tmp` 的 scratch 装配上（整份 `dramaclip` 包 + 改动后的测试树），跑完已删。

| # | 改了什么 | 实测/代码证据 | 作废了本文件里的什么 |
|---|---|---|---|
| **C1** | **《定案二》末段整段重写**：从"本批次不做单条方案内跨集 + ⚠️ 须业主签字"改成"业主拒绝签字，P-2a 做真跨集"，并把原计划给推迟的三条技术理由逐条交代处置 | 规格 §1 逐字：「一次提交（剧 × 模式）→ 每模式产出 1..K 条**卖点角度互异**的**跨集**方案」——"跨集"是**方案**的定语。§4.3 卡片四要素之一是「取材集**区间**」，单集方案给不出区间 | 《定案二》的「本批次不做的事」段与整块 ⚠️ 引用；《P-2c 交接规格》整节（改成《P-2c 取消记录》）；《已知不做》里"跨集化"那条；《自查》表里没有 §1 那一行（本轮补上） |
| **C2** | **新增 Task 3c（取材层 + 六编排器跨集化）**，插在 Task 3b 与 Task 4 之间。**用 `3c` 这个后缀是有意的**：本文件已经在用 `3b`，沿用后缀可以让 Task 4–11 的编号与全部 `Task N Step M` 交叉引用一个都不用改 | `_plan_one` 在 Task 6，它消费取材层，故新任务必须排在 Task 6 之前；Task 3b 的 `top_conflict_windows` 也是它的同类（编排器**之外**的取材决定），排在一起 | 无（纯新增）。但《文件结构》的"**不动**"清单里"六个模式编排器 `modes/__init__.py`、`modes_w5.py`、`modes_w8.py`、`modes_p2.py`、`modes_w9.py`"那一条**作废**，五个文件全部移到"修改"栏 |
| **C3** | **集身份不加数据库列、不动 `ConflictScore`**，改为规划期由 `casting.stamp` 注入到一个 `ConflictScore` 的**子类** `EpisodeScene` 上 | ① `episode_analysis.conflict_scores` 是**按集一行**的 JSON（`migrations/001_init.sql:41` 逐字 `conflict_scores TEXT, -- JSON`，经 `analysis_repo.get(conn, episode_id)` 取）→ 集身份就是那一行的主键，**无需迁移、无需重跑分析**；② 加字段的代价是真的：`api/analysis.py:260` 与 `:411` 都用 `json.dumps([s.model_dump() for s in ...])` 落库，而分析层按集被调用、**不知道自己在为哪一集打分**，于是新行会带上 `episode_number: 0` / `episode_id: ""` 这种"长得像有值"的假值（正是 `loudnorm` 键名那次的失败形态），且 `api/analysis.py:290-298,319` 会把这份 JSON 原样回给前端；③ `engines/semantic/models.py` 的模块 docstring 逐字写着「落库结构对齐 docs/service/04 episode_analysis 列」 | 《定案四》第 1 点里"所以跨集排序只能在编排器**之外**做"这句**半作废**：排序确实在编排器之外定键（`casting.episode_order`），但**执行**回到编排器内部——因为六个编排器全都自己重排（见 C4） |
| **C4** | **`dict[int, list[ConflictScore]]` 这个方案被否掉**（设计问题 1 的选项 b）。改为把身份**放进场景对象**，六个编排器的排序键与盖章处一起改 | 光靠"外面排好序再喂进去"不成立：六个编排器**全都自己重排**——`modes/__init__.py:41,60`（`sorted(..., key=lambda s: s.start)`）、`modes_w5.py:31-32`（先按 `-score` 取 top6 再按 `start` 排）、`modes_w8.py:38-39`、`modes_p2.py:27-28`、`modes_w9.py:53-54`。而"排完再按 `(start,end)` 把集号贴回段上"更不行：**活库实测十集的场景起点全部从 `0.0` 开始**（ep1 前四个起点 `0.0/5.2/9.9/13.4`、ep2 `0.0/7.9/12.6/19.7`、ep3 `0.0/2.8/5.4/11.0`、ep4 `0.0/2.9/7.8/12.7`），集与集的秒轴互相覆盖，按 `(start,end)` 反查集号是**歧义**的 → 会静默把段盖成另一集，而 `export_plan` 按 `segment.episode_id` 查 `episode_paths` 查得到、只是查错了，于是不报错地出错片 | 《P-2c 交接规格》里"得让 `ConflictScore` 带上集身份、或让编排器接受『每集一组场景』"这个二选一**作废**：两条都不选，选的是第三条（子类盖章） |
| **C5** | **跨集叙事顺序定为 `(集号, 集内起点, scene_index)`**，由 `casting.episode_order` 独家持有；`casting.score_order` = `(-score, 集号, 起点, scene_index)` 同理 | 剧本驱动模式的顺序来自模型写的剧本（`build_from_script_episodes` 逐 `script.segments` 装配、`cursors: dict[int, float]` 按集各持一个游标），规则选取的场景**没有模型**，唯一不武断的顺序就是播出序；`episode_number` 已经是这个语义（`api/narration.py::_collect_episode_inputs` 逐字 `sorted(episodes, key=lambda ep: int(ep["episode_number"]))`）。次键不是洁癖：**活库实测 333 个场景只有 19 个不同分值**（最热的一档出现 45 次），只按 `-score` 排时结果稳定于输入顺序，而输入顺序来自 `episodes_repo.list_by_project`，那个顺序没有契约 | 无（纯新增）。但与 Task 3b 的 `top_conflict_windows` 排序键 `(-score, 集号, scene_index)` 是**同一条理由的两个实例**，两处都补了次键 |
| **C6** | **`_fit_duration` 的末场景预算豁免删掉**，且 `intro_first=True` 时从预算里**预留** `_INTRO_MAX_S`。门禁的时长阈值**一个字都不改** | 豁免的上界是"一个最长场景"，单集时代它是**死的**：活库实测最大的一集只有 **204.2** 场景秒 < `strategy.max_duration_s`=**300**（活库 settings 实测值），故 `used + duration > budget` 恒不成立。跨集之后两集就到 **405.8** 场景秒，豁免开始生效：活库最长单场景 **7.9s** → 最坏 **307.9s**，而门禁断言是 `duration_s > strategy.max_duration_s` 即失败。引子槽位另算：`synthesize_narration_texts` 把段 `end` 改成 `start + 实测音频时长`，ep1 的引子编排期只给 **5.17s**、实测音频 **22.48s**（由 P-1.5 实测成片 209.51s − planned 192.20s + 5.17s 反推），故四集一手 planned **298.80s** 的成片约 **313s** → **顶穿 300**。预留之后同一手 planned **269.06s**、成片约 **283.6s**，落回窗口；而 ep1 单集仍是 planned 192.20s / 成片 209.5s，与 P-1.5 实测的 **209.51s** 逐位对上（预留不改变单集行为，因为 192.20 < 270） | Task 3b 的 docstring 里"重分时长预算（`_fit_duration` 现在按 `strategy.max_duration_s` 截断单集场景）…归 P-2c"那句**作废**——重分就在本批次做完了。既有测试 `test_modes.py::test_raw_clip_opens_with_highest_conflict` 的断言消息「截断预算（**含首尾豁免**）」随之过期，改成「只有首场景豁免」（B9 同类：过期散文） |
| **C7** | **`copywriter` 的槽位台词改成按集取用**：`write_plan_copy(plan, material, …)` 的第二参从一张摊平的 `list[AsrSegment]` 换成 `casting.MaterialByEpisode`（`episode_id → 集号 + 该集台词表`），`_slot_block` 按 `segment.episode_id` 查；缺键**抛**，不退回"该区间无台词" | 这是裁决逼出来的**真缺陷**，不是整洁癖：`_slot_block` 逐字是 `[seg for seg in asr_segments if seg.start < segment.end and seg.end > segment.start]`，而区间是**集内相对秒**、十集的秒轴互相覆盖（C4 的实测数字）。单集时代这个过滤不可能错；跨集之后它**必然**把别的集的对白喂给编剧，而 system prompt 明写「情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件」→ 模型会照着错的台词写出一段通顺、可信、说的却不是这段画面的解说。不报错、不降级、成片看着正常。同类第二处：`modes_w9.strongest_line(scene, segments)` 也吃一张摊平表，金句会串集 | Task 4 的 `write_plan_copy` 签名与全部调用点（含 Step 5 那张"逐个补 `angle_block=""`"的清单）；《自查》表里"`plan_data` 无 `window` 字段这一事实被沿用（`copywriter._slot_block` 从配对段读区间，Task 4 未改）"那句**半作废**——区间仍从配对段读，但**台词**改成按集读 |
| **C8** | **`angles.select_angles` 的 `cross_episode` 形参删掉**，七个解说模式一律要"每条角度给出全部取材集（至少一个，可多个）" | 该形参存在的唯一理由是"六个模式一条片只吃一集"（`_episode_rule(False)` 逐字是「本模式一条片只取一集素材：每条角度的 `episode_numbers` 恰好一个集号」，`_sanitize` 里 `if not cross_episode and len(numbers) != 1: raise`）。裁决之后这个前提没了，留着它就是一个恒为 True 的开关 | Task 3 Step 2 的 `test_single_episode_mode_rejects_multi_episode_angle` 整条用例删除；`test_cross_episode_mode_asks_for_a_set` 改名 `test_prompt_asks_for_an_episode_set`；`test_prompt_carries_mode_k_and_transcript` 的 `assert "恰好一个集号" in prompt` 改成 `"至少一个"`；Step 4 的 `_episode_rule` 与 `_sanitize` 那条 raise 删掉；Step 6 的变异表从 **18** 行降到 **17** 行、`_sanitize` 的抛出点从 **13** 降到 **12**；R8 与《文件结构》里"18 条变异检查"的计数同步改成 17（**上一节那张表里的 18 不改，它是当时的真数**） |
| **C9** | **规则类两模式的 K 条改成"轮转发窗"**：`top_conflict_windows` 给全集排名，新增纯函数 `pipeline.deal_windows(windows, hands)` 把窗轮转发成 K 手、每手若干集，一手一条方案 | 规格 §4.3 ④ 定的是**条数**（「规则类 = 全剧 top-K 冲突窗」），§1 定的是**每条方案的形状**（「跨集方案」）：一集一条满足前者、违反后者。轮转同时满足两者，且手与手**不共集** ⇒ 取材重叠恒为 0（《定案四》第 2 点原本靠"按集去重"换来的那条性质，由"手间不共集"接着保证）。实测（scratch）：活库十集排名 `[6,7,8,2,3,4,9,10,1,5]`、K=3 → `[[2,5,6,9],[3,7,10],[1,4,8]]`，三手互不相交、每手都拿到一个高分窗。轮转而不是切块：切块会让第 1 手独占 6/7/8 三集，三条片强弱差一个量级 | 《定案四》第 2 点「按集去重，**一集一条**」改成「按集去重，**轮转发成 K 手**」；Task 3b Step 3 docstring 里"本批次做不到的那一半"整段重写；Task 6 Step 7 第 11 点的 `_rule_variants` 整函数重写；`test_rule_mode_yields_fewer_than_k_and_leaves_a_trace` 的留痕断言文案（原断 `"top-3 冲突窗" in item`）随之改 |
| **C10** | **`_CROSS_EPISODE_MODES` 改名 `_SCRIPT_DRIVEN_MODES`**，值仍是 `frozenset({"dialogue_narration"})`，但注释与它豁免 `_reject_same_episode_sibling` 的**理由换了** | 原注释逐字是「只有剧情解说能在一条方案里跨集取画面…其余模式的编排器签名是 `(episode_id, scenes, strategy)`，一条片只吃一集」——裁决之后这是**假话**。豁免仍然成立，但理由变成"它的剧本由模型按角度现写，同一组集也能写出两条压在同一段画面上的剧本"，成稿前无从判定。前置闸门的证明随之从 `(mode, episode_id)` 改成 `(mode, 取材集组合)`：`build_plan(mode, scenes, highlights, material, settings)` 五个入参没有一个来自角度名或理由 | Task 6 Step 7 第 4 点的常量与注释、第 10 点 `_reject_same_episode_sibling` 的 docstring、Step 10 变异 #14 的说明；`test_post_copy_overlap_gate_still_guards_cross_episode_modes` 的 docstring（它说"生产上 `dialogue_narration` 只剩它"——结论不变，理由要换） |
| **C11** | **`build_plan` 的死参数 `audio: AudioFeatures` 删掉**，`pipeline.parse_audio_features` 随之成为死码、一并删 | 原函数体（`pipeline.py:48-85`）**从头到尾没有一处引用 `audio`**：九个分派分支只往下传 `conflict_scores` / `highlights` / `asr_segments` / `strategy`。全仓唯一使用点是 `api/narration.py:243` 为它专门调的一次 `parse_audio_features`；`parse_audio_features` 全仓也**只有那一个调用点**（实测 grep）。在一个刚被重写的签名里留着一个没人读的 `audio` 形参，等于告诉下一个人"音频特征参与编排" | Task 6 Step 7 第 11 点 `_plan_one` 里那行 `narration_pipeline.parse_audio_features(record["audio_features"])`；`tests/engines/narration/test_modes.py:7` 的 `AudioFeatures` import 与 `:69` 的 `pipeline.build_plan(...)` 实参（少两个位置参数，照抄会 `TypeError`） |
| **C12** | **门禁新增一列 `集数` 与一个 `--require-cross-episode` 旗标**，Task 11 用它作为规格 §1 的机器判据 | 门禁今天**没有任何一条断言能区分"跨集"与"单集"**：它量时长/响度/真峰/冻结/planner/插桩覆盖，全部与集数无关。不加这一条，《完成判据》里"覆盖规格 §1"就是一句自我声明。集数从落库的 `plan_data.timeline` 直接数（`len({seg["episode_id"] for seg in timeline})`），不需要新查询 | Task 9 Step 2.4 的停机分支散文（原文「解说类模式一条片只取一集（dialogue_narration 除外）」在裁决之后是**假话**，整段重写）；Task 9 Step 2.7 的"保持不动的部分"清单（表格列宽表 `columns` 现在要动）；Task 11 Step 2/3b 的判据 |
| **C13** | **`ultra_short_hook` 明确豁免跨集**，写进 `build_ultra_short` 的 docstring 与《定案二》，不做"为跨集而跨集" | 它三个段全压在 `best = 全剧最高分场景` 上（`modes_w5.py:86-116`），是 10-20s 的单镜头悬念版。活库实测：单集 ep1 planned **14.77s**、跨集一手 planned **14.40s**、**集数恒为 1**、段数恒为 3 | 《定案二》新增一句豁免说明（原文没有，因为原文假定"六个模式都单集"）；Task 11 Step 3b 若加跑 `ultra_short_hook`，其 `集数` 列的期望值是 **1** 而不是 ≥2 |

**本轮另外查出、裁决清单里没有的四处**（都是跨集才暴露的，单集时代不可能发生）：

1. **`scene_index` 只在**一集内**唯一，`build_raw_clip` 拿它当身份用**。原代码逐字是 `if ordered[0].scene_index != best.scene_index:`（`modes/__init__.py:43`）——跨集时第 1 集的第 4 个场景与第 5 集的第 4 个场景 `scene_index` 相同，于是"开场是不是最高冲突"会判错、该前置的不前置。改成 `if ordered[0] is not best:`（身份比较），配 `test_raw_clip_best_first_swap_survives_a_scene_index_collision`（夹具刻意让两集都有一个 `scene_index=1`）。变异实测：改回按 `scene_index` 比较 → 该用例红。
2. **`build_cross` 的旁白段盖的是"上一个原声段"的集，不是锚点的集**。原代码两段都写 `episode_id=episode_id`（同一个入参，单集时无所谓），而旁白段的 `start/end` 取的是 **`anchor`**（`modes_w5.py:54,65-70`）——跨集时画面在下一集、集号写的是上一集，`export_plan` 会去**上一集的同一秒**切画面。改成 `episode_id=anchor.episode_id`，配 `test_cross_narration_segment_carries_the_anchor_episode`。变异实测：改回 `scene.episode_id` → 该用例红。
3. **`max(scenes, key=lambda s: s.score)` 在同分时取输入顺序的第一个**（`modes_w5.py:86`）。单集时输入顺序来自一份 JSON，稳定；跨集时输入顺序来自 `episodes_repo.list_by_project`，**没有契约**，于是"整组重规划两次取到不同的集"。活库实测 333 个场景只有 19 个不同分值，同分是常态不是边角。改成 `min(scenes, key=casting.score_order)`，配 `test_ultra_short_breaks_a_cross_episode_score_tie_by_episode_number`（夹具把 ep2 排在输入第一位、两集同为 95 分）。变异实测：改回 `max(key=score)` → 该用例红。
4. **预算会在后面的集拿到任何画面之前就被吃光**，于是"取材集"会缩水。活库实测 `intro_narration` 一手四集 `[2,5,6,9]`：planned 269.06s，但时间轴上**只出现 2 集**（ep2、ep5），ep6/ep9 一帧都没有——因为 `_fit_duration` 按播出序填充、预算 270s 在 ep5 就用完了。这不是缺陷（`intro_narration` 本来就没有场景条数上限，与其余五个模式的 `_MAX_SCENES` 不同），但**落库的 `episode_ids` 必须从建好的时间轴反推**，不能抄角度点名的那份，否则卡片的「取材集区间」会列两集没出现的集（§9.5 假文案类）。`script_driver.script_dialogue_plan` 早就是这么做的（`used_ids = sorted({seg.episode_id for seg in plan.timeline})`），`_plan_one` 沿用同一口径，配 Task 6 的 `test_episode_ids_come_from_the_timeline_not_the_brief`。

---

**Task 6–11 审计轮（2026-09-12，接 C13 之后）**：上一轮的重构代理在写 Task 6 时中断，Task 6 只改了一半、Task 7–11 与全部尾部章节（《P-2c 交接规格》/《完成判据》/《已知不做》/《自查》）一字未动，而**当时**顶部那条 ⚠️ 横幅（"Task 6 及之后不得直接执行"，本轮已改写成 ✅）声称《P-2c 取消记录》已经存在——**它当时不存在**。下面每条都附证据；实测口径与上一轮相同（活库 `data/data.db` 只读聚合查询、代码基线 `9b42f24`、`scripts/verify_modes.py` 与 `api/*.py` 逐行读）。

| # | 改了什么 | 实测/代码证据 | 作废了本文件里的什么 |
|---|---|---|---|
| **C14** | **Task 6 Step 10 的变异表修三行、补两行**：#10 的破坏对象从 `_pick_episode`（已不存在）改成 `_casting_for` 的 `if missing: raise`；#12 从 `if len(windows) < k:` 改成 `if len(hands) < k:`；#14 从 `_CROSS_EPISODE_MODES` 改成 `_SCRIPT_DRIVEN_MODES` 并按 C10 换掉理由；新增 **#10b**（`record is None` 那条 raise）与 **#16**（`used_ids` 从时间轴反推 + "某集没有冲突场景"的留痕） | `_pick_episode` 在 Task 6 Step 7 第 11 点已被 `_casting_for` 取代（全文再无定义）；`_rule_variants` 的判据是 `len(hands) < k`（C9 的轮转发窗之后 `windows` 是集排名、`hands` 才是条数）；**《定案二》的失败模式表逐字把 #10b 与 #16 登记在"Task 6 Step 10"名下，而那张表里两行都不存在**——一条被承诺的变异检查不存在，比没有变异检查更坏（读的人以为它被测着） | Step 10 的 #10/#12/#14 三行原文；《定案二》失败模式表第 2、3 行的落点从"承诺"变成"已兑现" |
| **C15** | **`test_rule_mode_yields_fewer_than_k_and_leaves_a_trace` 整条重写**：docstring 从"top-3 窗按集去重后只剩 1 条"改成"轮转发窗只够 1 手"，留痕断言从 `"top-3 冲突窗" in item and "1 集" in item` 改成 `"轮转发窗只够 1 手"` + `"其中 1 手只取到一集"` **两条** | `_rule_variants` 实际打的两句是「全剧只有 N 集带冲突窗，**轮转发窗只够** M 手，本模式出 M 条」与「…不足 2×K 集，**其中 T 手只取到一集**…」，**两句里都没有"top-3 冲突窗"这个串**，也没有裸的"1 集"（是"只够 1 手"）。照旧断言跑 ⇒ 用例**必红**，而它是 Task 6 Step 8 的"Expected: PASS"里的一条 | C9 那行末尾"`test_rule_mode_yields_fewer_than_k_and_leaves_a_trace` 的留痕断言文案随之改"从**待办**变成**已做**（上一轮记了要做、没做） |
| **C16** | **Task 6 Step 3 补两条用例**：`test_named_episode_without_an_analysis_row_fails_only_that_variant`（桩掉选题、让 `analysis_repo.get` 对第 2 集回 `None`，断言只有角度2 失败且错误串点名到集号）与 `test_episode_ids_come_from_the_timeline_not_the_brief`（把第 2 集的 `conflict_scores` 重种成 `[]`，断言 `episode_ids` 只含第 1 集 + 有留痕） | 两条分别守 `_casting_for` 的 `record is None` raise 与 `_plan_one` 的 `used_ids = sorted({segment.episode_id for segment in plan.timeline})`；**没有它们，C14 新增的 #10b/#16 两行变异就是"红不了"的**（本仓已经为三条红不了的变异检查付过账）。夹具用 `analysis_repo.upsert`（实测 `repos/analysis.py:11-41`，`ON CONFLICT(episode_id) DO UPDATE` 整行覆盖）重种一集，不需要新助手 | Task 6 Step 4/Step 8 的用例计数（16 条/18 项 → **18 条/20 项**）；Step 4 的 `-k` 片段清单（14 → 17 个，原先**漏了 `cancel_releases`**，那条用例在 Step 8 之前从没被跑过一眼，而 Step 8 的 Expected 把它算进了通过数） |
| **C17** | **Task 7 补一条跨集用例 + 把两个"核对过、不用改"的结论连同证据写进任务开头**：`test_get_plan_exposes_the_episodes_a_plan_spans`（两集一条方案：`episode_ids` 与时间轴上的集**逐字相等**、分组不丢段、无零长区间、`cost == {"copy_llm_calls": 1, "tts_calls": 6}` **字面整数**）；Step 3 补变异 **#2b**（把 `copy_llm_calls` 改成按集数计 → 该用例红） | ① 返回体**已经**够拼「取材集区间」：`episode_ids` 由 `_row_to_dict` `json.loads` 成 `list[str]`（`repos/plans.py:20-24`），逐段区间在 `plan_data.timeline[*]`；集号不在返回体里是有意的——`project.get` 已给 `Episode.episode_number`（`protocol/schemas/project.json:49-88`），再抄一份就是 docs/04 §5.2 的双处定义。② `plan_cost` 与集数无关：`write_plan_copy` 把全部槽位拼进**一个** prompt（`copywriter.py:114-121`），它的循环是 `for _ in range(_ATTEMPTS)`（重试，`:125-133`）；剧本链同理（`scriptwriter.py:227-241`）。断言用字面整数是 B6 的教训（`len(plan.narration_texts)` 是把实现的公式又算一遍） | Task 7 Step 2 的"PASS（4 条）"→ **5 条**；Step 3 的变异表从 4 行到 6 行 |
| **C18** | **Task 8 补两条跨集用例 + 把"守卫不查源文件"的依据写进用例 docstring**：`test_submit_accepts_a_plan_spanning_two_episodes`、`test_submit_rejects_an_unvoiced_slot_in_the_second_episode`（第二集的 ducked 槽位没配音 → 必须 `rejected` 且理由点名 `ep2`）；`_seed_plan` 的 `episode_ids` 从写死 `["ep1"]` 改成从时间轴反推；Step 8 补变异 **#10**（守卫的配音遍历加一行"只查第一集"）与 **#11**（覆盖边界，登记为"本文件不红"）；Step 4 末尾补 `serial_per_episode` 归 P-2.5 的两句话 | **守卫不需要自己查源文件，核过两处**：`render_export` 的 `episode_paths` 取自 `episodes_repo.list_by_project(conn, project_id)`——项目**全部**集（`api/export.py:216-219`），`dialogue_zones` 逐段按 `segment.episode_id` 预取（`:223-237`）；而 `encoder.export_plan` 对**每一段**做 `episode_paths.get(...)`，缺就抛 `EpisodeSourceMissing(f"第 {…} 集源文件缺失")`（`encoder.py:360-362`）——逐段查、点名到集，且它跑在**渲染那一刻**，比提交时 stat 一遍更靠得住。变异 #10 是本轮最重要的一条：**它在单集夹具上是死代码，11 条既有用例一条都不红**，而它放出去的是"前半段有解说、后半段静默"的片（§3.3.1 禁止级） | Step 2 的 Expected（补上"12 条/14 项"与 `retry` 那条的红法）；Step 7 的 Expected；Step 8 从 9 行到 11 行；`test_export_submit.py` 的模块 docstring 从"钉三件事"到"钉四件事" |
| **C19** | **Task 9 Step 2 从七个改动点补到八个**：2.4 的停机分支散文按 C12 整段重写（并补 `--require-cross-episode` 需要 ≥2 集这第二条前置）；2.6 的附注行加"逐条取材集数"；2.7 的"保持不动"清单**收窄**（`_mode_table_drift` 与 `columns`/`values` 现在要动）；**新增 2.8**（`SINGLE_EPISODE_MODES` + 它的子集核对 + `集数` 列 + 跨集断言 + 门禁阈值逐条重新推导表）；2.2 的 batch 查询改成一次取 `id, plan_data`（集数由此推出，不再二次查同一个 batch）；2.3 从两个旗标到三个；Files 行从"五处"到"八处"；"原 8 行"改成实测的 **7** 行 | 2.4 的原文「解说类模式一条片只取一集（`dialogue_narration` 除外）」在裁决之后是**假话**（C12 点名要重写，上一轮没做）；`_mode_table_drift` 的既有纪律逐字是"手抄清单必须与 `SUPPORTED_MODES` 对账，否则新模式会按默认值悄悄判绿"（`:322-328`），而 `SINGLE_EPISODE_MODES` 正是一份手抄子集——写错一个名字就让 §1 的判据对那个模式**永远不判**；`:638` 是 `zip(values, columns, strict=True)`，两表不同长会当场 `ValueError`（这是本文件里少数"改错就响"的地方）；`:459-465` 实测是 7 行不是 8 行 | 2.4 的整段散文；2.7 那句「`_mode_table_drift()`、响度窗口、planner 断言、冻结帧断言全部不动」里的**第一项**（其余三项仍然不动）；Files 行的"五处"；C12 那行末尾"Task 9 Step 2.4/2.7、Task 11 Step 2/3b 的判据"从**待办**变成**已做** |
| **C20** | **门禁阈值逐条重新推导，写进 Task 9 Step 2.8 的表**（`EXPECT_PLANNER`、`EXPECT_NARRATION`、时长、响度窗、真峰门限、冻结帧、插桩覆盖各一行，每行给"不用改因为 Y"的代码或实测依据）。**结论：七个阈值一个字都不改** | 响度：Phase C 归一的是**整片**，P-1.5 九部真成片全部落在 −14.0/−14.1 LUFS，**最大偏差 0.1 LU** 对容差 **2.5 LU**。真峰：段级天花板挂在每段 `atempo` 之后（`encoder.py:263`）、混音限幅挂在 `amix` 之后，都是**逐段**；实测 −2.20…−5.20 dBTP 对门限 −1.00，**最小余量 1.20 dB**。冻结：跨集只增加硬切点，实测九部全 **0.0s** 对门限 2.0s。planner/旁白段数：都由**模式族**决定，不读集数（`pipeline.py:173`、`copywriter.py:147`、`PlanData.planner` 默认 `"rule"` 在 `models.py:60`）。插桩覆盖：**它不是跨集正确性的守卫**——盖错集号时段数照样对得上，这一条已在表里写明，免得下一个人拿它当证据 | C6 那句「门禁的时长阈值一个字都不改」与《定案二》第 ③ 行「逐条推导与实测数字见 Task 9 Step 2.8」——**Step 2.8 原先不存在**，两处引用都悬空；现在兑现了 |
| **C21** | **新查出一条 C6 没算到的时长顶穿，并把它交出去而不是就地拍板**：`raw_clip` 在 `--variants 1` 下 planned **296.21s**、成片预估 **≈303.0s** > 门禁的 **300s**。修法（给 `_fit_duration` 的预算留编码漂移余量）落在 Task 3c，**余量取多少是设计决定，本轮不替业主拍**；改为记进《开放问题》#5 +《完成判据》#10（收口前必须"改"或"明确接受并登记"，不许既不改也不记），并把 Task 11 Step 3b 的 `raw_clip` 那一跑挪到 `--variants 3`（一手四集，planned 117.89s）、另加 Step 3d 用**只算不渲**的脚本把这个数交给业主 | 机制：`deal_windows(windows, hands=1)` → `min(1, len(windows))` = **1 手**、逐窗 `dealt[rank % 1]` ⇒ K=1 时一手装**全部**集（`--variants 1` 正是门禁默认口径）。活库只读实测：十集 **333** 场景，合格（分数 ≥ `RAW_CLIP_MIN_SCORE`=70 且 3-25s）**59** 个、合计 **346.5** 场景秒 > 预算 **300** ⇒ 吃满，**51 段 / 296.21s / 覆盖 9 集**（ep10 一帧没有）。成片漂移比值取自 P-1.5 实测：`raw_clip` 15.48/15.13 = **1.0231**、`subtitle_flow` 32.43/30.57 = **1.0609** ⇒ 303.0s（保守 314.3s）。**这套重算的可信度**：它在五个独立点上与 Task 3c Step 8 那张实测表逐位对上（ep1 `raw_clip` 15.13/3 段、四集一手 117.89/21 段/4 集、`subtitle_flow` 36.24/7 段/3 集、窗排名 `[6,7,8,2,3,4,9,10,1,5]`、`intro_narration` 269.06）。单集时代不可能发生：ep1 合格场景只有 **15.1s**，差 20 倍 | Task 11 Step 3b 原来"`dialogue_narration,raw_clip --variants 1`"那一跑（会撞这条红）；《完成判据》原 8 条（补 #9 跨集机器判据、#10 本条的处置） |
| **C22** | **Task 10 从三份文档扩到五份**：新增 `docs/service/02-引擎设计.md`（`:59` 的 `copywriter.py` 行写着 `slot` / `window` 两个**早已不存在**的字段名）与规格本身（§3.3.1 降级裁决表 `:126` 的「位置」列点名 `api/narration._generate_one`，Task 6 删掉它）；Step 4 补两点（`docs/service/04:247-250` 的 `jobs.type` 注记被本批次**同时**过期两次；`narration_plans` 那节写明"跨集不加列"）；Step 7 的 `git add` 与提交信息随之扩 | `docs/service/02:59` 逐字是「编排器只产出槽位（`slot` 职责 + `window` 素材区间）」，而 P-1.5《实现定案修正》定的字段是 `brief`、`window` **已删**——pydantic **静默忽略未知 kwargs**，照这行写代码不报错、只丢数据，正是本仓付过两次账的那类"编造出来的规格"；该表 `:40` 的免责句只管"未建条目"，管不到"已建条目写错字段名"。规格 `:126` 是全 `docs/`（除计划目录）里**唯一**一处 `_generate_one` 命中，实测 `grep -rn "_generate_one\|_run_produce\|_newest_ready_plan\|_run_generation_parallel" docs/ --include=*.md | grep -v superpowers/plans` 只回这一行。`docs/service/04:247-250` 同时写着"`produce`（`narration.produce`）"与"`jobs.json` 同样漏了 `semantic`"，前者随 Task 6 失效、后者随 Task 9 Step 3 修掉。迁移号实测最高仍是 `009_ocr_segments.sql`（`ls migrations/` = 9 个文件），故 `010` 未被占用、`docs/04:305` 的"实测 8 个文件"确实过期 | Task 10 的 Files 清单（3 → 5 份）与 Step 7 的 `git add`；Step 4 从 3 点到 5 点；《自查》第 4 项的清单 |
| **C23** | **尾部四节全部按裁决重写**：《P-2b / P-2c 交接规格》→《P-2b 交接规格 / P-2c 取消记录》（P-2c 那一节整节替换成一张"原待办 → 落在哪 → 状态"的对账表，并说明为什么保留记录而不是删掉）；**新建《开放问题》一节**（#1–#5）；《已知不做》改两条（`serial_per_episode` 从"规格自相矛盾、等裁决"改成"`4228bef` 已裁决、归 P-2.5"；磁盘回收那条的 `work_dir/tts/<job>/…` 路径层级已随 Task 5 删除）+ 补一条（规则类重掷留痕无用例，Step 10 #15 承诺登记在此）；《自查》补 §1 / §4.2 / §4.3 ④ / §5 #21 / §3.3 留痕 五行、修 `narration_id` 那行被 C7 半作废的"Task 4 未改"、第 3 项按裁决后的签名整段重写（`_pick_episode`/`cross_episode`/`_voice(…, job_id, mode, index)`/`_plan_one(…, brief)` 四处作废，补 `casting.*`、`build_plan` 新签名、`deal_windows`、`_Variant`/`_OverlapHit`、门禁新名字）；《完成判据》#6 补 `--include=*.mjs` 并把 Expected 从"无输出"改成"三处零命中 + `scripts` 下恰好两条" | **《开放问题》这一节原先根本不存在**，而正文有**五处**点名到它（R2、R3、《定案二》末段、《定案四》末段两处、Task 3b Step 3 的 docstring）——悬空引用与悬空指针同类：读的人会以为答案在别处。《完成判据》#6 的 grep 实测**没有** `--include=*.mjs` 而 Expected 写着"无输出"，可 `scripts/verify_e2e.mjs:152,168` 是两条永久命中 ⇒ 那是一条**永远红的门禁**，正是 R6 说要同步、B9 说比没有门禁更坏的那种（教会执行者"这条不用看"）。顶部横幅声称《P-2c 取消记录》已存在——实测 `grep -n "P-2c" 本文件` 在改写前**九处命中里没有一处是取消记录**，`:6959` 那节标题仍是《P-2c：单条方案内的跨集拼接》，正文仍写着"P-2a 让角度之间跨集，但六个单集模式的单条方案内仍限于一集" | 《P-2c 交接规格》整节（C1 点名要改成取消记录，上一轮没做）；R2/R3 两行末尾"并进《开放问题》#1/#2"从**待办**变成**已兑现**；《自查》表里没有 §1/§4.2/§4.3 ④ 三行（C1 与 R1 各点名过一次）；《已知不做》的 `serial_per_episode` 条与 `work_dir/tts/<job>/…` 那条路径 |

---

## 范围裁决：P-2 拆成 P-2a（本计划）与 P-2b

规格 §6 的 P-2 行标题本身就是两件事：**「规划/渲染解耦 + 剧库」**。它们不共享任何代码——前者动 `api/narration.py` / `api/export.py` / `engines/narration/` / `narration_plans` 表，后者动 `api/project.py` / `repos/projects.py` / `projects`+`episodes`+`episode_analysis`+`jobs` 四表联查。合成一份计划会得到 14 个任务、两个互不相干的验收面，以及"改剧库时必须重跑规划全套测试"的执行负担。故拆开：

| 计划 | 规格 §6 的 P-2 五项 | 出口 |
|---|---|---|
| **P-2a（本计划）** | ① `produce` → `plan_variants` + `export.submit`；② `narration.get_plan`；③ 角度重叠度量 | 阶段③ 能只看方案不渲染；一个模式的 K 条方案取材重叠全部 ≤60% |
| **P-2b（下一份计划，本文件末尾给交接规格）** | ④ `project.batch_create`；⑤ `project.list` 阶段聚合 | 批量建项目与阶段定位可用 |

拆分不破坏规格给 P-2 定的出口判据，只是按那个「+」号切成两半分别验收。**第 ① 项（`produce` 拆分）在本计划里，且是 Task 6/8/9 的主干**——②③ 都挂在它上面（`get_plan` 读的是 `plan_variants` 写的行，重叠度量是 `plan_variants` 的出片闸门），顺序不可颠倒。

P-2b 不需要新迁移、不碰 `engines/narration/`、不碰 `protocol/schemas/narration.json`；它碰的 `protocol/schemas/project.json`、`protocol/ts/index.ts`、`docs/03`、`docs/service/01`、`docs/service/04` 与本计划有重叠，**故 P-2b 必须在 P-2a 合入之后再开工**（详见末尾《P-2b 交接规格》的冲突面清单）。

---

## 开工前置（硬门禁，不满足就不要开始 Task 1）

- [ ] **Step 0.1: 确认 P-1.5 已收口**

Run: `cd /d/PersonProjects/DramaClip && git log --oneline -3 && git status --short`

Expected: 工作区干净（或只有另一位工程师的 `scripts/verify_e2e.mjs` / `scratch/`），且 P-1.5 的 Task 10（真机九模式复验）已提交。**本计划 Task 9 会改写 `scripts/verify_modes.py` 的提交入口**——门禁脚本正在跑、或 P-1.5 出口未闭环时动它，等于把上一批的验收证据抽掉。

- [ ] **Step 0.2: 确认没有门禁在跑**

Run: `tasklist //FI "IMAGENAME eq python.exe" 2>/dev/null | head -5`

Expected: 没有正在跑 `verify_modes.py` 的 python 进程。本计划全程不跑 ffmpeg 渲染门禁（Task 11 除外，且它只跑两个模式）。

- [ ] **Step 0.3: 确认迁移号未被占用**

Run: `ls service/dramaclip/infra/storage/migrations/`

Expected: 最高是 `009_ocr_segments.sql`（另一位工程师的 OCR 通道）。**本计划用 `010`。** 若此时已出现 `010_*`，停下并改用 `011`，同时把 Task 1 里所有 `010_plan_angles.sql` 字面量与 `tests/infra/storage/test_db.py` 白名单一并改成新号——上一批就撞过一次号。

- [ ] **Step 0.4: 基线全绿**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -5`

Expected: 除 `tests/api/test_analysis.py` 的既有隔离 flake 外全绿。那条 flake 属另一位工程师（`tests/api/test_analysis.py` 是他的文件），**本计划不修它、不碰它**。

Run: `cd service && ../.venv/Scripts/ruff.exe check . && ../.venv/Scripts/mypy.exe dramaclip`

Expected: 两条都无输出、退出码 0。

**提交纪律（贯穿全计划）**：只 `git add` 显式路径，**禁止 `git add -A` / `git add .` / `git commit -a`**。同树同分支另有工程师在提交（OCR 字幕通道：`scripts/verify_e2e.mjs`、`scratch/`、`tests/api/test_analysis.py`、`tests/engines/analysis/*`、`hotwords.py`、`docs/07-*`），宽 add 会卷走他的暂存。

**`data/data.db` 是活库**：只读、含明文 API key、绝不打印其内容。Task 11 的真机复验跑隔离副本（`verify_modes.py` 自己建），不写活库。

---

## 四处设计定案（实施前先读，代码里的注释都指回这里）

### 定案一：配音归规划侧，不归 `export.submit`

**位置**：`plan_variants` 内部配音；`export.submit` 只渲染。

**代码依据**：

1. `render_export`（`service/dramaclip/api/export.py:193-277`）从头到尾只做一件事——读传进来的 `run.plan_data` 渲染。它不合成任何音频。
2. 旁白音频的唯一来源是 `tts_audio_by_segment`（`api/export.py:165-179`），它按 `segment.narration_id` 取 `text.audio_path`。
3. `audio_path` 全仓只有一处写入：`pipeline.synthesize_narration_texts`（`engines/narration/pipeline.py`，函数体实测 `:250-303`）——它算出内容寻址路径（`:273`）、回填 `NarrationText.audio_path`（`:296` 的 `model_copy`）。同一个函数还改写 `segment["end"] = start + duration`（`:292`）与 `segment["subtitle_text"] = text`（`:293`）。**行号会随该文件漂移，认函数名**：`9b42f24` 一次提交就让它整体下移了约 40 行，本计划原先引的 `:249/:250/:251-256` 全部作废。
4. 于是：**一条没配过音的方案行渲染出来，是一部没有解说声、也没有解说字幕的哑片，而且静默**——`api/export.py:260` 的 `tts_segments or None` 把空映射直接变成 `None`，编码器认为这条片本来就没有旁白。这正是规格 §3.3.1 禁止级「半条旁白的片子不可交付」。
5. `export.retry`（`api/export.py:124-152`）的幂等设计前提是"方案行是完整且不变的输入"：它重读同一行、复用同一个 `export_id`、只重跑渲染。若配音在 submit 侧，retry 就必须决定"要不要再配一次音"——要么重配（同一 `export_id` 两次配音、成本翻倍且结果可能不同），要么读一行没有音频的 plan（回到第 4 条）。两条都毁掉 P-1 好不容易做出来的幂等契约。

**后果（必须认）**：

- **一条 `status='ready'` 的方案行就是可渲染的成品输入**，`export.submit` 不需要任何规划知识。这是拆分能成立的根本原因。
- **`work_dir` 从缓存变成承重存储**。配音音频落在 `<data>/cache/analysis/tts/…`，而方案可能几小时后、几次重启后才被提交渲染。全仓没有任何路径清理 `work_dir`（`shutil.rmtree` 只出现在 `api/models.py:119`，删的是模型目录），所以今天它是"事实上永久"的；本批次把这个事实**变成契约**并写进注释。磁盘增长归 P-3 的「关于 → 本地数据」与回收站，不在本批。
- **音频文件现在可以被两条方案共用，所以回收站不能按作业删**。`9b42f24` 把文件名改成内容寻址（`{slot_id}-{sha1(text|voice|engine)[:12]}.mp3`），于是**文案相同的两条方案指向同一个文件**——这是有意的（缓存优先、不二次付费），但它把"一个作业一个目录"这个直觉彻底废掉了：按创建时间或按创建作业删除，会静默作废另一条老方案的 `audio_path`。好消息是它不会静默出坏片：Task 8 的 `_assert_renderable` 会 `is_file()` 一次，丢了就当场 `rejected` 并给出「配音音频已丢失」。坏消息是**回收站的设计模型必须换**——详见末尾《P-3 交接规格》第 1 条，那里同时记了修复代理点出的残余（摘要不覆盖模型权重）。
- **重掷一条角度要重付它的配音成本**。规格 §6 承诺的是"不付**渲染**成本"，配音比渲染便宜一个量级；且 §4.3 ④ 的默认路径是 K 条全渲染，所以默认流程下一条都不浪费。

### 定案二：K 条角度怎么才真的互异

**（本定案只适用于解说类七模式；`raw_clip`/`subtitle_flow` 的 K 条另有来源，见《定案四》。）**

**角度由 LLM 选，一模式一次调用（不是一条角度一次）。** 规格 §4.3 定案「用户不能挑角度，角度归模型」，§4.4 的成本预估卡按「LLM 成稿次数」计账——若选题按变体付，成本账就变成 `k × 2` 次成稿，与 §4.4 的口径不符。所以：**每模式 1 次选题调用 + 每条方案 1 次成稿调用（`copywriter`，`dialogue_narration` 走 `scriptwriter`）+ 每条方案 N 次配音**。选题是模式级固定开销，一个 batch 的选题次数 = 该 batch 里不同模式的数量，可由 `narration_plans` 的 `batch_id` + `DISTINCT narration_mode` 直接数出，不落库。

**成本账有一处必须如实交代的口径差（R7）**：成稿发生在重叠闸门之前，所以**被拦掉的角度也付了一次成稿**，而它不落库 → 这笔钱在 `narration_plans` 里无从重算，`plan_cost()` 逐条相加得到的是"落库方案的成稿数"，**不是"这个 batch 真花掉的成稿数"**。分两半处置：

- **可判定的那一半已经前置**：同模式同集的两条角度，其时间轴是 `(mode, episode_id)` 的纯函数——`_plan_one` 的非剧情解说分支里 `brief` 只进 `copywriter` 的 `angle_block`，**不进 `build_plan`**（`build_plan(mode, episode_id, conflicts, highlights, asr, audio, settings)` 的七个入参没有一个来自角度）。所以"同集 ⇒ 取材逐秒相同 ⇒ 重叠 100%"在成稿**之前**就是可证的，Task 6 Step 7 第 11 点把它做成一道前置闸门，被拦的角度一次成稿都不付。
- **不可判定的那一半留在原地并写明**：`dialogue_narration` 的剧本由模型按角度现写（`script_driver.script_dialogue_plan`），成稿前无从知道两条剧本会不会压在几乎同一段画面上，只能事后量。这条残余写进 `plan_cost` 的 docstring，谁读那张成本卡都能知道它是"落库口径"而不是"花销口径"。

**互异靠两条腿，缺一不可**：

1. **选题时把"互异"写成模型的硬约束，并让它交出可核对的证据**：每条角度必须给 `name`（角度名）/ `reason`（为什么这条值得单出一条片）/ `hook`（开场钩子首句）/ `episode_numbers`（取材集）。`angles._sanitize` 逐条验收：少一条、名字重复、字段为空、集号不存在、被排除的角度又提出来——**一律抛，绝不拿残缺的凑数**（凑数就是 §3.3.1 禁止级「假装有 K 条」）。
2. **出片前量一次取材重叠，超阈值当场不出**（规格 §4.3：阈值 60%）。这是防"K 变成老虎机"的安全阀，也是唯一能证伪模型自称互异的客观度量。

**重叠度量：量什么、在什么单位上量、阈值什么意思**

- **量取材（时间窗），不量文案。** 规格 §4.3 的用词是「角度间**取材**重叠率」，卡片四要素里对应的是「取材集区间」。文案重叠是另一个问题（同一批画面配不同解说词其实是合法的差异化手段），并进同一个数会让阈值失去意义。
- **单位是"源素材秒"，不是场景条数。** 段长不等：按条数会把"共用两个 25 秒长镜"算得比"共用五个 3 秒短镜"还轻，而观感上恰恰相反。
- **算法是 Jaccard：`共用秒数 / 两者并集秒数`。** 不用包含率（`交集 / 较短一方`）：包含率会把"一条 20 秒短片完全落在一条 100 秒长片里"报成 100%，而那条短片只占长片五分之一——真正要拦的是"两条看起来是同一部片"，Jaccard 量的正是这个。并集为 0（两条都没画面）时回 `0.0`：无素材可比重，不该判成同一部片。
- **只读 `plan_data.timeline` 的 `episode_id` / `start` / `end` 三个字段**，不读 `audio` 角色：`original` / `narration` / `ducked` 三种角色占的是同一段源画面，取材就是取材。**每集内先合并区间再算**：编排器会产出首尾相接的段（`full_narration` 逐场景、`dialogue_narration` 逐句吸附），不合并会把同一秒数出两次，重叠率能超过 1.0。
- **阈值语义**：候选角度与**同一模式内已接受的兄弟方案**逐条比，取最大值 `overlap_max`；`overlap_max > 0.60` 即抛错、这条角度不落库，其余角度不受影响（失败粒度=单条方案）。`overlap_max` 落库，因为**被拦掉的角度不留行**，事后无从重算当时那个数——存下来才有审计链。

**本批次做的事（2026-09-12 业主裁决后改写，见下）**：一条方案内跨集拼画面。规格 §1 的原话是「一次提交（剧 × 模式）→ 每模式产出 1..K 条**卖点角度互异**的**跨集**方案」——**跨集写在方案的定义里**，不是写在批次之间的比较里。本定案原先把它收窄成"角度之间跨集、单条方案内仍限一集"，并把真正的跨集拼接推给一个假想的 P-2c、标注"须业主签字"。

> ✅ **业主拒绝签字。裁决：P-2a 就做真跨集——一条方案可以从多集取画面拼在同一条时间轴上。**
>
> 于是原先的推迟作废，P-2c 不再存在（末尾那一节已改成《P-2c 取消记录》）。原计划给推迟的三条技术理由都是真的，逐条交代它们现在怎么了——**这三条正是本轮全部新增工作的来源**：

| 原推迟理由（都是事实） | 裁决之后怎么办 | 落在哪 |
|---|---|---|
| ① 只有 `dialogue_narration` 能跨集拼（`pipeline.build_from_script_episodes` 按集号取素材），其余六个编排器签名是 `(episode_id, scenes, strategy)`，一条片只吃一集 | **给场景盖上集身份**：新增取材层 `engines/narration/casting.py`，六个编排器的第一个入参从 `episode_id: str` 换成 `scenes: list[EpisodeScene]`，段的 `episode_id` 由**每个场景自己**带。渲染侧一行不用改（见下面"渲染侧本来就跨集"那条证据） | **Task 3c** |
| ② `ConflictScore`（`engines/semantic/models.py`）只有 `scene_index/start/end/score/reason`，**不带集身份**，所以跨集排序只能在编排器之外做 | **不动 `ConflictScore`、不加数据库列**：集身份是**规划期注入**的，因为 `episode_analysis.conflict_scores` 本来就是**按集一行**的 JSON，集身份就是那一行的主键。`casting.stamp` 在解析时盖章，活库已有的十集分析结果一行都不用改、不用重跑分析、不需要任何迁移 | **Task 3c Step 1/3** |
| ③ 九模式门禁的时长/响度/冻结窗正压在现有单集成片形态上 | **响度与冻结窗不受影响**（Phase C 归一的是整片、段级天花板与格式滤镜逐段作用、`dialogue_narration` 早就出多集成片并且实测过门）；**时长窗会被顶穿，故改的是代码不是阈值**——`_fit_duration` 的末场景预算豁免与 `intro_narration` 的引子槽位余量。逐条推导与实测数字见 Task 9 Step 2.8 | **Task 3c Step 4 + Task 9 Step 2.8** |

**渲染侧本来就跨集，这是"改动只在规划侧"的静态证据**（三处，逐一核过）：

1. `TimelineSegment.episode_id` **逐段存在**（`engines/narration/models.py`），所以一条多集时间轴今天就能表示，模型一行不用改；
2. `api/export.py::render_export` 的 `episode_paths` 取自 `episodes_repo.list_by_project(conn, project_id)`——项目**全部**集，不是方案点名的那几集；`dialogue_zones` 逐段按 `segment.episode_id` 预取；
3. `engines/exporter/encoder.py::export_plan` 逐段 `episode_paths.get(segment.episode_id)` 取源、`zones_cache` 按 `episode_id` 分键；`overlap.source_spans` 也是按 `episode_id` 分组合并区间的（Task 2 的 `test_same_seconds_in_different_episodes_do_not_overlap` 已经钉住"第 3 集的 0-10s 与第 7 集的 0-10s 是两段不同画面"）。

生产上已经有多集成片在跑：`dialogue_narration` 走 `build_from_script_episodes`，P-1.5 Task 10 的九模式实测表里它那一行是 **56.10s / −14.1 LUFS / −2.20 dBTP / 冻结 0.0s / 段 7 插桩 7**——**同一套门禁、同一组阈值、全过**。所以《文件结构》的"不动"清单继续覆盖 `engines/exporter/*` 与 `api/export.py` 的渲染路径。

**§1 的"跨集"到底要求什么（本定案的读法，写下来备查）**：要求的是**一条方案的时间轴含来自多集的段**，不是"一个旁白槽位横跨两集"。后者不可能：一个槽位压在一段源画面上（`NarrationText` 没有区间字段，区间由配对段的 `start/end` 给出，P-1.5《实现定案修正》定的），而一段源画面只能来自一个源文件、按 `-ss/-to` 从那一集切。所以"跨集"= 一条解说弧的**若干个槽位分别落在不同集**，成片在集与集之间硬切。六个规则编排器改完之后就是这个形状（`full_narration` 活库实测一手 4 集 → 8 个槽位落在 3 集上，见 Task 3c Step 7 的实测表）。**唯一例外是 `ultra_short_hook`**：它三个段压在同一个场景上（`modes_w5.build_ultra_short` 的 `best`），是 15 秒的单镜头悬念版，跨集只会毁掉它全部的卖点，故它恒为一集——但"哪一集"现在是**全剧**最高分那一集，不再是 `episodes[0]`。§1 要的是一条方案**可以**跨集取画面，不是每条方案**必须** ≥2 集。

**跨集之后新长出来的四条失败模式，逐条给处置**（失败粒度仍是单条方案，`_run_plan_variants` 的内层 try/except 一条不变；每一条新的拒绝分支都配了变异检查，见 Task 3c Step 6 与 Task 6 Step 10）：

| 新的失败形态 | 处置 | 变异检查 |
|---|---|---|
| 角度点名的集**不在**已完成分析的集里 | `_casting_for` 一次点名**全部**缺号再抛（逐个抛会让第一条掩盖其余的，运维补完一集再跑又炸一集）。绝不悄悄换一集顶上 | Task 6 Step 10 #10 |
| 角度点名的集**没有 `episode_analysis` 行** | 同上，抛错点名到集号（「第 N 集分析记录缺失（本条方案点名要取它）」） | Task 6 Step 10 #10b |
| 点名的集**分析过但一个冲突场景都没出** | 不抛——其余集照样能出片。但必须 `notifier.log` 留痕（规格 §3.3），且落库的 `episode_ids` **从建好的时间轴反推**，不抄角度点名的那份，否则卡片的「取材集区间」会列一集一帧都没出现的集（§9.5 假文案类） | Task 6 Step 10 #16 |
| 槽位的 `segment.episode_id` **不在**按集分开的台词表里 | `casting.dialogue_of` / `label_of` 抛，点名到槽位 id。**绝不退回"这一集没有台词"**：`_slot_block` 本来就有"该区间无台词转写"那一支（素材事实，合法），缺键走那一条会让编剧对着别的集的画面写一段什么都不说的解说 | Task 4 Step 7 #4/#5 |

**成本账的口径差不变，但可判定的那一半扩大了一圈**（R7 的后续）：`_reject_same_episode_sibling` 这道成稿**前**的闸门原先按"同模式同集"判，跨集之后按"同模式**同一组集**"判——证明仍然成立，因为 `_plan_one` 的非剧本分支里 `variant` 只进 `copywriter` 的 `angle_block`、**不进** `build_plan`（新签名 `build_plan(mode, scenes, highlights, material, settings)` 的五个入参没有一个来自角度名或理由），故时间轴是 `(mode, 取材集组合)` 的纯函数：同一组集 ⇒ 同一份场景表 ⇒ 同一条时间轴 ⇒ Jaccard = 1.0。豁免的只剩 `dialogue_narration` 一个模式，而且理由**换了**——不再是"只有它能跨集"（现在九个都能），而是"它的剧本由模型按角度现写，同一组集也能写出两条压在几乎同一段画面上的剧本"，成稿前无从判定。常量因此从 `_CROSS_EPISODE_MODES` 改名为 `_SCRIPT_DRIVEN_MODES`（Task 6 Step 7 第 4 点）。

### 定案三：job 与库的形状

**新列，不建新表。** `narration_plans` 加五列（迁移 `010`）：

| 列 | 类型 | 为什么必须是列而不是塞进 `plan_data` |
|---|---|---|
| `angle` | `TEXT NOT NULL DEFAULT ''` | 卡片的角度名（金色标签）。要按角度查重叠、按角度名排除重掷，塞在 JSON 里就得每行解析一遍 |
| `angle_reason` | `TEXT NOT NULL DEFAULT ''` | 卡片四要素之一「模型自选理由」，纯展示但必须留痕（模型为什么选这条） |
| `variant_index` | `INTEGER NOT NULL DEFAULT 1` | 1..K 的槽位号。不能靠 `created_at` 排序推：**本机实测背靠背两次 `_now_ms()` 有 2000/2000 = 100.0% 撞同一个毫秒值**，而并列时 `ORDER BY created_at DESC` 实测 200/200 返回**先插入**那一行。`infra/jobs.py` 为同一件事补过 `created_at, id` 兜底（理由写在 `:94-96` 的 docstring，SQL 在 `list_recent` 的 `ORDER BY updated_at DESC, created_at DESC, id`）；Task 1 把同一个兜底补给 `plans_repo.list_by_project` |
| `overlap_max` | `REAL`（可空） | 与已接受兄弟方案的最大取材重叠。可空因为**首条没有兄弟**；存下来是因为被拦掉的角度不留行、事后算不出当时那个数 |
| `batch_id` | `TEXT`（可空） | 一次 `plan_variants` 调用产出全组的标识，取该作业的 `job_id`。它是唯一不含糊的组键：同一 (project, mode) 会被整组重规划多次，`created_at` 分段不可靠 |

**`钩子首句` 不单独立列**：卡片要展示的是"这条片实际说的第一句"，真相源是 `plan_data.narration_texts[0].text`（成稿后模型可能改写选题给的 hook）。存两份必然漂移，`get_plan` 现取即可。

**成本账不立列**：`copy_llm_calls` = `1 if plan_data.narration_texts else 0`（`raw_clip`/`subtitle_flow` 无槽位、零成稿，已由 `modes_w9.py` 全文无 `NarrationText` 证实），`tts_calls` = `len(plan_data.narration_texts)`。两个都是**恒等推导**，存下来只多一处会漂的副本（docs/04 §5.2「同一概念双处定义」）。口径写在唯一的助手 `plan_cost()` 里，`get_plan` 返回它——这就是"可观测而不必事后重算"。选题次数按定案二由 `batch_id` + `DISTINCT narration_mode` 数出。**注意这是"落库口径"不是"花销口径"**：被重叠闸门拦掉的角度不留行，它的成稿花费因此不在这两个数里（详见《定案二》的 R7 段）。

**方案行永不覆写，只追加。** 整组重规划 = 新 `batch_id` + K 条新行；重掷此条 = 新 `batch_id` + 1 条新行，`exclude_plan_ids` 指名被替换的方案、其角度名进选题 prompt 的排除清单。不覆写的理由：`export_jobs.narration_plan_id` 指向被渲染的那一行，覆写会让成品库的「跳回方案」（规格 §5 #33）指到一个已不是当初渲染出来的角度上。阶段③ 如何把"重掷的单条"并回 K 条一组显示，是 P-3 的展示决策，本批次只保证**任何并法都可行**。

**`export.submit` 与既有幂等 `retry` 的分工**：`submit` 是"新提交"，每条方案建一行新 `export_jobs` + 一个新 export job；`retry` 是"重跑一条已失败的提交"，复用原 `export_id` 覆盖写（`api/export.py:124-152`，P-1 已幂等）。**`submit` 不复制 `retry` 的任何机械**——两者都经同一个 `_submit_export`（`api/export.py:66-94`）投递，取消事件的注册与 `_run_export` finally 里的回收因此仍只有一处。一条方案一个 export job（不是一次提交一个大 job），这样规格 §4.4 的「条级 重掷/重试」与 `jobs.cancel` 的粒度才对得上。

**`submit` 不去重历史、只去重本次调用**：同一个 `plan_id` 在一次 `plan_ids` 里出现两次只出一次片（这是纯 bug，必须拦）；跨两次提交重复渲染同一条方案是合法的（换了字幕预设再出一版——规格 §4.3 ④ 的字幕预设与连载模式都是"提交时参数"），成品去重归 P-3 的成品库批量动作。

**本计划的错误码静默依赖一件事：Router 不做 JSON Schema 校验。** `transport/rpc.py` 的 `Router.dispatch`（实测 `:78-88`）全文只有三步——查方法表、`handler(request.params)`、把 `RpcDomainError` 与其他异常转成错误响应。**它从不拿 `protocol/schemas/*.json` 去校验入参**。所以：

- `-32303`（K 越界）之所以能触发，是因为 `plan_variants` 里**手写了** `if not 1 <= k <= _MAX_VARIANTS`，而 schema 里那句 `"maximum": 8` 只是文档；
- `-32302`（空 modes）同理，靠手写的 `if not modes`，schema 的 `"minItems": 1` 无人执行；
- `-32406`（`plan_ids` 非法）同理。

**这条依赖必须被写下来**：哪天有人"给 Router 统一加上 schema 校验"，这三个错会被 `-32602 INVALID_PARAMS` 抢先接管（或者两处都报、语义重复），而 `test_k_out_of_range_is_rejected_at_the_rpc_boundary`、`test_empty_modes_is_rejected`、`test_bad_plan_ids_are_rejected_at_the_rpc_boundary` 三条用例会一起改判——看起来像"测试坏了"，实际是契约执行层换了人。做那件事的人必须同批决定：**手写校验删掉、错误码映射到 `-32602`，还是保留手写校验并让 schema 校验只兜未登记的键**。Task 6 Step 5 在 schema 里也把这句话写进 `description`，两侧都留痕。

### 定案四：两个模式族的 K 条各自从哪来（规格 §4.2 + §4.3 ④）

**规格原文两句，都是用户定案，本计划不得推翻**：

- §4.2 空态三步的第 ② 步：「配 LLM（**解说类模式必需**：七个解说模式的文案由编剧模型产出，未配置则这七个模式的每条方案都失败并在队列页说明原因（§3.3.1），**仅「纯原片剪辑」「字幕金句流」不依赖 LLM**）」
- §4.3 ④：「条数按模式族分别算：**解说类 = K，规则类 = 全剧 top-K 冲突窗**（**两者不同源，已由用户定案**）」

**代码侧的三面镜子与此一致**：`api/narration.py` 的 `_NO_TTS_MODES = frozenset({"raw_clip", "subtitle_flow"})` 与由它派生的 `_NARRATION_MODES`；`modes_w9.py` 全文无 `NarrationText`、`modes/__init__.py::build_raw_clip` 也不产槽位；`scripts/verify_modes.py` 的 `EXPECT_PLANNER` 把这两个模式钉在 `"rule"`。所以：**这两个模式既不经选题模型，也不经成稿模型**，`plan_variants` 对它们调 `angles.select_angles` 就是把"不依赖 LLM"改成"依赖 LLM"，而 `select_angles` 在未配置时抛 `LlmUnavailable`（Task 3 的 `test_unconfigured_llm_raises_before_prompt` 正钉着这一行为）——**纯剪辑作业会在 LLM 未配置时整族失败**。这是本计划审查里最严重的一条（B2/R1）。

**分流点**：`_run_plan_variants` 按 `mode in _NARRATION_MODES` 分流，**两族只在这里分岔**；失败粒度、进度记账、重叠闸门、配音、落库五件事共用同一段代码（见 Task 6 Step 7 第 11 点的 `_Variant` 会合点）。

**解说类（七模式）**：K 条来自 `angles.select_angles`，见《定案二》。

**规则类（`raw_clip` / `subtitle_flow`）**：K 条来自**全剧 top-K 冲突窗**，实现在 Task 3b 的 `pipeline.top_conflict_windows`。设计要点与它们各自的依据：

1. **榜单必须跨集**。今天两个编排器吃的都是**带集身份**的场景表（Task 3c 之后是 `list[EpisodeScene]`），而 `ConflictScore`（`engines/semantic/models.py`）只有 `scene_index/start/end/score/reason`，**不带集身份**——身份是 Task 3c 的 `casting.stamp` 在规划期盖上去的。所以**排名**这一步仍然只能在编排器**之外**做，并且必须把 `(集号, 场景)` 成对喂进、成对取出——否则排完就不知道那一窗属于谁。
2. **按集去重，再轮转发成 K 手**（2026-09-12 裁决后改，原状是"一集一条"）。`build_raw_clip` 与 `build_subtitle_flow` 都是 `(取材集, 该集场景表)` 的**确定性纯函数**：同一组的两个不同窗口喂进去会得到**逐字节相同**的方案。那不是 K 条互异，是 1 条复制 K 份，而且会被重叠闸门判成 100% 重叠、把 K-1 条报成失败。故"窗"在这里的作用是把**集**排出名次；排完由 `pipeline.deal_windows` **轮转**发成 K 手（第 j 手拿排名 j, j+K, j+2K…），每手若干集、手与手**不共集**。"一集一条"满足规格 §4.3 ④ 的条数要求但违反 §1 的「跨集方案」，轮转两个都满足，而且"手间不共集"接着保证了原先靠"按集去重"换来的那条零重叠性质。**实测**（活库十集、K=3）：排名 `[6,7,8,2,3,4,9,10,1,5]` → 三手 `[[2,5,6,9],[3,7,10],[1,4,8]]`。轮转而不是切块，是因为切块会让第 1 手独占 6/7/8 三个最高分集，三条片的强弱差一个量级。
3. **条数可以少于 K，但必须留痕**。发窗之后不足 K 手时（极端例子：全剧只分析完 1 集）返回 1..K-1 条。规格 §1 的原话是「每模式产出 **1..K** 条」，所以少出是合法形状；但 §3.3 禁止静默，故 `_rule_variants` 在少出时打一行 `notifier.log`。**另有一条新的留痕义务**：互不相交的多集手至少需要 `2 × K` 集，所以**集数 < 2K 时必有手退化成一集**（3 集发 3 手就是 1/1/1）。那是算术不是缺陷，但界面卡片写着"跨集方案"，实际只取一集时必须说清楚——`_rule_variants` 为此单独打一行日志，点名"其中 N 手只取到一集"。
4. **`angle` 与 `angle_reason` 一律留空串**。规则类没有模型自选的卖点角度，也没有旁白槽位去读钩子。这与 `protocol/schemas/narration.json` 里 `NarrationPlan.angle` 的描述「无解说的模式为空串」逐字对应，也与 Task 1 的 `test_angle_columns_default_to_the_migration_defaults` 一致。界面卡片靠**四要素里的「取材集区间」**（`episode_ids` + `plan_data.timeline`）加 `variant_index` 区分。
5. **`planner` 仍是 `"rule"`**。两个编排器都不写 `planner`，`PlanData.planner` 的默认值就是 `"rule"`（`engines/narration/models.py:60`），而成稿链一次都不跑——所以 `verify_modes.py` 的 `EXPECT_PLANNER` 无需改动。**这是"规则类没被拖进 LLM"最便宜的一道真机证据。**

**仍然做不到、且必须说清楚的那一半**（2026-09-12 裁决后**换了理由**）：让**每条方案的内容真的等于它那一窗**。原先的理由是技术的——「`ConflictScore` 不带集身份、`_fit_duration` 按单集截断」。**那个前提已经被 Task 3c 拆掉了**：集身份有了（`casting.EpisodeScene`），预算也重分了（`_fit_duration` 的末场景豁免删掉、引子槽位预留 `_INTRO_MAX_S`，实测数字见《修订记录》C6）。所以剩下的理由是**产品**的，需要业主回答（《开放问题》#1）：

- 一个"窗"是 3-25s（`modes/__init__.py` 的 `_RAW_CLIP_MIN_S` / `_RAW_CLIP_MAX_S`）。若"内容 = 一窗"，`raw_clip` 的每条方案就是一部 **3-25 秒**的片；而活库实测今天的 `raw_clip` 是 **15.13s**（三个场景，走的是"分数不足放宽到 top-3"那一支）。把 K 条方案压成 K 个单窗，条均时长会掉到今天的一半以下，而且 `subtitle_flow` 的 CTA 卡片段（`_CTA_FALLBACK_S = 3.0`）会比正片还长。
- 本批次因此交付的是：**用全剧冲突窗排名决定规则类的条数与每一条的取材集组合，再让编排器在这些集的全部场景上照常选**。实测（活库、K=3、第一手 `[2,5,6,9]`）：`raw_clip` planned **117.89s / 21 段 / 4 集**（单集 ep1 是 15.13s / 3 段 / 1 集），`subtitle_flow` planned **36.24s / 7 段 / 3 集**。
- 这个差别写进 Task 3b 的 docstring，不藏在代码里。

**两个待业主回答的问题**（见《开放问题》#3、#4）：

- 规则类的 K 条方案卡上，「模型自选理由」那一格显示什么？规格 §4.3 ③ 把四要素写成**每卡**的结构，但规则类没有模型理由。本批次留空串 + 日志留痕，是否可接受，还是要显示"全剧冲突榜第 N 窗（第 X 集 a-bs，冲突分 S）"这类**确定性**推导文案？后者不是假文案（它逐字可核对），但它不是"模型自选理由"，需要规格给个名字。
- 规则类的**重掷此条**今天是个空操作：`exclude_plan_ids` 只贡献角度名（`_excluded_angle_names` 跳过空 `angle`），而窗口榜是确定性的 → 重掷会得到**同一条方案**。本批次如实留痕（Task 6 Step 7 第 11 点在规则族分支打一行日志说明重掷无意义），要不要把规则类的「重掷此条」按钮换成「改方案数/改素材」是 P-2.5 队列页与阶段③ 的展示决策。

---

## 文件结构

**新建**

| 路径 | 职责 |
|---|---|
| `service/dramaclip/engines/narration/angles.py` | 选题层（**解说类七模式**）：一个模式一次 LLM 调用 → K 条卖点互异的 `AngleBrief`；逐条验收、不合格即抛 |
| `service/dramaclip/engines/narration/casting.py` | **取材层（2026-09-12 裁决新增）**：`EpisodeScene`（场景 + 集身份）、`EpisodeMaterial`（一集的集号与台词表）、`stamp`（逐集盖章）、`episode_order` / `score_order`（跨集叙事序与确定性分数序）、`dialogue_of` / `label_of`（按集取台词，缺键即抛）。纯数据层，不触 IO、不发网络请求 |
| `service/dramaclip/engines/narration/overlap.py` | 度量层：源素材秒的 Jaccard 取材重叠 + 60% 阈值常量。纯函数，不触 IO |
| `service/dramaclip/infra/storage/migrations/010_plan_angles.sql` | `narration_plans` 五列 + batch 索引 |
| `service/tests/engines/narration/test_angles.py` | 选题层的验收分支逐条钉住（**17 条变异检查**，对应 `_sanitize` 的 12 处 raise + `select_angles` 的 5 处；原为 18/13，`cross_episode` 那条分支随裁决删除，见《修订记录》C8） |
| `service/tests/engines/narration/test_casting.py` | 取材层：盖章不丢字段、播出序而非钟表序、同分确定性、按集取台词、缺键即抛（9 条） |
| `service/tests/engines/narration/test_cross_episode_arrangement.py` | **六个编排器的跨集性质**（10 条）：逐段盖自己场景的集号、播出序装配、预算不被顶穿、引子槽位预留、`scene_index` 跨集碰撞、`cross` 的旁白段盖锚点的集、`subtitle_flow` 的金句不串集、`ultra_short` 同分按集号定序 |
| `service/tests/engines/narration/test_overlap.py` | 合并、交集、Jaccard、阈值边界 |
| `service/tests/engines/narration/test_conflict_windows.py` | 规则类的"选题"：全剧 top-K 冲突窗排序、按集去重、同分确定性、`limit < 1` 即抛；**外加 `deal_windows` 的轮转发窗（手间不共集、每手都拿一个高分窗、集不够少发、`hands < 1` 即抛）**，共 12 条 |
| `service/tests/infra/storage/test_plans.py` | 五个新列的落库与读回、`list_by_batch`（两模式交错夹具）、`list_by_project` 的并列兜底 |
| `service/tests/api/test_plan_variants.py` | 由 `tests/api/test_produce.py` 改名而来（`git mv`）：`Harness` 与种子函数留在此文件，`test_data_paths.py:8` 的 import 随之改 |
| `service/tests/api/test_export_submit.py` | `export.submit` 的接受/拒绝两路、可渲染性守卫、与 `retry` 的同形 |

**修改**

| 路径 | 改什么 |
|---|---|
| `service/dramaclip/api/narration.py` | 删 `produce`/`_run_produce`/`generate_plans`/`_run_generation_parallel`/`_generate_one`/`_newest_ready_plan`；加 `plan_variants`/`_run_plan_variants`/`_angle_variants`/`_rule_variants`/`_plan_one`/**`_casting_for`**/`_voice`/`get_plan`/`plan_cost`/`_effective_settings`/`_worst_overlap`/`_excluded_angle_names` + `_Variant`/`_OverlapHit` 两个内部 dataclass；删三个随之失去引用的 import（含 `exports as exports_repo`）；`_CROSS_EPISODE_MODES` → `_SCRIPT_DRIVEN_MODES`（《修订记录》C10） |
| `service/dramaclip/api/export.py` | `start` → `submit(plan_ids)`；加 `_assert_renderable` 并被 `submit`/`retry` 共用；两个新错误码；**并修 `ExportRun`（`:49-63`）与 `_submit_export`（`:66-94`）的 docstring**——它们写着 `start/retry/produce` 三处调用点，Task 6/8 之后只剩 `submit`/`retry` 两处。**渲染路径本身一行不动**（它本来就跨集，证据见《定案二》） |
| `service/dramaclip/engines/narration/pipeline.py` | 加纯函数 `top_conflict_windows`（Task 3b）与 **`deal_windows`**（Task 3b Step 3b）；**`build_plan` 换签名**（`episode_id: str` → `scenes: list[EpisodeScene]`、`asr_segments` → `material: MaterialByEpisode`，并删死参数 `audio: AudioFeatures` 与随之成为死码的 `parse_audio_features`，Task 3c Step 5）；改 `_synthesize_into` 的 docstring（Task 5 Step 5）。**渲染与合成逻辑一行不动** |
| `service/dramaclip/engines/narration/modes/__init__.py` | **（原在"不动"清单，2026-09-12 裁决后移出）** `build_raw_clip` / `build_intro` 的首参 `episode_id: str` → `scenes: list[EpisodeScene]`；`_fit_duration` 去掉首参、删末场景预算豁免、`intro_first` 时预留 `_INTRO_MAX_S`；排序改走 `casting.episode_order` / `score_order`；`best` 的身份比较从 `scene_index` 改成 `is not`（Task 3c Step 4） |
| `service/dramaclip/engines/narration/modes_w5.py` | 同上（`build_cross` / `build_ultra_short`）；**`build_cross` 的旁白段集号改跟锚点走**（`episode_id=anchor.episode_id`）；`build_ultra_short` 的 `max(key=score)` 改成 `min(key=score_order)`（Task 3c Step 4） |
| `service/dramaclip/engines/narration/modes_w8.py` | 同上（`build_full`）；`_slot_brief` 与 `_MAX_SCENES` 一字不动——槽位职责是**弧内位次**，跨集之后语义不变（Task 3c Step 4） |
| `service/dramaclip/engines/narration/modes_p2.py` | 同上（`build_dual_host` / `build_monologue` / `_pick`）；双音色交替按弧内位次，跨集之后语义不变（Task 3c Step 4） |
| `service/dramaclip/engines/narration/modes_w9.py` | `build_subtitle_flow` 的第二参从摊平的 `asr_segments: list[AsrSegment]` 换成 `material: casting.MaterialByEpisode`，`strongest_line` 因此只会看到**该场景自己那一集**的台词（Task 3c Step 4） |
| `service/dramaclip/engines/narration/copywriter.py` | `write_plan_copy` 增必填关键字 `angle_block`（Task 4），**第二参从 `asr_segments: list[AsrSegment]` 换成 `material: casting.MaterialByEpisode`**；`_slot_block` 按 `segment.episode_id` 取台词并把集名写进槽位块；缺键抛、不退回"该区间无台词"（Task 4 Step 3b，《修订记录》C7） |
| `service/dramaclip/engines/narration/scriptwriter.py` | `write_script_episodes` 增必填关键字 `angle_block`；`_format_transcript_episodes` → `format_transcript_episodes`（公开给 `angles.py` 复用，与 P-1.5 公开 `FUNDAMENTALS`/`clock`/`dump_trace` 同一套路），**并同步改 `:220` docstring 里对旧名的引用** |
| `service/dramaclip/engines/narration/script_driver.py` | `script_dialogue_plan` 增必填关键字 `angle_block` 并转交 |
| `service/dramaclip/infra/storage/repos/plans.py` | `_COLUMNS` 加五列；`create` 加五个关键字参数；新增 `list_by_batch`；`list_by_project` 补 `created_at, id` 兜底排序 |
| `service/dramaclip/infra/config.py` | `DEFAULTS` 加 `narration.variants_per_mode`（插在 `:34` 的 `narration.style_id` 之后） |
| `protocol/schemas/narration.json` | 删 `generate_plans`/`produce`，加 `plan_variants`/`get_plan`；`NarrationPlan` 加五字段 + `PlanCost`/`PlanDetail`；`list_plans` 加 `batch_id`；`k` 的 `description` 里写明"schema 的 maximum 只是文档，实际拦截靠 api 层手写校验（Router 不做 schema 校验）" |
| `protocol/schemas/export.json` | `start` → `submit`，返回体改 `{exports, rejected}` |
| `protocol/schemas/jobs.json` | `JobInfo.type` 的描述去掉 `produce`、补上实际在用的 `semantic` |
| `protocol/ts/index.ts` | `METHOD_NAMES` 同步（删 2 加 2，净 0）；`NarrationPlan` 加字段；新增 `PlanCost`/`PlanDetail`/`PlanVariantsResult`/`ExportSubmission`/`ExportRejection`/`ExportSubmitResult` |
| `desktop/src/services/client.ts` | 删 `narrationApi.produce`/`generatePlans`、`exportApi.start`；加 `planVariants`/`getPlan`/`submit`/`retry`。**按内容锚点定位，不按行号**（见 Task 8 Step 6 与 Task 9 Step 4 的实测行号附注） |
| `desktop/src/features/narration/useProduceJob.ts` | 唯一的生产调用点（`:31` 的 `narrationApi.produce`）：改成 `plan_variants` → 等作业 → `list_plans` 取本 batch → `export.submit` → 等全部 export job。**这是保住既有页面可用，不是做 UI**；`waitJob` 带 `onTick` 回调，两阶段的进度条都照常动 |
| `scripts/verify_modes.py` | ① `:39` 的 import 区加 `export as export_api`、`:456-457` 的 Router 装配加 `export_api.register(router, ctx)`（**B1：不加这两行，九个模式全拿 `-32601`，门禁 exit 1**）；② `:459` 的单次派发 → 规划 + 提交两步；③ argparse 加 `--variants`（默认 1）、`--plan-only` 与 **`--require-cross-episode`**；④ `done` 计数之后加前置条件停机分支（**散文按裁决重写**）；⑤ `:75-85` 的 `EXPECT_PLANNER` 推导散文与 `:382` 的注释改指新函数名；⑥ **新增 `集数` 列与跨集断言**（Task 9 Step 2.8） |
| `service/tests/api/test_data_paths.py` | `:8` 的 import 源改名；`:18-23` 的 `narration.produce` → 规划 + 提交两步 |
| `service/tests/engines/narration/test_modes.py`、`test_modes_w5.py`、`test_modes_w8.py`、`test_modes_p2.py`、`test_modes_w9.py`、`test_ducked_narration.py`、`test_copywriter.py`、`tests/api/test_narration_audio_chain.py`、`tests/api/test_narration_no_downgrade.py` | **九个既有测试文件的编排器/成稿调用点跟随换签名**（实测共 24 处 `build_*` 调用 + 10 处 `write_plan_copy` 调用）。Task 3c Step 6 与 Task 4 Step 5 逐文件给出替换后的字面行；`test_modes.py:7` 的 `AudioFeatures` import 与 `:61` 那行的折行、`test_ducked_narration.py:150` 的折行都是 ruff 实跑出来的（E501 / I001） |
| `docs/03-IPC协议规范.md` | §5.2 错误码表加 `-32303/-32304/-32406/-32407`、**改 `:86` 那一行**（`-32401` 不再覆盖"编排时间轴为空"）；§6 的「46 个方法」重数、`narration.*`（`:118`）与 `export.*`（`:119`）条目改写、删掉「`narration.get_plan` 从未实现」那句（`:131`，本批次实现它） |
| `docs/service/01-传输与API层设计.md` | §4 的方法清单（`:66-67`）与合计数（`:75`）、§6 的「`projects.settings` 尚无消费端」（`:132`）改成已接线并登记覆盖键名 |
| `docs/service/04-数据模型.md` | `narration_plans` 的 DDL（`:108-` ）加五列、迁移清单（`:305`，"实测 8 个文件"已过期，实为 9）加 `010` 行并补上漏登记的 `009`、§3 登记实际使用的项目级覆盖键名 |

**不动**：`docs/05-开发路线图.md`（用户自维护）；另一位工程师的 `scripts/verify_e2e.mjs`（**它有两处会随本批次失效的派发，P-2a 不改它，改为书面移交属主，见 Task 9 Step 1b**）、`scratch/`、`tests/api/test_analysis.py`、`tests/engines/analysis/*`、`hotwords.py`、`docs/07-*`；`data/data.db`（只读，实测含 52 行方案、10 集已分析）；**`engines/semantic/models.py`（`ConflictScore` 一个字段都不加——集身份是规划期注入的，理由与"加字段会往落库 JSON 里写进 `episode_number: 0` 这种假值"的实测见《修订记录》C3）**；**`engines/narration/models.py`（`TimelineSegment.episode_id` 逐段已存在，多集时间轴今天就能表示）**；`engines/exporter/*`（渲染侧一行不动——它本来就按 `segment.episode_id` 逐段取源，这是拆分干净的证明，也是"跨集只改规划侧"的证明）；`api/export.py` 的渲染路径（同上）；`engines/narration/pipeline.py` 的**合成与剧本装配逻辑**（`build_from_script_episodes` / `synthesize_narration_texts` / `_content_addressed_audio` / `_synthesize_into` 一行不动，本批次只加两个纯函数、改 `build_plan` 的签名与一段 docstring）。

**从"不动"清单移出的**：五个模式编排器文件（`modes/__init__.py`、`modes_w5.py`、`modes_w8.py`、`modes_p2.py`、`modes_w9.py`）。原清单的理由是《定案四》那句「规则类的 K 条在编排器**之外**决定，不改它们的签名与成片形态」——**裁决之后前半句仍成立（排名与发窗都在编排器之外），后半句不成立了**（规格 §1 的「跨集方案」必须改它们的取材结构与盖章处）。`modes_w9.py` 也在其中：它的 `build_subtitle_flow` 吃一张摊平的 ASR 表，跨集之后金句会串集。

---

## Task 1: 迁移 010 + `narration_plans` 五列 + 仓储读写

**Files:**
- Create: `service/dramaclip/infra/storage/migrations/010_plan_angles.sql`
- Modify: `service/dramaclip/infra/storage/repos/plans.py`
- Modify: `service/tests/infra/storage/test_db.py:31-41`（`expected_migrations` 清单，`"009_ocr_segments.sql",` 在 `:40`）
- Create: `service/tests/infra/storage/test_plans.py`

- [ ] **Step 1: 写失败测试**

新建 `service/tests/infra/storage/test_plans.py`：

```python
"""narration_plans 的角度五列：落库、读回、按 batch 取组。

五列的存在理由见 P-2a 计划《定案三》。这里只钉一件事：写进去的角度信息必须
原样读得回来——`plan_data` 是 JSON 文本、这五列是真列，读回路径（`_row_to_dict`
的 zip）漏一列不会报错，只会静默少一个字段。
"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo


def _seed_project(conn: sqlite3.Connection) -> str:
    return str(projects_repo.create(conn, "角度剧", "D:/media/角度剧")["id"])


def test_create_persists_the_five_angle_columns(memory_db: sqlite3.Connection) -> None:
    project_id = _seed_project(memory_db)
    row = plans_repo.create(
        memory_db,
        project_id,
        "full_narration",
        ["ep1"],
        {"mode": "full_narration", "timeline": []},
        angle="复仇线",
        angle_reason="全剧最狠的一次反杀落在第 3 集",
        variant_index=2,
        overlap_max=0.31,
        batch_id="batch-a",
    )
    assert row["angle"] == "复仇线"
    assert row["angle_reason"] == "全剧最狠的一次反杀落在第 3 集"
    assert row["variant_index"] == 2
    assert row["overlap_max"] == 0.31
    assert row["batch_id"] == "batch-a"

    fetched = plans_repo.get(memory_db, str(row["id"]))
    assert fetched is not None
    assert fetched["angle"] == "复仇线"
    assert fetched["angle_reason"] == "全剧最狠的一次反杀落在第 3 集"
    assert fetched["variant_index"] == 2
    assert fetched["overlap_max"] == 0.31
    assert fetched["batch_id"] == "batch-a"


def test_angle_columns_default_to_the_migration_defaults(
    memory_db: sqlite3.Connection,
) -> None:
    """不传角度信息也要能建（迁移的 DEFAULT 就是这条契约），且首条方案 overlap_max 为空。"""
    project_id = _seed_project(memory_db)
    row = plans_repo.create(
        memory_db, project_id, "raw_clip", ["ep1"], {"mode": "raw_clip", "timeline": []}
    )
    assert row["angle"] == "" and row["angle_reason"] == ""
    assert row["variant_index"] == 1
    assert row["overlap_max"] is None, "首条方案没有兄弟，重叠率是「无从比」而不是 0"
    assert row["batch_id"] is None


def test_list_by_batch_returns_only_that_batch_in_mode_then_variant_order(
    memory_db: sqlite3.Connection,
) -> None:
    """一个 batch 通常跨多个模式，阶段③ 要按模式分组显示 → 排序键必须带 narration_mode。

    夹具刻意做成**两模式 + 变体号交错**（raw_clip 的 1 号先插、full_narration 的
    2 号次之、1 号最后）：只按 variant_index 排会把 raw_clip·1 排到最前，
    只按 created_at 排会照抄插入顺序，两者都与 (模式, 变体号) 不同——
    于是排序键的两半**各有一条变异能把它打红**（Step 7 的 #3 与 #3b）。
    原夹具是单模式 + 变体号递增，那两个变异一个都红不了（实测过）。
    """
    project_id = _seed_project(memory_db)
    seeded = (
        ("batch-a", "raw_clip", 1),
        ("batch-a", "full_narration", 2),
        ("batch-a", "full_narration", 1),
        ("batch-b", "full_narration", 1),
    )
    created: list[str] = []
    for batch, mode, index in seeded:
        row = plans_repo.create(
            memory_db,
            project_id,
            mode,
            ["ep1"],
            {"mode": mode, "timeline": []},
            angle=f"角度{mode}{index}",
            variant_index=index,
            batch_id=batch,
        )
        created.append(str(row["id"]))
    # created_at 是毫秒精度，背靠背插入实测 2000/2000 撞同一个值（见《计划修订记录》B4）。
    # 显式拉开时间戳：`ORDER BY created_at` 这条变异必须因为**顺序**而红，
    # 不能靠 SQLite 在并列值上的扫描顺序来红——那是实现细节，换个版本就变。
    memory_db.executemany(
        "UPDATE narration_plans SET created_at = ? WHERE id = ?",
        [(1_700_000_000_000 + offset, plan_id) for offset, plan_id in enumerate(created)],
    )
    memory_db.commit()

    group = plans_repo.list_by_batch(memory_db, project_id, "batch-a")
    assert [(row["narration_mode"], row["variant_index"]) for row in group] == [
        ("full_narration", 1),
        ("full_narration", 2),
        ("raw_clip", 1),
    ]
    assert plans_repo.list_by_batch(memory_db, project_id, "batch-缺") == []


def test_list_by_project_still_carries_the_angle_columns(
    memory_db: sqlite3.Connection,
) -> None:
    """`list_by_project` 走的是同一个 `_row_to_dict`：新五列必须在**列表**路径上也读得回来。

    **不断顺序**。原用例断言 `[:2] == ["新角度", "旧角度"]`，靠 `ORDER BY created_at DESC`；
    实测背靠背两次 `_now_ms()` 有 2000/2000 撞同一个毫秒值，而并列时该排序
    200/200 返回**先插入**那一行——也就是说那条断言在落地那天就是红的（B4）。
    顺序由下一条用例按"并列必须确定性"这个真实不变量去钉。
    """
    project_id = _seed_project(memory_db)
    plans_repo.create(
        memory_db, project_id, "raw_clip", [], {"mode": "raw_clip"}, angle="旧角度"
    )
    plans_repo.create(
        memory_db, project_id, "raw_clip", [], {"mode": "raw_clip"}, angle="新角度"
    )
    listed = plans_repo.list_by_project(memory_db, project_id)
    assert {row["angle"] for row in listed} == {"旧角度", "新角度"}
    assert len(listed) == 2


def test_list_by_project_breaks_created_at_ties_by_id(
    memory_db: sqlite3.Connection,
) -> None:
    """并列时间戳必须有确定性兜底：`ORDER BY created_at DESC, id`。

    `infra/jobs.py::list_recent` 为同一件事补过 `created_at, id`（理由写在它的
    docstring 里：同毫秒内变更的任务否则顺序随机，队列页每次刷新可能跳行）。
    阶段③ 的"最近方案"列表有完全一样的症状。

    夹具用 raw SQL 直插两个**自己挑的** id，且插入顺序与 id 升序**相反**：
    `DESC` 只作用于 created_at，并列时 id 是升序，故兜底给出 ["aaa","zzz"]、
    不兜底给出插入顺序 ["zzz","aaa"]——两者必然不同，Step 7 的变异 #5 才红得下来。
    """
    project_id = _seed_project(memory_db)
    for plan_id in ("zzz", "aaa"):
        memory_db.execute(
            "INSERT INTO narration_plans (id, project_id, narration_mode, episode_ids,"
            " plan_data, status, created_at, angle) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan_id,
                project_id,
                "raw_clip",
                "[]",
                '{"mode": "raw_clip"}',
                "ready",
                1_700_000_000_000,
                plan_id,
            ),
        )
    memory_db.commit()
    listed = plans_repo.list_by_project(memory_db, project_id)
    assert [row["id"] for row in listed] == ["aaa", "zzz"], (
        "并列 created_at 的顺序不确定：阶段③ 每次刷新可能跳行"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/infra/storage/test_plans.py -q`

Expected: FAIL —— **五条全红**，但**红的形态分两种，两种都要看到**：

- 四条报 `TypeError: create() got an unexpected keyword argument 'angle'`；
- `test_list_by_project_breaks_created_at_ties_by_id` 报 `sqlite3.OperationalError: table narration_plans has no column named angle`（它绕过仓储直插，所以撞的是**列不存在**而不是关键字不认）。

若五条全是同一种形态，说明 Step 1 的 raw SQL 那条被写成了走仓储，改回来——它故意不走仓储，为的是能自己挑 id。

- [ ] **Step 3: 写迁移**

新建 `service/dramaclip/infra/storage/migrations/010_plan_angles.sql`：

```sql
-- P-2a 规划/渲染解耦：一条方案要能被当成「一个角度」来看、来比、来重掷。
-- 五列都是真列而不是塞进 plan_data：角度要查重叠、要按名排除、要按 batch 取组，
-- 塞在 JSON 里就得每行解析一遍。权威定义同步更新 docs/service/04-数据模型.md。
ALTER TABLE narration_plans ADD COLUMN angle TEXT NOT NULL DEFAULT '';
ALTER TABLE narration_plans ADD COLUMN angle_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE narration_plans ADD COLUMN variant_index INTEGER NOT NULL DEFAULT 1;
ALTER TABLE narration_plans ADD COLUMN overlap_max REAL;
ALTER TABLE narration_plans ADD COLUMN batch_id TEXT;
CREATE INDEX IF NOT EXISTS idx_plans_batch ON narration_plans(project_id, batch_id);
```

**这五条 ALTER 打在一张有数据的表上，已实测过（不要凭"应该合法"就往下走）**：`data/data.db` 是活库，实测含 **52 行**方案（1 个项目），现有列仍是旧 8 列。在 `D:/tmp` 的 scratch 库上跑真迁移（`db.migrate` 应用 001–009）、按**旧 7 列** INSERT 写 3 行、再 `executescript` 上面这段，结果是：

- 合法，无异常；3 行旧数据读回 `('', '', 1, None, None)`，即各列拿到本迁移写的 DEFAULT，`NOT NULL` 因此满足（SQLite 对有数据的表加 `NOT NULL` 列要求必须带非空 DEFAULT，这里三列都带了）；
- `pragma integrity_check` = `ok`；12 列 SELECT 配 `_row_to_dict` 的 `zip(strict=True)` 正常；
- **重复应用**这段会抛 `sqlite3.OperationalError: duplicate column name: angle`——响亮失败，不会静默损坏。正常路径不会重放：`db.migrate` 按文件名在 `schema_migrations` 里记账（`infra/storage/db.py:24-36`）。

实测环境：本仓 `.venv` 自带 `sqlite3.sqlite_version = 3.50.4`、pysqlite `2.6.0`。

- [ ] **Step 4: 把 010 加进迁移白名单**

`service/tests/infra/storage/test_db.py`，在 `expected_migrations` 列表的 `"009_ocr_segments.sql",` 之后加一行：

```python
            "010_plan_angles.sql",
```

（**这一行不加，`test_migrate_idempotent` 必红**——它断言 `db.migrate` 的返回值逐字等于那份清单。上一批的工程师就是在这里撞的号。）

- [ ] **Step 5: 改仓储**

`service/dramaclip/infra/storage/repos/plans.py`：

1. `_COLUMNS` 整块替换：

```python
_COLUMNS = (
    "id", "project_id", "narration_mode", "episode_ids", "plan_data", "status", "created_at",
    "angle", "angle_reason", "variant_index", "overlap_max", "batch_id",
)
```

2. `create` 整函数替换：

```python
def create(
    conn: sqlite3.Connection,
    project_id: str,
    narration_mode: str,
    episode_ids: list[str],
    plan_data: dict[str, Any],
    *,
    status: str = "ready",
    angle: str = "",
    angle_reason: str = "",
    variant_index: int = 1,
    overlap_max: float | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """建一条方案行并原样返回（含五个角度字段）。

    默认值与迁移 010 的列默认逐字对应，不是兼容垫片：raw_clip / subtitle_flow
    这类无解说的模式确实没有角度可言，`overlap_max=None` 也确实表示「首条无兄弟、
    无从比」，与 0.0（比过、完全不重叠）是两件事。
    """
    plan_id = uuid4().hex
    created_at = _now_ms()
    conn.execute(
        "INSERT INTO narration_plans (id, project_id, narration_mode, episode_ids, plan_data,"
        " status, created_at, angle, angle_reason, variant_index, overlap_max, batch_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            plan_id,
            project_id,
            narration_mode,
            json.dumps(episode_ids),
            json.dumps(plan_data, ensure_ascii=False),
            status,
            created_at,
            angle,
            angle_reason,
            variant_index,
            overlap_max,
            batch_id,
        ),
    )
    conn.commit()
    return {
        "id": plan_id,
        "project_id": project_id,
        "narration_mode": narration_mode,
        "episode_ids": episode_ids,
        "plan_data": plan_data,
        "status": status,
        "created_at": created_at,
        "angle": angle,
        "angle_reason": angle_reason,
        "variant_index": variant_index,
        "overlap_max": overlap_max,
        "batch_id": batch_id,
    }
```

（原实现在返回字典里第二次调 `_now_ms()`，返回值与库内的 `created_at` 因此可以差 1 毫秒；顺手改成同一个 `created_at` 变量。`update_plan_data` 与 `get` 不动。）

3. 在 `list_by_project` 之后新增：

```python
def list_by_batch(
    conn: sqlite3.Connection, project_id: str, batch_id: str
) -> list[dict[str, Any]]:
    """一次 plan_variants 调用产出的整组方案，按 (模式, 变体号) 升序。

    排序键带 narration_mode：一个 batch 通常覆盖多个模式，阶段③ 要按模式分组显示；
    只按 variant_index 排会把不同模式的第 1 条混在一起。
    """
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM narration_plans"
        " WHERE project_id = ? AND batch_id = ?"
        " ORDER BY narration_mode, variant_index",
        (project_id, batch_id),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]
```

4. `list_by_project` 整函数替换（**补 `created_at, id` 兜底排序**，B4）：

```python
def list_by_project(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    """项目全部方案，最近优先。

    排序补 `created_at, id` 兜底，与 `infra/jobs.py::list_recent` 同一理由：
    `created_at` 是毫秒精度，背靠背插入实测 2000/2000 撞同一个值，而并列时
    单键排序的顺序由 SQLite 的扫描顺序决定——阶段③ 每次刷新可能跳行。
    兜底之后顺序是**总序**（id 是 uuid4 hex，并列时按字典序升序），可复现。
    组内顺序请用 `list_by_batch`（它按 (模式, 变体号) 排），不要依赖本函数的顺序。
    """
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM narration_plans WHERE project_id = ?"
        " ORDER BY created_at DESC, id",
        (project_id,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]
```

（**这不是顺手重构**：Task 6 之后 `list_by_project` 只剩两个消费者——`narration.list_plans`（阶段③ 的"全部方案"视图）与 P-2b 的「已过期」判据（它取 `MAX(created_at)`，与顺序无关）。前者是给人看的列表，跳行就是 bug；后者不受影响。所以补兜底没有下游风险，而不补就把一个已知的顺序不稳定留给 P-3 的界面。）

- [ ] **Step 6: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/infra/storage -q`

Expected: PASS（`test_plans.py` **5** 条 + `test_db.py` 3 条 + `test_episodes.py` 全绿）

- [ ] **Step 7: 变异检查**

依次手工破坏，每项跑 Step 6 的命令必须变红，改回后绿：

| # | 破坏 | 必须红的用例与**实际失败形态** |
|---|---|---|
| 1 | `plans.py` 的 `_COLUMNS` 去掉 `"overlap_max"` | `test_create_persists_the_five_angle_columns` 与 `test_angle_columns_default_to_the_migration_defaults` 红，但**是 `KeyError: 'overlap_max'`，不是 `ValueError`**。理由（实测）：`_COLUMNS` **同时**拼 SELECT 列表与 `_row_to_dict` 的 zip，去掉一列后两边都是 11 项，`zip(strict=True)` 根本不抛；抛的是随后那次下标取值。`create()` 的返回字典是手写字面量、不经 `_COLUMNS`，所以红点在 `plans_repo.get(...)` 之后。**别把 `strict=True` 当成这里的救星**——它救的是"SELECT 与 zip 用了两份不同清单"那种病，本仓没有那种病 |
| 2 | 迁移里 `overlap_max REAL` 改成 `overlap_max REAL NOT NULL DEFAULT 0` | `test_angle_columns_default_to_the_migration_defaults` 红（`None` 变 `0.0`，「无从比」被伪装成「完全不重叠」） |
| 3 | `list_by_batch` 的 `ORDER BY narration_mode, variant_index` 改成 `ORDER BY created_at` | `test_list_by_batch_returns_only_that_batch_in_mode_then_variant_order` 红。实测：正确排序给 `[(full_narration,1),(full_narration,2),(raw_clip,1)]`，`ORDER BY created_at` 给 `[(raw_clip,1),(full_narration,2),(full_narration,1)]`（夹具已用 raw SQL 把 `created_at` 拉开成插入顺序，故这条变异红在**顺序**上，不依赖 SQLite 的并列行为） |
| 3b | `list_by_batch` 的 `ORDER BY narration_mode, variant_index` 改成 `ORDER BY variant_index`（**只删模式那半键**） | 同上用例红。实测给 `[(raw_clip,1),(full_narration,1),(full_narration,2)]`。**这半键是 `list_by_batch` docstring 里写的全部理由，而原计划一条用例都没给它**——夹具是单模式递增，删掉模式键结果不变 |
| 4 | `list_by_batch` 的 `WHERE` 去掉 `AND batch_id = ?` | 同上用例红（返回 4 条而不是 3 条） |
| 5 | `list_by_project` 的 `ORDER BY created_at DESC, id` 改回 `ORDER BY created_at DESC` | `test_list_by_project_breaks_created_at_ties_by_id` 红：实测不兜底时返回插入顺序 `["zzz","aaa"]`，兜底后返回 id 升序 `["aaa","zzz"]`。夹具故意让插入顺序与 id 升序相反，所以这条变异**必然**红，不是 50% 概率 |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/infra/storage -q`

- [ ] **Step 8: 提交**

```bash
git add service/dramaclip/infra/storage/migrations/010_plan_angles.sql service/dramaclip/infra/storage/repos/plans.py service/tests/infra/storage/test_db.py service/tests/infra/storage/test_plans.py
git commit -m "feat(storage): narration_plans 增角度五列，方案行开始承载卖点角度"
```

---

## Task 2: 度量层——`overlap.py` 取材重叠

**Files:**
- Create: `service/dramaclip/engines/narration/overlap.py`
- Create: `service/tests/engines/narration/test_overlap.py`

- [ ] **Step 1: 写失败测试**

新建 `service/tests/engines/narration/test_overlap.py`：

```python
"""取材重叠度量：源素材秒的 Jaccard。规格 §4.3 的 60% 安全阀。

夹具全是手搓的 PlanData（不跑编排器）：本模块是纯函数，把编排器拉进来只会让
「重叠算错了」与「编排变了」两种失败混在一起。
"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration import overlap
from dramaclip.engines.narration.models import PlanData, TimelineSegment


def _plan(spans: list[tuple[str, float, float]], mode: str = "full_narration") -> PlanData:
    return PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(episode_id=ep, start=start, end=end, audio="ducked")
            for ep, start, end in spans
        ],
    )


def test_identical_material_is_one() -> None:
    a = _plan([("ep1", 0.0, 10.0), ("ep1", 20.0, 30.0)])
    assert overlap.overlap(a, a) == pytest.approx(1.0)


def test_disjoint_material_is_zero() -> None:
    a = _plan([("ep1", 0.0, 10.0)])
    b = _plan([("ep1", 10.0, 20.0)])
    assert overlap.overlap(a, b) == 0.0


def test_same_seconds_in_different_episodes_do_not_overlap() -> None:
    """集号是取材身份的一部分：第 3 集的 0-10s 与第 7 集的 0-10s 是两段不同画面。"""
    a = _plan([("ep1", 0.0, 10.0)])
    b = _plan([("ep2", 0.0, 10.0)])
    assert overlap.overlap(a, b) == 0.0


def test_half_shared_gives_one_third() -> None:
    """并集 0-30（30s）、交集 10-20（10s）→ 1/3。Jaccard 不是「占其中一条的比例」。"""
    a = _plan([("ep1", 0.0, 20.0)])
    b = _plan([("ep1", 10.0, 30.0)])
    assert overlap.overlap(a, b) == pytest.approx(10.0 / 30.0)


def test_containment_is_not_reported_as_identical() -> None:
    """短片完全落在长片里：包含率会说 100%，Jaccard 说 20%——后者才对应观感。"""
    long_plan = _plan([("ep1", 0.0, 100.0)])
    short_plan = _plan([("ep1", 10.0, 30.0)])
    assert overlap.overlap(long_plan, short_plan) == pytest.approx(20.0 / 100.0)


def test_touching_segments_are_merged_before_measuring() -> None:
    """相邻段不得被数成两倍素材：不合并时 a 的「总秒数」会是 20 而实际只有 10。"""
    a = _plan([("ep1", 0.0, 5.0), ("ep1", 5.0, 10.0)])
    b = _plan([("ep1", 0.0, 10.0)])
    assert overlap.source_spans(a) == {"ep1": [(0.0, 10.0)]}
    assert overlap.overlap(a, b) == pytest.approx(1.0)


def test_overlapping_segments_within_one_plan_are_merged() -> None:
    a = _plan([("ep1", 0.0, 8.0), ("ep1", 4.0, 12.0)])
    assert overlap.source_spans(a) == {"ep1": [(0.0, 12.0)]}


def test_zero_length_segments_are_ignored() -> None:
    a = _plan([("ep1", 5.0, 5.0), ("ep1", 0.0, 10.0)])
    assert overlap.source_spans(a) == {"ep1": [(0.0, 10.0)]}


def test_both_empty_gives_zero_not_a_division_error() -> None:
    """两条都没画面：无从比起，不该判成「同一部片」，更不该抛 ZeroDivisionError。"""
    empty = PlanData(mode="raw_clip")
    assert overlap.overlap(empty, empty) == 0.0


def test_original_audio_segments_count_as_material() -> None:
    """取材与音频角色无关：raw_clip 全是 original 段，它照样有取材。"""
    a = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=10.0, audio="original")],
    )
    b = _plan([("ep1", 0.0, 10.0)], mode="raw_clip")
    assert overlap.overlap(a, b) == pytest.approx(1.0)


def test_limit_is_the_spec_value() -> None:
    """阈值是规格写死的数，不是可调旋钮：改它就是改规格，必须在这里红一次。"""
    assert overlap.OVERLAP_LIMIT == 0.60
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_overlap.py -q`

Expected: FAIL —— `ModuleNotFoundError: No module named 'dramaclip.engines.narration.overlap'`

- [ ] **Step 3: 写 `overlap.py`**

新建 `service/dramaclip/engines/narration/overlap.py`：

```python
"""取材重叠度量：两条方案共用了多少秒的同一批画面。

规格 §4.3 的安全阀——K 条角度必须是 K 个不同卖点，而不是同一部片切 K 次。
度量单位是**源素材秒**而非场景条数：段长不等，按条数会把「共用两个 25 秒长镜」
算得比「共用五个 3 秒短镜」还轻，而观感上恰恰相反。

只认画面来源（timeline 的 episode_id + start/end），不认音频角色：
original / narration / ducked 三种角色占的是同一段源画面，取材就是取材。
"""

from __future__ import annotations

from dramaclip.engines.narration.models import PlanData

# 规格 §4.3：超阈值直接不出该角度。不是设置项——改它就是改规格。
OVERLAP_LIMIT = 0.60

# episode_id → 已合并的升序区间列表
Spans = dict[str, list[tuple[float, float]]]


def source_spans(plan: PlanData) -> Spans:
    """方案取材 → 每集的**已合并**区间列表（升序、互不重叠）。

    合并是必须的：编排器会产出首尾相接甚至互相覆盖的段（full_narration 逐场景、
    dialogue_narration 逐句吸附台词边界），不合并就会把同一秒源画面数出两次，
    重叠率因此能超过 1.0。零长段直接丢——它不占素材。
    """
    grouped: dict[str, list[tuple[float, float]]] = {}
    for segment in plan.timeline:
        if segment.end <= segment.start:
            continue
        grouped.setdefault(segment.episode_id, []).append((segment.start, segment.end))
    return {episode_id: _merge(spans) for episode_id, spans in grouped.items()}


def overlap(left: PlanData, right: PlanData) -> float:
    """Jaccard：共用秒数 / 两者并集秒数。0=取材全异，1=同一部片。

    取 Jaccard 而非包含率（交集 / 较短一方）：包含率会把「一条 20 秒短片完全落在
    一条 100 秒长片里」报成 100%，而那条短片只占长片五分之一——真正要拦的是
    「两条看起来是同一部片」，Jaccard 量的正是这个。
    并集为空（两条都没有可用画面）时回 0.0：无素材可比重，不该判成同一部片。
    """
    a = source_spans(left)
    b = source_spans(right)
    shared = _intersect(a, b)
    union = _total(a) + _total(b) - shared
    if union <= 0:
        return 0.0
    return shared / union


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _total(spans: Spans) -> float:
    return sum(end - start for group in spans.values() for start, end in group)


def _intersect(left: Spans, right: Spans) -> float:
    """两组已合并区间的交集秒数：逐集双指针，两侧各自有序故线性。"""
    shared = 0.0
    for episode_id, a in left.items():
        b = right.get(episode_id)
        if not b:
            continue
        i = 0
        j = 0
        while i < len(a) and j < len(b):
            start = max(a[i][0], b[j][0])
            end = min(a[i][1], b[j][1])
            if end > start:
                shared += end - start
            if a[i][1] < b[j][1]:
                i += 1
            else:
                j += 1
    return shared
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_overlap.py -q`

Expected: PASS（11 条）

- [ ] **Step 5: 变异检查**

依次手工破坏，每项跑 Step 4 的命令必须变红，改回后绿：

1. `source_spans` 里删掉 `if segment.end <= segment.start: continue` → `test_zero_length_segments_are_ignored` 必须红。
2. `_merge` 的 `start <= merged[-1][1]` 改成 `start < merged[-1][1]` → `test_touching_segments_are_merged_before_measuring` 必须红（首尾相接不再合并，并集翻倍、Jaccard 掉到 0.5）。
3. `overlap` 的返回式改成 `shared / min(_total(a), _total(b))`（即改成包含率）→ `test_containment_is_not_reported_as_identical` 与 `test_half_shared_gives_one_third` 都必须红。
4. `if union <= 0: return 0.0` 整块删掉 → `test_both_empty_gives_zero_not_a_division_error` 必须红（`ZeroDivisionError`）。
5. `_intersect` 的 `b = right.get(episode_id)` 改成 `b = right[episode_id]` → `test_same_seconds_in_different_episodes_do_not_overlap` 必须红（`KeyError`）。
6. `OVERLAP_LIMIT` 改成 `0.9` → `test_limit_is_the_spec_value` 必须红。

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_overlap.py -q`

- [ ] **Step 6: 提交**

```bash
git add service/dramaclip/engines/narration/overlap.py service/tests/engines/narration/test_overlap.py
git commit -m "feat(narration): 取材重叠度量（源素材秒 Jaccard，规格 60% 安全阀）"
```

---

## Task 3: 选题层——`angles.py` 一个模式 K 条互异卖点（**只服务解说类七模式**）

规则类两模式（`raw_clip` / `subtitle_flow`）**不经本模块**，它们的 K 条来自 Task 3b 的全剧 top-K 冲突窗（《定案四》、规格 §4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」）。

**Files:**
- Create: `service/dramaclip/engines/narration/angles.py`
- Modify: `service/dramaclip/engines/narration/scriptwriter.py:160,220,227`（`_format_transcript_episodes` → 公开：定义、docstring 引用、调用点）
- Modify: `service/tests/engines/narration/test_script_input_budget.py:25,32,38,47,53`（跟随改名）
- Create: `service/tests/engines/narration/test_angles.py`

- [ ] **Step 1: 把转写拼装块转成公开函数**

`service/dramaclip/engines/narration/scriptwriter.py`：`_format_transcript_episodes` → `format_transcript_episodes`。**这个名字在本文件里有三处，三处都要改**（实测行号）：

1. `:160` 的 `def _format_transcript_episodes(`；
2. `:227` 的唯一生产调用点 `transcript_block = _format_transcript_episodes(episode_inputs)`；
3. `:220` —— **`write_script_episodes` 的 docstring 里也写着这个名字**（「喂给模型的转写由 `_format_transcript_episodes` 按集分配额取样…」）。原计划说"函数体与 docstring 一字不动"，那样下面那条 grep 门禁就**永远红**（B9 同一类：一个散文命中让"Expected: 无输出"变成假门禁）。docstring 里改成新名，其余一字不动。

另外 `service/tests/engines/narration/test_script_input_budget.py` **确实**引用旧名，共 5 处（实测 `:25,32,38,47,53`，都是 `scriptwriter._format_transcript_episodes(...)`），同批改成新名并一起提交。

改完执行：

Run: `cd service && grep -rn "_format_transcript_episodes" . --include=*.py`

Expected: 无输出。（`grep` 的模式带前导下划线，故新名 `format_transcript_episodes` 不会误命中；`scriptwriter.format_transcript_episodes(...)` 前面是 `.`，`transcript_block = format_transcript_episodes(...)` 前面是空格。）

（这与 P-1.5 把 `_FUNDAMENTALS` / `_dump_trace` / `_clock` 转公开是同一套路：第二个消费者出现时下划线就该去掉，而不是各抄一份。第二个消费者就是 Task 3 Step 4 的 `angles.select_angles`。）

- [ ] **Step 2: 写失败测试**

新建 `service/tests/engines/narration/test_angles.py`：

```python
"""angles.select_angles：K 条卖点互异的取材角度。

降级禁止（规格 §3.3.1）在此的具体形态是「不许凑数」：选题答不出 K 条互异角度时
必须抛，而不是拿重复的、缺字段的、越界集号的凑够 K 条交给下游——那样界面会显示
K 张卡，其中几张是同一部片换了个说法，正是 §4.3 要拦的老虎机。

**每一条拒绝分支都配了变异检查（Step 6）**：上一批实测抓到四条「分支删了测试照绿」
的用例，本文件不接受那种绿灯。
"""

from __future__ import annotations

from typing import Any

import pytest

from dramaclip.engines.narration import angles
from dramaclip.engines.semantic.llm_client import LlmUnavailable

_SETTINGS = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
    "_project_name": "透视眼",
    "_genre": "复仇",
}

# 三集，每集两段转写：够选题看出「这部剧有三条线」
_EPISODES: list[dict[str, Any]] = [
    {
        "number": number,
        "episode_id": f"ep{number}",
        "duration": 60.0,
        "segments": [
            {"start": 1.0, "end": 4.0, "text": f"第 {number} 集台词一"},
            {"start": 5.0, "end": 8.0, "text": f"第 {number} 集台词二"},
        ],
    }
    for number in (1, 2, 3)
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


@pytest.fixture()
def llm(monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeLlm.calls = []
    FakeLlm.queue = []
    monkeypatch.setattr(angles, "LlmClient", FakeLlm)
    return FakeLlm


def _angle(index: int, episode: int) -> dict[str, Any]:
    return {
        "name": f"角度{index}",
        "reason": f"第 {episode} 集这条线最狠",
        "hook": f"第 {episode} 集的开场钩子",
        "episode_numbers": [episode],
    }


def _payload(count: int = 3) -> dict[str, Any]:
    return {"angles": [_angle(i + 1, i + 1) for i in range(count)]}


def _select(**overrides: Any) -> list[angles.AngleBrief]:
    kwargs: dict[str, Any] = {
        "mode": "full_narration",
        "mode_label": "全片解说",
        "k": 3,
        "episode_inputs": _EPISODES,
        "settings": _SETTINGS,
        "excluded": [],
    }
    kwargs.update(overrides)
    return angles.select_angles(**kwargs)


def test_returns_k_distinct_briefs(llm: Any) -> None:
    llm.queue = [_payload()]
    briefs = _select()
    assert [brief.name for brief in briefs] == ["角度1", "角度2", "角度3"]
    assert [brief.episode_numbers for brief in briefs] == [[1], [2], [3]]
    assert all(brief.reason and brief.hook for brief in briefs)


def test_prompt_carries_mode_k_and_transcript(llm: Any) -> None:
    llm.queue = [_payload()]
    _select()
    prompt = FakeLlm.calls[0]
    assert "透视眼" in prompt and "全片解说" in prompt
    assert "需要 3 条卖点互异的取材角度" in prompt
    assert "第 1 集台词一" in prompt and "第 3 集台词二" in prompt, "跨集转写未进 prompt"
    assert "至少一个" in prompt, "「一条方案可以取多集」这条约束没交代给模型（规格 §1）"


def test_prompt_asks_for_an_episode_set(llm: Any) -> None:
    """规格 §1 的「跨集方案」：每条角度给出**全部**取材集，可以是一个也可以是多个。

    2026-09-12 裁决之后不再有"单集模式"这回事，故 `select_angles` 也没有 `cross_episode`
    这个形参了——留着它就是一个恒为 True 的开关，而开关的注释会作为一句关于代码的假话
    被提交（「其余模式的编排器一条片只吃一集」，裁决之后不成立）。
    """
    llm.queue = [{"angles": [dict(_angle(1, 1), episode_numbers=[1, 3])]}]
    briefs = _select(mode="dialogue_narration", mode_label="剧情解说", k=1)
    assert briefs[0].episode_numbers == [1, 3]
    assert "至少一个" in FakeLlm.calls[0]
    assert "恰好一个集号" not in FakeLlm.calls[0], "单集约束的措辞还留着"


def test_excluded_angles_are_listed_in_the_prompt(llm: Any) -> None:
    llm.queue = [_payload()]
    _select(excluded=["复仇线"])
    assert "已存在、不得重复的角度：复仇线" in FakeLlm.calls[0]


def test_unconfigured_llm_raises_before_prompt(llm: Any) -> None:
    settings = dict(_SETTINGS, **{"llm.model": ""})
    with pytest.raises(LlmUnavailable, match="引擎"):
        _select(settings=settings)
    assert FakeLlm.calls == [], "未配置就该在发请求之前拦住"


def test_no_transcript_raises(llm: Any) -> None:
    empty = [{"number": 1, "episode_id": "ep1", "duration": 60.0, "segments": []}]
    with pytest.raises(ValueError, match="无米下锅"):
        _select(episode_inputs=empty)


def test_no_episodes_raises(llm: Any) -> None:
    with pytest.raises(ValueError, match="没有带转写的已完成集"):
        _select(episode_inputs=[])


def test_k_below_one_raises(llm: Any) -> None:
    with pytest.raises(ValueError, match="k 必须"):
        _select(k=0)


def test_fewer_angles_than_k_raises(llm: Any) -> None:
    """只答出 2 条却要求 3 条：不许拿重复的补齐，也不许悄悄把 K 降成 2。"""
    llm.queue = [_payload(2), {"angles": []}]
    with pytest.raises(ValueError, match="只给出 2 条角度，要求 3 条"):
        _select()
    assert len(FakeLlm.calls) == 2, "应重试一次"


def test_duplicate_names_raise(llm: Any) -> None:
    llm.queue = [{"angles": [_angle(1, 1), _angle(1, 2), _angle(3, 3)]}, {"angles": []}]
    with pytest.raises(ValueError, match="角度名重复"):
        _select()


def test_excluded_name_reproposed_raises(llm: Any) -> None:
    payload = {"angles": [dict(_angle(1, 1), name="复仇线"), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="已被排除"):
        _select(excluded=["复仇线"])


def test_empty_field_raises(llm: Any) -> None:
    payload = {"angles": [dict(_angle(1, 1), hook="  "), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="不得为空"):
        _select()


def test_unknown_episode_number_raises(llm: Any) -> None:
    llm.queue = [{"angles": [_angle(1, 9), _angle(2, 2), _angle(3, 3)]}, {"angles": []}]
    with pytest.raises(ValueError, match="取材集不存在"):
        _select()


def test_empty_episode_list_raises(llm: Any) -> None:
    payload = {
        "angles": [dict(_angle(1, 1), episode_numbers=[]), _angle(2, 2), _angle(3, 3)]
    }
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="没有给出取材集"):
        _select()


def test_oversize_name_raises(llm: Any) -> None:
    payload = {"angles": [dict(_angle(1, 1), name="长" * 13), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="超出长度上限"):
        _select()


def test_oversize_hook_raises(llm: Any) -> None:
    payload = {"angles": [dict(_angle(1, 1), hook="钩" * 41), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="钩子超出长度上限"):
        _select()


def test_oversize_reason_raises(llm: Any) -> None:
    """三个长度上限里只有 reason 那条**原本没有用例**（R8）：删掉它的 raise 全套照绿。

    `match` 必须写「理由超出长度上限」这个词：`_MAX_NAME_CHARS` 与 `_MAX_HOOK_CHARS`
    的两条消息分别是「角度名超出长度上限」与「钩子超出长度上限」，
    写"超出长度上限"会让三条分支互相顶包，红的时候不知道红的是哪条。
    """
    payload = {"angles": [dict(_angle(1, 1), reason="理" * 61), _angle(2, 2), _angle(3, 3)]}
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="理由超出长度上限"):
        _select()


def test_missing_angles_array_raises(llm: Any) -> None:
    llm.queue = [{"nope": 1}, {"angles": []}]
    with pytest.raises(ValueError, match="未返回 angles 数组"):
        _select()


def test_non_object_item_raises(llm: Any) -> None:
    llm.queue = [{"angles": ["一条字符串", _angle(2, 2), _angle(3, 3)]}, {"angles": []}]
    with pytest.raises(ValueError, match="非对象项"):
        _select()


def test_malformed_field_type_raises(llm: Any) -> None:
    payload = {
        "angles": [dict(_angle(1, 1), episode_numbers="第一集"), _angle(2, 2), _angle(3, 3)]
    }
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="字段不合法"):
        _select()


def test_extra_angles_are_cut_to_k_not_rejected(llm: Any) -> None:
    """多答不是质量问题：K 是用户的旋钮，取前 K 条即可（与「少答」完全不同，少答必抛）。"""
    llm.queue = [_payload(5)]
    assert len(_select()) == 3


def test_gateway_failure_retries_then_raises(llm: Any) -> None:
    llm.queue = [LlmUnavailable("网关 502"), {"angles": []}]
    with pytest.raises(ValueError, match="未产出 3 条合格角度"):
        _select()
    assert len(FakeLlm.calls) == 2


def test_prompt_block_names_the_selling_point(llm: Any) -> None:
    """成稿 prompt 的角度块：三要素齐备，且措辞由本模块独家持有（两条成稿链共用）。"""
    brief = angles.AngleBrief(
        name="复仇线", reason="第 3 集反杀最狠", hook="他跪着进了门", episode_numbers=[3]
    )
    block = angles.prompt_block(brief)
    assert "复仇线" in block and "第 3 集反杀最狠" in block and "他跪着进了门" in block
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_angles.py -q`

Expected: FAIL —— `ModuleNotFoundError: No module named 'dramaclip.engines.narration.angles'`

- [ ] **Step 4: 写 `angles.py`**

新建 `service/dramaclip/engines/narration/angles.py`：

```python
"""角度选题：一个模式一次 LLM 调用，产出 K 条**卖点互异**的取材角度。

规格 §4.3 定案「用户不能挑角度，角度归模型」，所以「K 条是不是 K 个不同卖点」
完全取决于这一步问得够不够狠。本模块的职责有两半：把「互异」写成模型的硬约束，
以及**在模型答不出互异时判不合格（抛）而不是凑数放行**——凑出来的 K 张卡里有几张
是同一部片换个说法，正是 §4.3 那句「防 K 变成老虎机」要拦的东西。

选题每模式一次、不是每条角度一次：规格 §4.4 的成本账按「每条方案 = 一次成稿 + N 次
配音」记，选题是模式级的固定开销。一个 batch 的选题次数 = 该 batch 里不同模式的数量，
由 narration_plans 的 batch_id + DISTINCT narration_mode 直接数出，不落库。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from dramaclip.engines.narration import scriptwriter
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig, LlmUnavailable

ANGLE_LLM_TIMEOUT_S = 240.0  # 与成稿同量级：要读完整剧摘录再给 K 条角度
_ATTEMPTS = 2
_MAX_NAME_CHARS = 12
_MAX_REASON_CHARS = 60
_MAX_HOOK_CHARS = 40

_SYSTEM_PROMPT = (
    "你是短剧切片分销的选题操盘手。下面给出一部剧的跨集台词转写与一个出片模式，"
    "为这个模式选出若干条**卖点互异**的取材角度：每条切进这部剧的不同一条线"
    "（不同的人物关系、不同的反转、不同的爽点类型），而不是把同一段剧情换个说法。\n"
    '只输出 JSON：{"angles": [{"name": "角度名", "reason": "为什么这条角度值得单出一条片",'
    ' "hook": "这条片的开场钩子首句", "episode_numbers": [集号整数]}]}，不要其他文字。\n'
    f"硬性要求：角度名互不相同且各不超过 {_MAX_NAME_CHARS} 字；"
    f"reason 不超过 {_MAX_REASON_CHARS} 字、hook 不超过 {_MAX_HOOK_CHARS} 字；"
    "各条角度的取材集尽量不重叠——共用素材越多，两条片就越像同一部片；"
    "角度、理由与钩子只能来自给定转写，禁止编造转写之外的事件。"
)


class AngleBrief(BaseModel):
    """一条取材角度：界面卡片四要素里的三项（角度名/理由/钩子）+ 取材集。

    第四项「取材集区间」由落库后的 episode_ids 与 plan_data.timeline 给出，不在此重复；
    hook 只是模型的**声明**，卡片上展示的是成稿后的 plan_data.narration_texts[0].text
    （实际说出口的那句），两者不必一致，故 hook 不落库。

    **本类型也被规则类两模式复用**（`raw_clip` / `subtitle_flow`，见《定案四》与
    Task 6 的 `_rule_variants`）：那两族的条数来自全剧 top-K 冲突窗、不经选题模型，
    但它们同样需要"取材集 + 一个能进 `_plan_one` 的意图"这个形状，于是 `name`/`reason`/
    `hook` 一律为空串、只填 `episode_numbers`。**`_sanitize` 不适用于它们**（它会因
    空 name 抛错），构造方直接实例化。读这个类型时不要假设它一定出自 LLM。
    """

    name: str
    reason: str
    hook: str
    episode_numbers: list[int]


def prompt_block(brief: AngleBrief) -> str:
    """卖点角度进成稿 prompt 的措辞。

    copywriter 与 scriptwriter 两条成稿链共用这一段字：措辞分家会让同一个角度在
    单集模式与跨集模式里被理解成两件事，而角度是本批次唯一的差异化来源。
    """
    return (
        f"\n本条片的取材角度：{brief.name}"
        f"\n这条角度为什么成立：{brief.reason}"
        f"\n开场钩子首句（第一个槽位据此下笔，可改写措辞但不得换卖点）：{brief.hook}"
    )


def _sanitize(
    raw: Any,
    *,
    k: int,
    known_numbers: set[int],
    excluded: list[str],
) -> list[AngleBrief]:
    """逐条验收；任何一条不合格即整批不合格（重试或抛），绝不拿残缺的凑够 K 条。

    多答不算不合格：K 是用户的旋钮，取前 K 条即可。少答必须抛——悄悄把 K 降成 2
    会让界面显示「这个模式只有 2 个卖点」，而真相是模型没答出来。
    """
    items = raw.get("angles") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("选题未返回 angles 数组")
    if len(items) < k:
        raise ValueError(f"选题只给出 {len(items)} 条角度，要求 {k} 条")
    briefs: list[AngleBrief] = []
    seen: set[str] = set()
    for item in items[:k]:
        if not isinstance(item, dict):
            raise ValueError("angles 里存在非对象项")
        try:
            candidate = AngleBrief.model_validate(item)
        except ValidationError as exc:
            raise ValueError(f"角度项字段不合法：{exc}") from exc
        name = candidate.name.strip()
        reason = candidate.reason.strip()
        hook = candidate.hook.strip()
        numbers = sorted(set(candidate.episode_numbers))
        if not name or not reason or not hook:
            raise ValueError("角度名、理由、钩子首句都不得为空")
        if len(name) > _MAX_NAME_CHARS:
            raise ValueError(f"角度名超出长度上限（{_MAX_NAME_CHARS} 字）：{name}")
        if len(reason) > _MAX_REASON_CHARS:
            raise ValueError(f"角度「{name}」的理由超出长度上限（{_MAX_REASON_CHARS} 字）")
        if len(hook) > _MAX_HOOK_CHARS:
            raise ValueError(f"角度「{name}」的钩子超出长度上限（{_MAX_HOOK_CHARS} 字）")
        if name in seen:
            raise ValueError(f"角度名重复：{name}（同名即同卖点）")
        if name in excluded:
            raise ValueError(f"角度「{name}」已被排除，不得重复提出")
        if not numbers:
            raise ValueError(f"角度「{name}」没有给出取材集")
        unknown = [number for number in numbers if number not in known_numbers]
        if unknown:
            raise ValueError(f"角度「{name}」取材集不存在：{unknown}")
        seen.add(name)
        briefs.append(
            AngleBrief(name=name, reason=reason, hook=hook, episode_numbers=numbers)
        )
    return briefs


def select_angles(
    mode: str,
    *,
    mode_label: str,
    k: int,
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    excluded: list[str],
    trace_dir: Path | None = None,
) -> list[AngleBrief]:
    """为一个模式选出 K 条互异角度；答不出互异就抛，不凑数。

    **没有 `cross_episode` 这个形参**（2026-09-12 裁决后删掉的，别顺手加回来）：
    规格 §1 的「跨集方案」是**每个模式**的定义性属性，不是某几个模式的开关。
    一个恒为 True 的开关会把"其余模式一条片只吃一集"这句已经作废的话留在注释里。
    """
    if k < 1:
        raise ValueError(f"方案数 k 必须 ≥ 1，实得 {k}")
    config = LlmConfig.from_settings(settings)
    if not config.configured:
        raise LlmUnavailable(
            "LLM 未配置：取材角度由模型选定（规格 §4.3 角度归模型），"
            "请先在「引擎」页配置文本模型"
        )
    if not episode_inputs:
        raise ValueError("没有带转写的已完成集，无从选题")
    transcript = scriptwriter.format_transcript_episodes(episode_inputs)
    if not transcript:
        raise ValueError("选题无米下锅：所有集都没有台词转写")
    known_numbers = {int(episode["number"]) for episode in episode_inputs}
    excluded_block = (
        f"\n已存在、不得重复的角度：{'、'.join(excluded)}" if excluded else ""
    )
    user_prompt = (
        f"项目：{str(settings.get('_project_name') or '')}"
        f"\n模式：{mode_label}（{mode}）\n"
        f"需要 {k} 条卖点互异的取材角度。\n"
        "每条角度的 episode_numbers 给出这条片要用到的全部集号（至少一个，可多个）："
        "一条方案可以从多集取画面拼在同一条时间轴上。\n"
        f"{excluded_block}\n"
        f"台词转写：\n{transcript}"
    )
    llm = LlmClient(config, timeout_s=ANGLE_LLM_TIMEOUT_S)
    attempts: list[dict[str, Any]] = []
    briefs: list[AngleBrief] | None = None
    for _ in range(_ATTEMPTS):
        try:
            raw = llm.chat_json(_SYSTEM_PROMPT, user_prompt)
            briefs = _sanitize(
                raw,
                k=k,
                known_numbers=known_numbers,
                excluded=excluded,
            )
        except (LlmUnavailable, ValueError, TypeError, KeyError) as exc:
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append({"raw": raw, "accepted": True})
        break
    if trace_dir is not None:
        stamp = time.strftime("%m%d_%H%M%S")
        scriptwriter.dump_trace(
            Path(trace_dir) / f"llm_angles_{mode}_{stamp}.json",
            {"system": _SYSTEM_PROMPT, "user": user_prompt, "attempts": attempts},
        )
    if briefs is None:
        detail = "；".join(str(item["error"]) for item in attempts)
        raise ValueError(f"选题未产出 {k} 条合格角度：{detail}")
    return briefs
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_angles.py tests/engines/narration/test_script_input_budget.py tests/engines/narration/test_scriptwriter.py -q`

Expected: PASS（`test_angles.py` **23** 条 + 另两个文件既有用例全绿。原为 24 条，`test_single_episode_mode_rejects_multi_episode_angle` 随 `cross_episode` 形参一起删除——它钉的那条分支已经不存在，留着它就是一条永远绿、却什么也没守着的用例）

- [ ] **Step 6: 变异检查（本任务的重点，一条都不许省）**

**抛出点实数：`_sanitize` 12 条 + `select_angles` 5 条 = 17 条**（上一轮审查把 `_sanitize` 数成 13、合计 18；2026-09-12 裁决删掉了 `if not cross_episode and len(numbers) != 1` 那条，故为 12/17。R8 补的 `_MAX_REASON_CHARS` 那条**连用例都没有**的分支仍在表里，第 7 行）。上一批的实测修正是这么写的：「新增拒绝分支的用例必须当场做『删掉这行分支看它红不红』的验证，否则它只是把 happy path 又跑了一遍」。逐条破坏、逐条跑 Step 5 的命令、逐条按字节还原：

| # | 破坏（所在函数） | 必须红的用例 |
|---|---|---|
| 1 | `if not isinstance(items, list): raise`（`_sanitize`） | `test_missing_angles_array_raises` |
| 2 | `if len(items) < k: raise`（`_sanitize`） | `test_fewer_angles_than_k_raises` |
| 3 | `if not isinstance(item, dict): raise`（`_sanitize`） | `test_non_object_item_raises` |
| 4 | `except ValidationError: raise ValueError(f"角度项字段不合法：{exc}")`（`_sanitize`） | `test_malformed_field_type_raises` |
| 5 | `if not name or not reason or not hook: raise`（`_sanitize`） | `test_empty_field_raises` |
| 6 | `if len(name) > _MAX_NAME_CHARS: raise`（`_sanitize`） | `test_oversize_name_raises` |
| 7 | **`if len(reason) > _MAX_REASON_CHARS: raise`（`_sanitize`）** | **`test_oversize_reason_raises`（本轮新增，R8）** |
| 8 | `if len(hook) > _MAX_HOOK_CHARS: raise`（`_sanitize`） | `test_oversize_hook_raises` |
| 9 | `if name in seen: raise`（`_sanitize`） | `test_duplicate_names_raise` |
| 10 | `if name in excluded: raise`（`_sanitize`） | `test_excluded_name_reproposed_raises` |
| 11 | `if not numbers: raise`（`_sanitize`） | `test_empty_episode_list_raises` |
| 12 | `if unknown: raise`（`_sanitize`） | `test_unknown_episode_number_raises` |
| 13 | `if k < 1: raise`（`select_angles`） | `test_k_below_one_raises` |
| 14 | `if not config.configured: raise LlmUnavailable(...)`（`select_angles`） | `test_unconfigured_llm_raises_before_prompt`（**含 `FakeLlm.calls == []` 那半条断言**：守卫删掉之后请求就发出去了） |
| 15 | `if not episode_inputs: raise`（`select_angles`） | `test_no_episodes_raises` |
| 16 | `if not transcript: raise`（`select_angles`） | `test_no_transcript_raises` |
| 17 | `if briefs is None: raise` 改成 `return []`（`select_angles` 末尾的汇总抛出） | `test_gateway_failure_retries_then_raises`（改成 `return []` 而不是整块删：删掉会让 mypy 报"缺少返回语句"，那是类型检查红，不是用例红，证不出这条分支被测着） |

**第 3 条的陷阱**（上一批踩过同类）：删掉 `isinstance(item, dict)` 之后 `AngleBrief.model_validate("一条字符串")` 会抛 `ValidationError`，被下一行转成 `ValueError("角度项字段不合法")`——用例仍然红，但红的已经不是这条分支（第 4 条顶着）。所以 `test_non_object_item_raises` 的 `match` 必须写死「非对象项」这个词：**变异后它要因为消息对不上而红，才算真的守着这一行**。同理第 4 条的 `match` 写死「字段不合法」。

**原第 13 条已删除**（`if not cross_episode and len(numbers) != 1` 随裁决消失），后续行号上移，全部 17 行。**`numbers = sorted(set(candidate.episode_numbers))` 那行的去重仍然必须留着**，只是它的用途换了：不再是"单集判定"的前置，而是 Task 6 那道成稿**前**的重叠闸门（`_reject_same_episode_sibling` 按 `frozenset(variant.episode_numbers)` 比）与落库 `episode_numbers` 的规范形。把 `set(...)` 删掉不会让本文件任何用例红（`[1, 1]` 与 `[1]` 在剩下的 12 条分支上表现相同），它由 Task 6 Step 10 的 #13 守着——**这类"本文件测不到、由下游守"的分支必须在此写明落点，否则下一个人会当它是死的而删掉**。

**第 7 条为什么单列一行**：三个长度上限共用"超出长度上限"这个措辞，`match` 只写这一段时三条分支会互相顶包。原计划正是因此漏掉了 reason 那条——它没有用例，删掉 raise 全套照绿。

- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/engines/narration/angles.py service/dramaclip/engines/narration/scriptwriter.py service/tests/engines/narration/test_angles.py service/tests/engines/narration/test_script_input_budget.py
git commit -m "feat(narration): angles 选题层，一个模式一次调用产出 K 条互异卖点"
```

---

## Task 3b: 规则类的"选题"——`pipeline.top_conflict_windows`（全剧 top-K 冲突窗，纯函数）

规格 §4.3 ④：「条数按模式族分别算：**解说类 = K，规则类 = 全剧 top-K 冲突窗**（两者不同源，已由用户定案）」。Task 3 做的是解说类那一半；本任务做规则类那一半。设计依据全部在《定案四》，这里只落代码。

**为什么放在 `pipeline.py` 而不是新开一个模块**：`pipeline.py` 已经是"编排层"的入口（`build_plan` 的模式分派就在这里），而这个榜单与它的发窗结果的唯一用途就是决定"喂给 `build_plan` 的是哪几集的场景"。为一个函数新开文件会让编排知识分两处。（Task 3c 新增的 `casting.py` 是**另一件事**：它管"场景怎么带上集身份、按什么顺序装配"，是数据层；本任务管"取哪几集"，是决定层。两层不合并。）

**为什么不放进 `modes/__init__.py` 或 `modes_w9.py`**：本批次确实要改这两个文件（Task 3c，2026-09-12 裁决后从"不动"清单移出），但改的是**取材结构与盖章处**，不是"取哪几集"这个决定。榜单在编排器**之外**算，是为了让"条数与取材集由全剧冲突榜定"这条规格 §4.3 ④ 的用户定案有一个**唯一**的落点——塞进编排器就会变成九个模式各判一次。

**Files:**
- Modify: `service/dramaclip/engines/narration/pipeline.py`（在 `build_plan` 之后、`build_from_script_episodes` 之前插入**两个**纯函数：`top_conflict_windows` 与 `deal_windows`）
- Create: `service/tests/engines/narration/test_conflict_windows.py`

- [ ] **Step 1: 写失败测试**

新建 `service/tests/engines/narration/test_conflict_windows.py`：

```python
"""规则类两模式的条数来源：全剧 top-K 冲突窗（规格 §4.3 ④）+ 轮转发窗成 K 手。

夹具手搓 ConflictScore，不跑分析层也不跑编排器：这两个函数都是纯函数，把上游拉进来
只会让"榜单排错了"与"冲突分算错了"两种失败混在一起。

`top_conflict_windows` 钉四件事，每件都对应一个真实的坏法：
① 跨集排序（`ConflictScore` 不带集身份，排完不知道那一窗属于谁就没法用）；
② 按集去重（同一集的两窗喂进 `build_raw_clip` 会得到逐字节相同的方案，
   那不是 K 条互异，是 1 条复制 K 份，还会被重叠闸门判成 100% 重叠）；
③ 同分时的确定性（分析层给的是 0-100 的**整数**分，全剧尺度上同分很常见——
   活库实测 333 个场景只有 19 个不同分值；不确定就意味着"整组重规划"两次取到不同的集）；
④ limit < 1 即抛（与 `angles.select_angles` 的 `k < 1` 同一口径）。

`deal_windows` 钉的是**规格 §1 的跨集要求与 §4.3 ④ 的条数要求怎么同时成立**：
一集一条满足条数、违反跨集；把窗轮转发成 K 手、每手若干集，两者都满足，
而且手与手不共集 ⇒ 取材重叠恒为 0。
"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.semantic.models import ConflictScore


def _scene(index: int, score: int, start: float = 0.0) -> ConflictScore:
    return ConflictScore(scene_index=index, start=start, end=start + 8.0, score=score)


def test_picks_the_highest_scoring_window_across_episodes() -> None:
    """榜单是全剧的、也是全集内的：不看"每集第一个场景"，看"每集最狠的那一窗"。

    三集、limit=2，且第 1 集的最高分窗（95）刻意放在场景表的**第二位**：
    只扫每集首个场景的实现会拿它的 70 分去比，把这一集挤出前二——那是"按集取头"
    而不是"全剧取顶"。三集配 limit=2 也让"取满就停"这条可观察（见 Step 5 的 #4）。
    """
    episodes = [
        (1, [_scene(0, 70), _scene(1, 95, 10.0)]),
        (2, [_scene(0, 85)]),
        (3, [_scene(0, 90), _scene(1, 60, 10.0)]),
    ]
    picked = pipeline.top_conflict_windows(episodes, 2)
    assert [(number, scene.score) for number, scene in picked] == [(1, 95), (3, 90)]


def test_one_window_per_episode_so_the_plans_are_not_copies() -> None:
    """同一集的两个高分窗只留一个：留两个就会产出两条逐字节相同的方案。"""
    episodes = [(1, [_scene(0, 95), _scene(1, 94, 10.0), _scene(2, 93, 20.0)])]
    picked = pipeline.top_conflict_windows(episodes, 3)
    assert [number for number, _scene in picked] == [1], "一集出了两条，那不是互异是复制"
    assert picked[0][1].score == 95, "留的必须是该集排名最高的那一窗"


def test_returns_fewer_than_limit_when_episodes_run_out() -> None:
    """规格 §1 允许「每模式产出 1..K 条」：集不够就少出，不许凑数、也不许抛。"""
    episodes = [(1, [_scene(0, 90)]), (2, [_scene(0, 80)])]
    assert len(pipeline.top_conflict_windows(episodes, 5)) == 2


def test_ties_are_broken_deterministically() -> None:
    """同分按 (集号, scene_index) 定序：整组重规划必须可复现。

    分析层的分是 0-100 的整数（`ConflictScore.score: int`），80 集的剧里同分是常态。
    只按 -score 排时 Python 的 sorted 虽然稳定，但稳定于**输入顺序**，而输入顺序来自
    `episodes_repo.list_by_project` —— 那个顺序本身没有契约。故必须显式给次键。
    """
    shuffled = [(2, [_scene(5, 70)]), (1, [_scene(9, 70)]), (2, [_scene(1, 70)])]
    reordered = [(1, [_scene(9, 70)]), (2, [_scene(1, 70)]), (2, [_scene(5, 70)])]
    assert pipeline.top_conflict_windows(shuffled, 2) == pipeline.top_conflict_windows(
        reordered, 2
    )
    assert [(n, s.scene_index) for n, s in pipeline.top_conflict_windows(shuffled, 2)] == [
        (1, 9),
        (2, 1),
    ]


def test_episodes_without_scenes_are_skipped_not_fatal() -> None:
    """某集分析过但一个冲突场景都没出：跳过它，不要抛，也不要塞一个空窗进去。"""
    episodes = [(1, []), (2, [_scene(0, 50)])]
    assert [(n, s.score) for n, s in pipeline.top_conflict_windows(episodes, 3)] == [(2, 50)]


def test_no_episodes_at_all_gives_an_empty_list() -> None:
    """空榜是"无从取窗"，由调用方（api 层）决定怎么响；纯函数不发明错误语义。"""
    assert pipeline.top_conflict_windows([], 3) == []


def test_limit_below_one_raises() -> None:
    with pytest.raises(ValueError, match="limit 必须"):
        pipeline.top_conflict_windows([(1, [_scene(0, 90)])], 0)


def test_deal_windows_deals_round_robin_into_disjoint_hands() -> None:
    """轮转发窗：第 j 手拿排名 j, j+hands, j+2·hands…，手与手**不共集**。

    不共集是这条设计的承重点：规则类两模式的编排器是 (取材集, 该集场景表) 的确定性
    纯函数，两手共集就会共画面，取材重叠直接顶到 60% 阈值上，K 条里只有第一条能落库。
    夹具的输入名次刻意打乱（4,1,9,2,7,3），断言的是**发完之后每手内部升序**。
    """
    windows = [(number, _scene(0, 90 - number)) for number in (4, 1, 9, 2, 7, 3)]
    assert pipeline.deal_windows(windows, 3) == [[2, 4], [1, 7], [3, 9]]


def test_deal_windows_gives_every_hand_a_strong_episode() -> None:
    """轮转而不是切块：切块会让第 1 手独占全剧最狠的几集，三条片的强弱差一个量级。"""
    windows = [(number, _scene(0, 90 - number)) for number in range(1, 7)]
    hands = pipeline.deal_windows(windows, 3)
    assert [hand[0] for hand in hands] == [1, 2, 3], "每手都该拿到一个高分窗"


def test_deal_windows_returns_fewer_hands_than_asked_when_episodes_run_out() -> None:
    """规格 §1 允许「每模式产出 1..K 条」：集不够就少发几手，不许凑数、也不许抛。"""
    windows = [(1, _scene(0, 90)), (2, _scene(0, 80))]
    assert pipeline.deal_windows(windows, 5) == [[1], [2]]


def test_deal_windows_on_an_empty_ranking_is_empty() -> None:
    """空榜是"无从取窗"，由调用方决定怎么响；纯函数不发明错误语义（与上面同一条口径）。"""
    assert pipeline.deal_windows([], 3) == []


def test_deal_windows_below_one_hand_raises() -> None:
    with pytest.raises(ValueError, match="手数 hands 必须"):
        pipeline.deal_windows([(1, _scene(0, 90))], 0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_conflict_windows.py -q`

Expected: FAIL —— **十二条**全红。前七条报 `AttributeError: module 'dramaclip.engines.narration.pipeline' has no attribute 'top_conflict_windows'`，后五条（`test_deal_windows_*`）报 `… has no attribute 'deal_windows'`。两种形态都算"如期失败"；若看到的是 `ImportError` 或 `SyntaxError`，那是测试文件本身写坏了，先修它。

- [ ] **Step 3: 写实现**

`service/dramaclip/engines/narration/pipeline.py`，插在 `build_plan` 之后、`build_from_script_episodes` 之前：

```python
def top_conflict_windows(
    episodes: list[tuple[int, list[ConflictScore]]],
    limit: int,
) -> list[tuple[int, ConflictScore]]:
    """全剧 top-K 冲突窗，**按集去重**（每集只留它排名最高的那一窗），按窗口名次返回。

    规格 §4.3 ④：「条数按模式族分别算：解说类 = K，规则类 = 全剧 top-K 冲突窗
    （两者不同源，已由用户定案）」。规则类两模式（`raw_clip` / `subtitle_flow`）
    不经选题模型（规格 §4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」），
    它们的条数因此必须另有一个来源，就是这个榜单。**本函数不发任何网络请求。**

    为什么按集去重：`build_raw_clip` 与 `build_subtitle_flow` 都是**确定性纯函数**——
    同一组的两个不同窗口喂进去会得到逐字节相同的方案。那不是 K 条互异，是 1 条复制 K 份，
    而且会被 `overlap` 判成 100% 重叠、把 K-1 条报成失败。所以"窗"在这里的作用是把
    **集**排出名次；排完由下面的 `deal_windows` 轮转发成 K 手，一手一条方案。

    **仍然做不到的那一半，写在这里而不是藏在代码里**：让每条方案的内容真的等于它那一窗。
    原先的理由是技术的（`ConflictScore` 不带集身份、`_fit_duration` 按单集截断），
    **那个前提已经被 Task 3c 拆掉了**：集身份有了（`casting.EpisodeScene`），预算也重分了
    （末场景豁免删掉、引子槽位预留 `_INTRO_MAX_S`）。剩下的理由是**产品**的：一个窗是
    3-25s，"内容 = 一窗"会让 `raw_clip` 的每条方案掉到 3-25 秒，而活库实测今天它是
    15.13s（三个场景）。所以本函数交付的是"用全剧冲突榜决定**条数与每条的取材集组合**"，
    不是"每条方案就是一窗"。这个差别记在计划《定案四》末段与《开放问题》#1，不藏在这里。

    排序键 `(-score, 集号, scene_index)`：分析层给的是 0-100 的**整数**分，同分在全剧
    尺度上是常态；只按 -score 排时结果稳定于**输入顺序**，而输入顺序来自
    `episodes_repo.list_by_project`，那个顺序没有契约。补两个次键才有"整组重规划可复现"。

    返回条数可以少于 limit（集不够）。规格 §1 的原话是「每模式产出 **1..K** 条」，
    少出是合法形状；**但调用方必须留痕**（规格 §3.3 静默禁止），见 `api/narration.py`
    的 `_rule_variants`。本函数自己不发明错误语义：空榜就返回空表。

    `limit < 1` 抛 ValueError：与 `angles.select_angles` 的 `k < 1` 同一口径——
    条数是调用方的契约，不该在这里静默变成空表。
    """
    if limit < 1:
        raise ValueError(f"窗口数 limit 必须 ≥ 1，实得 {limit}")
    ranked = sorted(
        ((number, scene) for number, scenes in episodes for scene in scenes),
        key=lambda item: (-item[1].score, item[0], item[1].scene_index),
    )
    picked: list[tuple[int, ConflictScore]] = []
    seen: set[int] = set()
    for number, scene in ranked:
        if number in seen:
            continue
        seen.add(number)
        picked.append((number, scene))
        if len(picked) == limit:
            break
    return picked
```

（`ConflictScore` 在该文件已 import：`from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment`，不需要新增 import。）

- [ ] **Step 3b: 写 `deal_windows`（2026-09-12 裁决新增）**

紧接 `top_conflict_windows` 之后插入。**这一步是规格 §1 的「跨集方案」与 §4.3 ④ 的「规则类 = 全剧 top-K 冲突窗」同时成立的唯一办法**：一集一条满足条数、违反跨集；轮转发成 K 手、每手若干集，两者都满足，而且手间不共集 ⇒ 取材重叠恒为 0。

```python
def deal_windows(
    windows: list[tuple[int, ConflictScore]], hands: int
) -> list[list[int]]:
    """把排名后的冲突窗**轮转**发成 hands 手，每手是它拿到的集号（升序、手间互不相交）。

    规格 §4.3 ④ 定的是**条数**（「规则类 = 全剧 top-K 冲突窗」），规格 §1 定的是
    **每条方案的形状**（「跨集方案」）。一集一条满足前者、违反后者；把窗轮转发成 K 手
    同时满足两者，而且手与手拿到的是**互不相交的集**，于是取材重叠恒为 0——不必等
    `overlap` 事后拦（《定案四》第 2 点原本靠"按集去重"换来的那条性质，跨集之后由
    "手间不共集"接着保证）。

    轮转（第 j 手拿排名 j, j+hands, j+2·hands …）而不是切块（前几集全给第 1 手）：
    切块会让第 1 手独占全剧最狠的几集，三条片的强弱差一个量级；轮转让每手都拿到
    一个高分窗，强弱可比。**实测**（活库十集、K=3）：排名 `[6,7,8,2,3,4,9,10,1,5]`
    → `[[2,5,6,9],[3,7,10],[1,4,8]]`。

    返回条数可以少于 hands（集不够）：规格 §1 允许「每模式产出 1..K 条」，
    少出由调用方留痕（`api/narration.py::_rule_variants`），不在这里发明错误语义。
    **集数 < 2 × hands 时每手会退化成一集**（3 集发 3 手就是 1/1/1），
    那不是缺陷是算术：互不相交的多集手至少需要 2 × hands 集。调用方必须留痕。
    `hands < 1` 抛，与 `top_conflict_windows` 的 `limit < 1` 同一口径。
    """
    if hands < 1:
        raise ValueError(f"手数 hands 必须 ≥ 1，实得 {hands}")
    dealt: list[list[int]] = [[] for _ in range(min(hands, len(windows)))]
    for rank, (number, _scene) in enumerate(windows):
        dealt[rank % len(dealt)].append(number)
    return [sorted(hand) for hand in dealt]
```

（`dealt` 的长度取 `min(hands, len(windows))` 而不是 `hands`：这一行同时兜住了"集不够"与"空榜"两种情况，且让下面的 `rank % len(dealt)` 不可能除零——空榜时 `dealt` 是空表、`for` 一次都不进。把 `min(...)` 写成 `hands` 会在空榜上抛 `ZeroDivisionError`，而空榜是合法输入（`test_deal_windows_on_an_empty_ranking_is_empty` 钉着它）。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_conflict_windows.py tests/engines/narration -q`

Expected: PASS（新增 **12** 条 + `tests/engines/narration` 既有用例全绿——本任务是**纯新增**，不该碰红任何既有用例；若有红的，说明插函数的位置切断了什么，就地修）

- [ ] **Step 5: 变异检查**

下表每一行的"实测输出"都是把破坏后的函数真跑一遍得到的（`D:/tmp` scratch，非推断）：

| # | 破坏 | 必须红的用例 | 实测输出（正确值 → 破坏后） |
|---|---|---|---|
| 1 | 排序键去掉 `-item[1].score`，改成 `key=lambda item: (item[0], item[1].scene_index)` | `test_picks_the_highest_scoring_window_across_episodes` | `[(1,95),(3,90)]` → `[(1,70),(2,85)]` |
| 2 | 删掉 `if number in seen: continue` 与 `seen.add(number)`（即不去重） | `test_one_window_per_episode_so_the_plans_are_not_copies` | 集号序列 `[1]` → `[1,1,1]` |
| 3 | 排序键只留 `-item[1].score`（去掉两个次键） | `test_ties_are_broken_deterministically`——**两条断言都红**（实测）：乱序输入给 `[(2,5),(1,9)]`、重排输入给 `[(1,9),(2,1)]`，两者不再相等（第一条断言红），且都不等于 `[(1,9),(2,1)]`（第二条断言也红） | 见左 |
| 4 | `if len(picked) == limit: break` 改成 `if len(picked) > limit: break`（或整行删掉——两者实测同效） | `test_picks_the_highest_scoring_window_across_episodes` | `[(1,95),(3,90)]` → `[(1,95),(3,90),(2,85)]`（多出 limit 之外的第三条）。**这条变异只有在"集数 > limit"的夹具上才可见**，所以 Step 1 的第一条用例是三集配 limit=2 |
| 5 | `if limit < 1: raise` 整块删掉 | `test_limit_below_one_raises` | 抛 `ValueError("窗口数 limit 必须 ≥ 1，实得 0")` → 静默返回 `[]` |
| 6 | 生成式改成 `for number, scenes in episodes for scene in scenes[:1]`（每集只看首个场景） | `test_picks_the_highest_scoring_window_across_episodes` | `[(1,95),(3,90)]` → `[(3,90),(2,85)]`。**注意它不红 `test_one_window_per_episode…`**（那条夹具里 95 分本来就是首个场景，实测输出不变）——所以第一条用例把最高分窗放在场景表第二位是刻意的 |
| **7** | **`dealt[rank % len(dealt)]` 改成切块：`dealt[min(rank * len(dealt) // max(len(windows), 1), len(dealt) - 1)]`（`deal_windows`）** | **`test_deal_windows_deals_round_robin_into_disjoint_hands` 与 `test_deal_windows_gives_every_hand_a_strong_episode` 两条都红**（实测：两条同时进 FAILED 清单） | 见左。切块仍然给出不相交的手，所以第一条红的是**具体分组**（`[[2,4],[1,7],[3,9]]` → `[[4,1],[9,2],[7,3]]` 排序后 `[[1,4],[2,9],[3,7]]`），第二条红的是"每手都拿到一个高分窗"（切块把 1/2/3 三个最高分集全塞进第 1 手） |
| **8** | **`if hands < 1: raise` 改成 `return []`（`deal_windows`）** | **`test_deal_windows_below_one_hand_raises`** | 抛 `ValueError("手数 hands 必须 ≥ 1，实得 0")` → 静默返回 `[]`。改成 `return []` 而不是整块删：删掉会让 `min(hands, len(windows))` 给出 `range(0)`、函数照样返回 `[]`，mypy 与用例都不红，只有"条数契约被静默吃掉"这件事没人知道 |
| **9** | **`return [sorted(hand) for hand in dealt]` 改成 `return [hand for hand in dealt]`（`deal_windows`）** | **`test_deal_windows_deals_round_robin_into_disjoint_hands`** | `[[2,4],[1,7],[3,9]]` → `[[4,2],[1,7],[9,3]]`（轮转顺序，不是升序）。**这一条不是整洁癖**：`_Variant.episode_numbers` 会原样进 `_reject_same_episode_sibling` 的 `frozenset` 比较（那里无所谓）与 `_casting_for` 的 `sorted(set(...))`（那里也无所谓），但**留痕日志**会按这个顺序念集号，"取第 4、2 集"读起来像排错了 |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_conflict_windows.py -q`

- [ ] **Step 6: 提交**

```bash
git add service/dramaclip/engines/narration/pipeline.py service/tests/engines/narration/test_conflict_windows.py
git commit -m "feat(narration): 全剧冲突窗排名 + 轮转发窗——规则类两模式的条数与取材集来源（规格 §4.3 ④ + §1）"
```

---

## Task 3c: 取材层——`casting.py` + 六个编排器跨集化（**2026-09-12 裁决新增**）

**这个任务整个是裁决的产物。** 规格 §1「每模式产出 1..K 条卖点角度互异的**跨集**方案」里的"跨集"是**方案**的定语；业主拒绝给《定案二》那次收窄签字，所以一条方案的时间轴必须能含来自多集的段。今天只有 `dialogue_narration` 做得到（`pipeline.build_from_script_episodes`），其余六个编排器的首参是 `episode_id: str`、段上的集号一律盖这同一个值。

**为什么改的是编排器而不是在编排器之外"贴集号"**（这是本任务最重要的一个设计决定，证据在《修订记录》C4）：

- **贴不回去。** 段上只有 `start`/`end`，而它们是**集内相对秒**——活库实测十集的场景起点全部从 `0.0` 开始（ep1 前四个 `0.0/5.2/9.9/13.4`、ep2 `0.0/7.9/12.6/19.7`、ep3 `0.0/2.8/5.4/11.0`、ep4 `0.0/2.9/7.8/12.7`）。按 `(start,end)` 反查集号是**歧义**的，而 `export_plan` 拿 `segment.episode_id` 去查 `episode_paths` **查得到、只是查错了**，于是不报错地切出另一集的同一秒。这是本仓最贵的那一类缺陷。
- **排不进去。** 六个编排器**全都自己重排**：`modes/__init__.py:41,60`、`modes_w5.py:31-32`、`modes_w8.py:38-39`、`modes_p2.py:27-28`、`modes_w9.py:53-54` 都有 `sorted(..., key=lambda s: s.start)` 或按 `-score`。外面排好序再喂进去，进去就被按钟表序打散。
- **不动 `ConflictScore`、不加数据库列。** 集身份是**规划期注入**的：`episode_analysis.conflict_scores` 本来就是**按集一行**的 JSON（`migrations/001_init.sql:41`），集身份就是那一行的主键，所以活库已有的十集分析结果一行都不用改、不用重跑分析、不需要迁移。反过来，给 `ConflictScore` 加字段的代价是真的：`api/analysis.py:260` 与 `:411` 都用 `json.dumps([s.model_dump() for s in ...])` 落库，而分析层按集被调用、**不知道自己在为哪一集打分**，新行于是会带上 `episode_number: 0` / `episode_id: ""` 这种"长得像有值"的假值——正是 `loudnorm` 键名那次的失败形态；而且 `api/analysis.py:290-298,319` 会把这份 JSON 原样回给前端。
- **用子类而不是包装类。** 六个编排器里读的全是 `scene.start` / `scene.end` / `scene.score` / `scene.scene_index`；包一层会把这几十处读点改成 `item.scene.start`，而它们与跨集毫无关系。继承之后只有两类点要动：**排序键**与 **`episode_id=` 的盖章处**（实测：12 处盖章 + 8 处排序键）。

**Files:**
- Create: `service/dramaclip/engines/narration/casting.py`
- Create: `service/tests/engines/narration/test_casting.py`
- Create: `service/tests/engines/narration/test_cross_episode_arrangement.py`
- Modify: `service/dramaclip/engines/narration/modes/__init__.py`（`build_raw_clip` / `build_intro` / `_fit_duration` 三个函数整块替换 + import 区）
- Modify: `service/dramaclip/engines/narration/modes_w5.py`（`build_cross` / `build_ultra_short` + import 区）
- Modify: `service/dramaclip/engines/narration/modes_w8.py`（`build_full` + import 区；`_slot_brief` 与两个常量一字不动）
- Modify: `service/dramaclip/engines/narration/modes_p2.py`（`_pick` / `build_dual_host` / `build_monologue` + import 区；四个常量一字不动）
- Modify: `service/dramaclip/engines/narration/modes_w9.py`（`strongest_line` / `build_subtitle_flow` + import 区；`_CTA_TEXT` 等四个常量一字不动）
- Modify: `service/dramaclip/engines/narration/pipeline.py`（`build_plan` 整函数替换；删 `parse_audio_features` 与 `AudioFeatures` import）
- Modify: `service/tests/engines/narration/test_modes.py`、`test_modes_w5.py`、`test_modes_w8.py`、`test_modes_p2.py`、`test_modes_w9.py`、`test_ducked_narration.py`、`tests/api/test_narration_audio_chain.py`、`tests/api/test_narration_no_downgrade.py`（跟随换签名）
- **不改**：`service/dramaclip/api/narration.py`（它的调用点由 Task 6 Step 7 第 11 点整体重写；本任务结束时那个文件会**暂时红**，见 Step 8 的交代）

- [ ] **Step 1: 写失败测试（取材层）**

新建 `service/tests/engines/narration/test_casting.py`：

```python
"""取材层：集身份注入、跨集叙事排序、按集取台词。

夹具全手搓，不跑分析层：本模块是纯函数，把上游拉进来只会让"身份盖错了"与
"冲突分算错了"两种失败混在一起。

这里钉的四件事各对应一个真实的坏法：
① 盖章（`stamp`）——身份丢了，段的 episode_id 就只能是调用方随手给的那一集；
② 叙事排序（`episode_order`）——活库实测十集的场景起点全部从 0.0 开始，
   跨集仍按 start 排会把十集交错成一条谁也不是的时间线；
③ 分数排序的确定性（`score_order`）——活库 333 个场景只有 19 个不同分值，
   同分不补次键就稳定于输入顺序，而输入顺序没有契约；
④ 按集取台词（`dialogue_of`）——摊平一张表按秒过滤会把别的集的对白喂给编剧，
   而编剧被 §3.3.1 要求"只能来自给定台词"，于是它照着错的台词写出一段通顺的假解说。
"""

from __future__ import annotations

import pytest

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting
from dramaclip.engines.semantic.models import ConflictScore


def _scene(index: int, start: float, score: int) -> ConflictScore:
    return ConflictScore(
        scene_index=index, start=start, end=start + 6.0, score=score, reason="冲突"
    )


def _line(start: float, text: str) -> AsrSegment:
    return AsrSegment(start=start, end=start + 2.0, text=text)


def test_stamp_attaches_the_episode_identity_of_the_row_it_came_from() -> None:
    stamped = casting.stamp(
        [
            (3, "ep-three", [_scene(0, 0.0, 90)]),
            (7, "ep-seven", [_scene(0, 0.0, 80), _scene(1, 12.0, 70)]),
        ]
    )
    assert [(item.number, item.episode_id) for item in stamped] == [
        (3, "ep-three"),
        (7, "ep-seven"),
        (7, "ep-seven"),
    ]
    # 原有五个字段一个都不能丢（reason 尤其容易在"逐字段抄"的写法里被漏掉）
    assert [(item.scene_index, item.start, item.score, item.reason) for item in stamped] == [
        (0, 0.0, 90, "冲突"),
        (0, 0.0, 80, "冲突"),
        (1, 12.0, 70, "冲突"),
    ]


def test_stamp_survives_a_new_field_on_conflictscore() -> None:
    """盖章走 model_dump/model_validate，不走逐字段抄。

    逐字段抄在 `ConflictScore` 加字段那天会**静默丢掉**新字段：pydantic 默认忽略未知
    kwargs，照抄旧字段名不报错，只会少一个值（P-1.5《实现定案修正》正是为这件事写的）。
    这条用例把"不丢字段"钉成可执行的断言，而不是注释里的一句提醒。
    """
    payload = _scene(0, 0.0, 90).model_dump()
    assert set(casting.stamp([(1, "ep1", [_scene(0, 0.0, 90)])])[0].model_dump()) >= set(payload)


def test_episode_order_is_broadcast_order_not_clock_order() -> None:
    """两集的 0.0s 是两段不同画面：先按集号、再按集内起点。"""
    late = casting.stamp([(7, "ep7", [_scene(0, 0.0, 90)])])[0]
    early = casting.stamp([(3, "ep3", [_scene(0, 0.0, 40)])])[0]
    ordered = sorted([late, early], key=casting.episode_order)
    assert [item.number for item in ordered] == [3, 7], "按 start 排会把两集的 0.0s 混在一起"


def test_episode_order_breaks_ties_by_scene_index() -> None:
    """同集同起点（零长场景与舍入会让 start 相等）时补 scene_index，才有可复现的顺序。"""
    a = casting.stamp([(1, "ep1", [_scene(5, 0.0, 90)])])[0]
    b = casting.stamp([(1, "ep1", [_scene(2, 0.0, 40)])])[0]
    assert casting.episode_order(b) < casting.episode_order(a)


def test_score_order_is_deterministic_across_input_order() -> None:
    """同分不补次键就稳定于输入顺序，而输入顺序来自 list_by_project，没有契约。"""
    first = casting.stamp([(2, "ep2", [_scene(1, 5.0, 85)]), (1, "ep1", [_scene(9, 5.0, 85)])])
    second = casting.stamp([(1, "ep1", [_scene(9, 5.0, 85)]), (2, "ep2", [_scene(1, 5.0, 85)])])
    assert [min(first, key=casting.score_order).number] == [1]
    assert [min(second, key=casting.score_order).number] == [1]


def test_score_order_puts_the_highest_score_first() -> None:
    scenes = casting.stamp([(1, "ep1", [_scene(0, 0.0, 60), _scene(1, 10.0, 95)])])
    assert min(scenes, key=casting.score_order).score == 95


def test_dialogue_of_returns_only_that_episodes_lines() -> None:
    material = {
        "ep3": casting.EpisodeMaterial(number=3, asr=[_line(12.0, "第三集的话")]),
        "ep7": casting.EpisodeMaterial(number=7, asr=[_line(12.0, "第七集的话")]),
    }
    assert [seg.text for seg in casting.dialogue_of(material, "ep3")] == ["第三集的话"]


def test_dialogue_of_raises_on_a_missing_episode_instead_of_looking_silent() -> None:
    """缺键 ≠ 这一集没有台词：静默返回空表会让编剧写出一段什么都不说的解说。"""
    material = {"ep3": casting.EpisodeMaterial(number=3, asr=[_line(12.0, "第三集的话")])}
    with pytest.raises(ValueError, match="没有装配进来"):
        casting.dialogue_of(material, "ep7")


def test_label_of_names_the_episode_for_the_copy_prompt() -> None:
    material = {"ep3": casting.EpisodeMaterial(number=3, asr=[])}
    assert casting.label_of(material, "ep3") == "第3集"
    with pytest.raises(ValueError, match="无从给出集名"):
        casting.label_of(material, "ep7")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_casting.py -q`

Expected: FAIL —— 九条全红，`ModuleNotFoundError: No module named 'dramaclip.engines.narration.casting'`

- [ ] **Step 3: 写 `casting.py`**

新建 `service/dramaclip/engines/narration/casting.py`：

```python
"""取材层：把「哪几集的场景」变成编排器能直接吃的、带集身份的场景表。

规格 §1「一次提交（剧 × 模式）→ 每模式产出 1..K 条**卖点角度互异**的**跨集**方案」——
"跨集"写在**方案**的定义里，不是写在批次之间的比较里，所以一条方案的时间轴可以
（并且通常会）含来自多集的段。

链路上只缺一层身份，其余早就跨集了：`TimelineSegment.episode_id` 逐段存在
（`engines/narration/models.py`）、`api/export.py::render_export` 的 `episode_paths`
覆盖项目**全部**集、`exporter/encoder.py::export_plan` 的 `zones_cache` 与 `dialogue_zones`
都按 `episode_id` 分键、`overlap.source_spans` 按 `episode_id` 分组合并区间，
而 `dialogue_narration` 已经在生产上出多集成片（`pipeline.build_from_script_episodes`）。
缺的是六个规则编排器：它们吃的是一集的 `ConflictScore` 表，而 `ConflictScore`
（`engines/semantic/models.py`）只有 scene_index/start/end/score/reason，**不带集身份**。
本模块补的就是这一层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.semantic.models import ConflictScore

# episode_id → 该集的取材原料。全链只用**一种**集键（episode_id）：
# `TimelineSegment.episode_id`、`episode_paths`、`zones_cache`、`overlap.source_spans`
# 都是它，再引入"按集号索引"的第二种键只会让两侧各查一半。
MaterialByEpisode = dict[str, "EpisodeMaterial"]


class EpisodeScene(ConflictScore):
    """一个冲突场景 + 它的取材身份（集号用于叙事排序，集 id 用于盖进时间轴段）。

    **继承 `ConflictScore` 而不是包一层**：六个编排器里读的全是 `scene.start` /
    `scene.end` / `scene.score` / `scene.scene_index`，包一层会把这几十处读点改成
    `item.scene.start`，而它们与跨集毫无关系。继承之后只有两类点要动——排序键与
    `episode_id=` 的盖章处。

    **为什么不把这两个字段直接加到 `ConflictScore` 上**（那是最省事的写法，也是错的）：
    `ConflictScore` 是**落库结构**——`engines/semantic/models.py` 的模块 docstring 逐字写着
    「落库结构对齐 docs/service/04 episode_analysis 列」，而 `api/analysis.py` 两处用
    `json.dumps([s.model_dump() for s in ...])` 把它写进 `episode_analysis.conflict_scores`。
    加字段之后新写入的行会带上 `episode_number: 0` / `episode_id: ""`——分析层根本不知道
    自己在为哪一集打分（它按集被调用），于是这两个值恒为假的默认值，而 `0` 与 `""`
    都长得像"有值"。这正是 `loudnorm` 键名那次的失败形态：一个说得通的值被烤进存储，
    下游所有人都会信它。集身份属于**规划期的取材决定**，故落在本模块、由 `stamp` 注入。
    """

    number: int
    episode_id: str


@dataclass(frozen=True)
class EpisodeMaterial:
    """一集的取材原料：集号（人读标签 + 叙事排序）与台词表（编剧的唯一事实来源）。

    台词表**按集分开**是硬要求，不是整洁癖：`start`/`end` 是集内相对秒，活库实测十集的
    场景起点全部从 `0.0` 开始，集与集的秒轴互相覆盖。摊平成一张表之后按秒过滤，
    第 3 集 12-20s 的槽位会捞到第 7 集 12-20s 的对白。
    """

    number: int
    asr: list[AsrSegment]

    @property
    def label(self) -> str:
        """人读集名。进编剧 prompt：跨集时间轴上「画面区间 12.0-20.0s」不说是哪一集
        就等于没说，模型无从判断两个相邻槽位是不是同一条线。"""
        return f"第{self.number}集"


def episode_order(scene: EpisodeScene) -> tuple[int, float, int]:
    """跨集叙事顺序：集号（播出序）→ 集内起点 → scene_index。

    单集时代六个编排器一律 `sorted(scenes, key=lambda s: s.start)`；跨集之后这个键
    **没有意义**：活库实测十集的场景起点全部从 `0.0` 开始，按 start 排会把十集交错成
    一条谁也不是的时间线。剧本驱动模式的叙事顺序来自模型写的剧本
    （`pipeline.build_from_script_episodes` 逐 `script.segments` 顺序装配、按集各持一个
    cursor）；规则选取的场景没有模型，于是唯一不武断的顺序就是**播出序**——
    `episode_number` 已经是这个语义，`api/narration.py::_collect_episode_inputs`
    就按它排（`sorted(episodes, key=lambda ep: int(ep["episode_number"]))`）。

    第三个键 `scene_index` 只为确定性：同集同起点（零长场景与舍入会让 start 相等）时
    不补次键，结果就稳定于输入顺序，而输入顺序来自 `episodes_repo.list_by_project`，
    那个顺序没有契约——与 `pipeline.top_conflict_windows` 补两个次键是同一条理由。
    """
    return (scene.number, scene.start, scene.scene_index)


def score_order(scene: EpisodeScene) -> tuple[int, int, float, int]:
    """冲突分降序 + 确定性次键（集号、集内起点、scene_index）。

    同分在全剧尺度上不是边角情况而是常态：活库实测十集共 **333** 个场景、
    只有 **19** 个不同的分值（平均一个分值上压着 17.5 个场景），最热的分值出现 **45** 次。
    只按 `-score` 排时 Python 的 sorted 虽然稳定，但稳定于**输入顺序**，于是
    「整组重规划两次取到不同的集」——而取材集正是界面卡片四要素之一。
    """
    return (-scene.score, scene.number, scene.start, scene.scene_index)


def stamp(
    scenes_by_episode: list[tuple[int, str, list[ConflictScore]]],
) -> list[EpisodeScene]:
    """逐集盖章：把 (集号, 集 id, 该集场景表) 摊平成带集身份的场景表。

    集身份在这里注入，而不是从库里读：`episode_analysis.conflict_scores` 是**按集一行**的
    JSON（`migrations/001_init.sql` 的 `conflict_scores TEXT -- JSON`，经
    `analysis_repo.get(conn, episode_id)` 取），集身份就是那一行的主键。于是活库里已有的
    十集分析结果**一行都不用改、也不用重跑分析、不需要任何迁移**。

    用 `model_dump()` + `model_validate` 而不是逐字段抄：`ConflictScore` 将来加字段时，
    逐字段抄会**静默丢掉**新字段（pydantic 默认忽略未知 kwargs，照抄旧字段名不报错，
    只会少一个值——P-1.5 的《实现定案修正》就是为这件事写的）。
    """
    stamped: list[EpisodeScene] = []
    for number, episode_id, scenes in scenes_by_episode:
        for scene in scenes:
            payload: dict[str, Any] = scene.model_dump()
            payload["number"] = number
            payload["episode_id"] = episode_id
            stamped.append(EpisodeScene.model_validate(payload))
    return stamped


def dialogue_of(material: MaterialByEpisode, episode_id: str) -> list[AsrSegment]:
    """某一集的台词表。**缺键即抛**，绝不退回"这一集没有台词"。

    缺键与"该集这一区间没有台词"是两件事：后者是素材事实（`modes_w9.strongest_line`
    回 `None`、`copywriter._slot_block` 明写「该区间无台词转写」），前者是装配漏了一集。
    静默当成"没台词"会让编剧对着**别的集**的画面写这一段，而它拿到的台词是空的，
    于是它按 §3.3.1 的禁令「不得编造台词之外的事件」产出一段什么都不说的解说——
    不报错、不降级、成片看着正常，正是本仓最贵的那一类缺陷。
    """
    try:
        return material[episode_id].asr
    except KeyError:
        raise ValueError(
            f"集 {episode_id} 的台词转写没有装配进来：跨集取材的槽位必须按集取台词，"
            "缺键不是「这一集没有台词」"
        ) from None


def label_of(material: MaterialByEpisode, episode_id: str) -> str:
    """某一集的人读集名（进编剧 prompt）。缺键即抛，与 `dialogue_of` 同一口径。"""
    try:
        return material[episode_id].label
    except KeyError:
        raise ValueError(f"集 {episode_id} 没有装配进取材原料表，无从给出集名") from None
```

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_casting.py -q`

Expected: PASS（**9** 条）

- [ ] **Step 4: 六个编排器换签名（逐文件整块替换）**

**改法只有三类点，其余一行不动**：① 首参 `episode_id: str` 删掉、场景表类型换成 `list[EpisodeScene]`；② `sorted(..., key=lambda s: s.start)` → `key=episode_order`、`sorted(..., key=lambda s: -s.score)` → `key=score_order`；③ `episode_id=episode_id` → `episode_id=<该段真正取画的那个场景>.episode_id`。**第 ③ 类是全部风险所在**：盖错一个就是"去另一集的同一秒切画面"，而它不报错。

`service/dramaclip/engines/narration/modes/__init__.py` —— 模块 docstring、import 区、`build_raw_clip`、`build_intro`、`_fit_duration` 五处整块替换（`RAW_CLIP_MIN_SCORE` 等五个常量一字不动）：

```python
"""九种解说模式的编排器（原案第六章）。W4：raw_clip + intro_narration。

场景表带集身份（`casting.EpisodeScene`），故一条方案的时间轴可以含多集的段
（规格 §1 的「跨集方案」）；段的 `episode_id` 由场景自己带，编排器不再有
"这一条片属于哪一集"这个入参。
"""

from __future__ import annotations

from dramaclip.engines.narration.casting import EpisodeScene, episode_order, score_order
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.semantic.models import HighlightSegment
```

（**`ConflictScore` 从这一行里消失了**——它在本文件已无引用，留着就是 ruff F401，而 Step 10 的门禁写着"Expected: 无输出"。`HighlightSegment` 仍被 `build_raw_clip` 的 `len(highlights)` 用着，保留。）

```python
def build_raw_clip(
    scenes: list[EpisodeScene],
    highlights: list[HighlightSegment],
    strategy: StrategySpec,
) -> PlanData:
    """纯原片剪辑编排（原案 6.7）：开场最高冲突 → 时间线 → 截断。零加工（不遮罩）。"""
    if not scenes:
        return PlanData(mode="raw_clip", strategy=strategy)
    candidates = [
        scene
        for scene in scenes
        if scene.score >= RAW_CLIP_MIN_SCORE
        and _RAW_CLIP_MIN_S <= scene.end - scene.start <= _RAW_CLIP_MAX_S
    ]
    # 分数不足时放宽到全部场景（按冲突分取头部，保证可用性）
    if len(candidates) < 3:
        ranked = sorted(scenes, key=score_order)[: max(3, len(highlights))]
        candidates = ranked

    ordered = sorted(candidates, key=episode_order)
    best = max(ordered, key=lambda s: s.score)
    # 身份比较用 `is`，不用 `scene_index`：scene_index 只在**一集内**唯一，
    # 第 1 集的第 4 个场景与第 5 集的第 4 个场景 index 相同，跨集时按 index 判
    # 会认定"开场已经是最高冲突"而不前置。
    if ordered[0] is not best:
        ordered.remove(best)
        ordered.insert(0, best)

    timeline = _fit_duration(ordered, strategy)
    return PlanData(mode="raw_clip", timeline=timeline, strategy=strategy)


def build_intro(
    body_scenes: list[EpisodeScene],
    strategy: StrategySpec,
) -> PlanData:
    """片头解说编排（原案 6.4）：引子旁白段（画面为正文首镜）+ 正片高光（原声）。

    引子文案由编剧层填充；槽位压在哪一段画面即本时间轴首段，段时长在导出阶段由 TTS 实际时长回填。
    正文可跨集：首镜是叙事顺序（`casting.episode_order`）最前的那一集的第一个场景，
    其余高光逐集接在后面，每段的集号各自随场景走。
    """
    ordered = sorted(body_scenes, key=episode_order)
    timeline = _fit_duration(ordered, strategy, intro_first=True)
    if not timeline:
        return PlanData(mode="intro_narration", timeline=timeline, strategy=strategy)
    timeline[0] = timeline[0].model_copy(update={"narration_id": _INTRO_SLOT_ID})
    return PlanData(
        mode="intro_narration",
        timeline=timeline,
        narration_texts=[
            NarrationText(
                id=_INTRO_SLOT_ID,
                brief="片头钩子：两三句把最大冲突抛出来，收尾留悬念，不要复述剧情梗概",
            )
        ],
        strategy=strategy,
    )


def _fit_duration(
    ordered: list[EpisodeScene],
    strategy: StrategySpec,
    *,
    intro_first: bool = False,
) -> list[TimelineSegment]:
    """按时长目标截断：首场景无条件保留，其余在预算内按叙事顺序填充（不打乱顺序）。

    入参必须已按 `casting.episode_order` 排好，本函数不再重排：跨集之后"按 start 排"
    会把十集交错成一条谁也不是的时间线。

    **末场景不再享受预算豁免**（原状是首尾都豁免）。豁免的上界是"一个最长场景"，
    单集时代它够不到预算，所以那条豁免是死的：活库实测十集里最大的一集只有 **204.2**
    场景秒，而 `strategy.max_duration_s` 是 **300**，于是 `used + duration > budget`
    恒不成立。跨集之后两集就能到 **405.8** 场景秒，豁免会把成片推过 `max_duration_s`
    （活库最长单场景 **7.9s** → 最坏 **307.9s**），而九模式真机门禁的时长断言正是
    `duration_s > strategy.max_duration_s`（`scripts/verify_modes.py`）。

    首场景仍然无条件保留：`intro_narration` 的旁白槽位挂在它上面（`build_intro` 的
    `timeline[0]`），丢掉它等于丢掉那条片唯一的解说。
    """
    # 片头解说要在预算里**预留**引子槽位的最坏长度：段长是 TTS 回填时才定的
    # （`pipeline.synthesize_narration_texts` 把段 end 改成 start + 实测音频时长），
    # 编排期只知道 `_INTRO_MAX_S` 这个保守估计。不预留就会两头都吃满预算：
    # 活库实测四集的一手给出 planned 298.80s，而 ep1 的引子实测音频 22.48s
    # （编排期只给它 5.17s），成片因此约 313s——顶穿 `strategy.max_duration_s`=300，
    # 而九模式门禁的时长断言正是 `duration_s > strategy.max_duration_s`。
    budget = strategy.max_duration_s - (_INTRO_MAX_S if intro_first else 0.0)
    kept: list[EpisodeScene] = []
    used = 0.0
    for index, scene in enumerate(ordered):
        duration = scene.end - scene.start
        if index != 0 and used + duration > budget:
            continue
        kept.append(scene)
        used += duration

    segments = [
        TimelineSegment(
            episode_id=scene.episode_id,
            start=round(scene.start, 3),
            end=round(scene.end, 3),
            audio="narration" if intro_first and index == 0 else "original",
        )
        for index, scene in enumerate(kept)
    ]
    if intro_first and segments:
        first = segments[0]
        segments[0] = first.model_copy(
            update={"end": round(min(first.end, first.start + _INTRO_MAX_S), 3)}
        )
    return segments
```

`service/dramaclip/engines/narration/modes_w5.py` —— 模块 docstring、import 区、`build_cross`、`build_ultra_short` 四处整块替换（四个常量一字不动）：

```python
"""W5 模式编排：交叉解说（原案 6.3）与超短悬念版（原案 6.9）。

编排只产出画面结构与旁白槽位，文案一律由 narration.copywriter 生成（无模板兜底）。
场景表带集身份（`casting.EpisodeScene`），一条方案的时间轴可以含多集的段。
"""

from __future__ import annotations

from dramaclip.engines.narration.casting import EpisodeScene, episode_order, score_order
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
```

（**`from dramaclip.engines.semantic.models import ConflictScore` 整行删掉**：本文件改完之后不再有裸 `ConflictScore` 的引用，留着就是 F401。）

```python
def build_cross(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
) -> PlanData:
    """交叉解说：场景原声与旁白交替；旁白压住下一场景开头，承担串联与悬念。

    时间轴：场景1(原声) → 旁白1 → 场景2(原声) → 旁白2 → …（旁白段画面延续下一场景）。
    跨集时"下一场景"可能在另一集，旁白段因此盖的是那一集的开场画面——这是有意的：
    旁白的职责就是串联，串到别的集去正是跨集方案的形状。
    """
    ranked = sorted(scenes, key=score_order)
    picked = sorted(ranked[:6], key=episode_order)  # 取 top 6 按叙事顺序
    if not picked:
        return PlanData(mode="cross_narration", strategy=strategy)

    segments: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    budget = min(strategy.max_duration_s, _CROSS_MAX_S)
    used = 0.0
    for index, scene in enumerate(picked):
        duration = min(scene.end - scene.start, _CROSS_SCENE_S)
        segments.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(scene.start, 3),
                end=round(scene.start + duration, 3),
                audio="original",
            )
        )
        used += duration
        if used >= budget:
            break
        # 场景间插入旁白段（画面延续到下一场景开头；末尾场景后用本场景尾部）
        anchor = picked[index + 1] if index + 1 < len(picked) else scene
        narration_seconds = _HOOK_TTS_FALLBACK_S
        slot_id = f"cross-{index + 1}"
        texts.append(
            NarrationText(
                id=slot_id,
                brief="原声片段之间的串联：承接上一幕，给下一幕留半句钩",
            )
        )
        segments.append(
            TimelineSegment(
                # 集号跟**锚点**走，不跟上一段的 scene 走：这一段画面就是 anchor 的开头。
                # 沿用 scene.episode_id 会让渲染去另一集的同一秒取画面（`export_plan`
                # 按 segment.episode_id 查 episode_paths），出错片而不报错。
                episode_id=anchor.episode_id,
                start=round(anchor.start, 3),
                end=round(anchor.start + narration_seconds, 3),
                audio="narration",
                narration_id=slot_id,
            )
        )
        used += narration_seconds
    return PlanData(
        mode="cross_narration", timeline=segments, narration_texts=texts, strategy=strategy
    )


def build_ultra_short(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
) -> PlanData:
    """超短悬念版（10-20s）：钩子旁白 → 最高冲突原声画面 → 收尾引导。

    跨集只改变**在哪一集**找那个最高冲突场景：本模式的三个段压在同一个场景上，
    它天然是单场景片，取材集因此恒为一集——规格 §1 要的是"一条方案**可以**跨集取画面"，
    不是"每条方案必须≥2 集"，故这里不为跨集而跨集。
    """
    if not scenes:
        return PlanData(mode="ultra_short_hook", strategy=strategy)
    # `min(score_order)` 而不是 `max(key=score)`：后者在同分时取**输入顺序**的第一个，
    # 而输入顺序来自 episodes_repo.list_by_project，没有契约（活库实测 333 个场景只有
    # 19 个不同分值）。score_order 已带 (集号, 起点, scene_index) 三个次键。
    best = min(scenes, key=score_order)
    scene_span = min(best.end - best.start, _ULTRA_CONFLICT_S)
    texts = [
        NarrationText(id="hook-1", brief="开场钩子：一句，最大反差或最狠的悬念，不超过 20 字"),
        NarrationText(
            id="cta-1",
            brief="收尾引导：一句，指向「结局更狠」并引导点击，不超过 15 字",
        ),
    ]
    timeline = [
        TimelineSegment(
            episode_id=best.episode_id,
            start=round(best.start, 3),
            end=round(best.start + _HOOK_TTS_FALLBACK_S, 3),
            audio="narration",
            narration_id=texts[0].id,
        ),
        TimelineSegment(
            episode_id=best.episode_id,
            start=round(best.start, 3),
            end=round(best.start + scene_span, 3),
            audio="original",
        ),
        TimelineSegment(
            episode_id=best.episode_id,
            start=round(best.end - _HOOK_TTS_FALLBACK_S, 3),
            end=round(best.end, 3),
            audio="narration",
            narration_id=texts[1].id,
        ),
    ]
    return PlanData(
        mode="ultra_short_hook", timeline=timeline, narration_texts=texts, strategy=strategy
    )
```

`service/dramaclip/engines/narration/modes_w8.py` —— docstring 末补一行、import 区替换、`build_full` 整块替换。**`_slot_brief` 与 `_MAX_SCENES` / `_FULL_SCENE_S` 一字不动**：槽位职责是**弧内位次**（开篇/推进/高潮/收尾），跨集之后语义完全不变——变的只是"这条弧横跨几集"。

```python
场景表带集身份（`casting.EpisodeScene`），故一条解说弧可以横跨多集。
```

（上面这一行接在模块 docstring 的 `旁白时长在 TTS 合成后回填（机制同 intro/cross），段长随旁白实际时长伸缩。` 之后。）

```python
from dramaclip.engines.narration.casting import EpisodeScene, episode_order, score_order
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
```

（`from dramaclip.engines.semantic.models import ConflictScore` 整行删掉，理由同上。）

```python
def build_full(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
) -> PlanData:
    """全片解说编排：场景按叙事顺序全程覆盖，全部原声压低（ducked）。

    `_slot_brief` 的位置语义在跨集之后仍然成立：位置是**这条解说弧**里的位置，
    不是"第几集的第几场"。开篇/推进/高潮/收尾由弧内位次决定，弧本身可以横跨三集。
    """
    ranked = sorted(scenes, key=score_order)[:_MAX_SCENES]
    picked = sorted(ranked, key=episode_order)
    if not picked:
        return PlanData(mode="full_narration", strategy=strategy)

    count = len(picked)
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        slot_id = f"full-{index + 1}"
        end = round(min(scene.start + _FULL_SCENE_S, scene.end), 3)
        timeline.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(scene.start, 3),
                end=end,
                audio="ducked",
                narration_id=slot_id,
            )
        )
        texts.append(NarrationText(id=slot_id, brief=_slot_brief(index, count, scene.score)))
    return PlanData(
        mode="full_narration", timeline=timeline, narration_texts=texts, strategy=strategy
    )
```

`service/dramaclip/engines/narration/modes_p2.py` —— docstring 末补一行、import 区替换、`_pick` / `build_dual_host` / `build_monologue` 三处整块替换（四个常量与两段 `brief` 文案一字不动）：

```python
场景表带集身份（`casting.EpisodeScene`），故一条对谈/独白弧可以横跨多集。
```

```python
from dramaclip.engines.narration.casting import EpisodeScene, episode_order, score_order
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
```

（`from dramaclip.engines.semantic.models import ConflictScore` 整行删掉。）

```python
def _pick(scenes: list[EpisodeScene]) -> list[EpisodeScene]:
    ranked = sorted(scenes, key=score_order)[:_MAX_SCENES]
    return sorted(ranked, key=episode_order)


def build_dual_host(
    scenes: list[EpisodeScene],
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
            brief = f"{speaker} 开场抛话题：用剧名点出这片为什么值得看"
        elif index == count - 1:
            brief = f"{speaker} 收尾：放狠话评结局并引导看全集"
        elif index % 2 == 1:
            brief = f"{speaker} 接话：情绪反应 + 补一个刚才没说的细节"
        else:
            brief = f"{speaker} 抛下一层：把冲突往更狠处推一句"
        end = round(min(scene.start + _SCENE_S, scene.end), 3)
        timeline.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(scene.start, 3),
                end=end,
                audio="narration",
                narration_id=slot_id,
            )
        )
        texts.append(NarrationText(id=slot_id, brief=brief, voice=voice))
    return PlanData(
        mode="dual_host_chat", timeline=timeline, narration_texts=texts, strategy=strategy
    )


def build_monologue(
    scenes: list[EpisodeScene],
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
            brief = "第一人称开场：主角此刻的处境与误判，一句话"
        elif index == count - 1:
            brief = "第一人称收尾：态度反转落定 + 一句点击引导"
        elif scene.score >= 85:
            brief = "第一人称高潮：这一刻主角想明白了什么，短促、带情绪"
        else:
            brief = "第一人称推进：忍让如何一点点失效"
        end = round(min(scene.start + _SCENE_S, scene.end), 3)
        timeline.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(scene.start, 3),
                end=end,
                audio="narration",
                narration_id=slot_id,
            )
        )
        texts.append(NarrationText(id=slot_id, brief=brief, voice=_VOICE_A))
    return PlanData(
        mode="inner_monologue", timeline=timeline, narration_texts=texts, strategy=strategy
    )
```

⚠️ **`build_dual_host` 的四段 `brief` 字面值必须用 `git diff` 逐字核对**（「开场抛话题」/「收尾」/「接话」/「抛下一层」）。这四句是直接进 LLM prompt 的文案，而 `test_modes_p2.py` 只断言 `text.brief` **非空**与音色交替，**不断言措辞**——改错一个字不会有任何用例红，只会让成片的对谈悄悄变味。本任务对它们一字未改；这一行提醒是给"照抄代码块时手滑"的人准备的（P-1.5 Task 2 的实测修正里就有一条同类：一个中文引号被写成 ASCII 引号，`ast.parse` 当场炸，那是运气好；文案改字不会炸）。

`service/dramaclip/engines/narration/modes_w9.py` —— docstring 末补一行、import 区替换、`strongest_line` 与 `build_subtitle_flow` 整块替换（四个常量一字不动）：

```python
场景表带集身份（`casting.EpisodeScene`），台词表按集分开（`casting.MaterialByEpisode`）。
```

```python
from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting
from dramaclip.engines.narration.casting import EpisodeScene, episode_order, score_order
from dramaclip.engines.narration.line_scoring import score_line
from dramaclip.engines.narration.models import (
    PlanData,
    StrategySpec,
    TimelineSegment,
)
```

（`from dramaclip.engines.semantic.models import ConflictScore` 整行删掉。`AsrSegment` **保留**——`strongest_line` 的第二参仍是 `list[AsrSegment]`，只是调用方现在按集传。）

```python
def strongest_line(
    scene: EpisodeScene,
    segments: list[AsrSegment],
) -> str | None:
    """场景内最强金句：冲突/情绪词密度最高的对白；无对白返回 None。

    `segments` 必须是**这一集**的台词表：start/end 是集内相对秒，活库实测十集的场景
    起点全部从 0.0 开始，拿摊平的表按秒过滤会捞到别的集的句子——字幕上出现一句
    这一集没人说过的话，而它逐字来自本剧，肉眼与耳朵都查不出来。
    """
    inside = [
        segment
        for segment in segments
        if segment.start < scene.end and segment.end > scene.start
    ]
    if not inside:
        return None
    best_text, best_score = None, -1
    for segment in inside:
        duration = segment.end - segment.start
        score = score_line(segment.text, duration)
        if score > best_score:
            best_text, best_score = segment.text, score
    return best_text


def build_subtitle_flow(
    scenes: list[EpisodeScene],
    material: casting.MaterialByEpisode,
    strategy: StrategySpec,
) -> PlanData:
    """金句流编排：top 场景按叙事顺序，每段字幕=该场景最强金句，结尾 CTA 卡片。"""
    ranked = sorted(scenes, key=score_order)[:_MAX_SCENES]
    picked = sorted(ranked, key=episode_order)

    segments: list[TimelineSegment] = []
    for scene in picked:
        duration = min(scene.end - scene.start, _FLOW_SCENE_S)
        segments.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(scene.start, 3),
                end=round(scene.start + duration, 3),
                audio="original",
                subtitle_text=strongest_line(
                    scene, casting.dialogue_of(material, scene.episode_id)
                ),
            )
        )

    # 结尾 CTA 卡片段（复用最后场景尾部画面，climax 居中字幕）
    if picked:
        last = picked[-1]
        segments.append(
            TimelineSegment(
                episode_id=last.episode_id,
                start=round(max(last.end - _CTA_FALLBACK_S, last.start), 3),
                end=round(last.end, 3),
                audio="original",
                subtitle_text=_CTA_TEXT,
            )
        )
    return PlanData(mode="subtitle_flow", timeline=segments, strategy=strategy)
```

- [ ] **Step 5: `pipeline.build_plan` 换签名，并删掉两个死物**

`service/dramaclip/engines/narration/pipeline.py`：

1. import 区改两行（`AudioFeatures` 与 `AsrSegment` 原本同一行，现在只剩后者；新增 casting 那一行，isort 位置在 `from dramaclip.engines.narration import (…)` 之后、`from dramaclip.engines.narration.models import (…)` 之前）：

```python
from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import (
    modes,
    modes_p2,
    modes_w5,
    modes_w8,
    modes_w9,
)
from dramaclip.engines.narration.casting import EpisodeScene, MaterialByEpisode
```

2. `build_plan` 整函数替换：

```python
def build_plan(
    mode: str,
    scenes: list[EpisodeScene],
    highlights: list[HighlightSegment],
    material: MaterialByEpisode,
    settings: dict[str, str],
) -> PlanData:
    """按模式生成编排方案（纯计算，不触 IO）。

    场景表带集身份（`casting.EpisodeScene`），故一条方案的时间轴可以含多集的段
    （规格 §1「每模式产出 1..K 条卖点角度互异的**跨集**方案」）；段的 `episode_id`
    由场景自己带，不再有"这一条片属于哪一集"这个入参。

    **原签名的 `episode_id: str` 与 `audio: AudioFeatures` 两个入参都随本次改写消失**：
    前者被逐场景的集身份取代；后者是**死参数**——原函数体从头到尾没有一处引用 `audio`
    （九个分派分支只往下传 conflict_scores / highlights / asr_segments / strategy），
    而它唯一的调用点为它专门调了一次 `parse_audio_features`。在一个刚被重写的签名里
    留着一个没人读的 `audio` 形参，等于告诉下一个人"音频特征参与编排"。
    """
    strategy = StrategySpec(
        platform="douyin",
        min_duration_s=float(settings.get("strategy.min_duration_s", "30")),
        max_duration_s=float(settings.get("strategy.max_duration_s", "120")),
    )
    if mode == "raw_clip":
        return modes.build_raw_clip(scenes, highlights, strategy)
    if mode == "intro_narration":
        return modes.build_intro(scenes, strategy)
    if mode == "cross_narration":
        return modes_w5.build_cross(scenes, strategy)
    if mode == "ultra_short_hook":
        return modes_w5.build_ultra_short(scenes, strategy)
    if mode == "dialogue_narration":
        raise ValueError(
            "剧情解说为剧本驱动，不经规则编排（走 script_driver.script_dialogue_plan）"
        )
    if mode == "full_narration":
        return modes_w8.build_full(scenes, strategy)
    if mode == "subtitle_flow":
        return modes_w9.build_subtitle_flow(scenes, material, strategy)
    if mode == "dual_host_chat":
        return modes_p2.build_dual_host(scenes, strategy)
    if mode == "inner_monologue":
        return modes_p2.build_monologue(scenes, strategy)
    raise ValueError(f"模式暂未支持: {mode}（{MODE_LABELS.get(mode, mode)} 将随后续阶段启用）")
```

3. **删掉 `parse_audio_features` 整个函数**（实测 `pipeline.py:177-180`，四行）。它随 `audio` 形参一起失去唯一调用点（`api/narration.py:243`，那一行由 Task 6 Step 7 第 11 点的 `_plan_one` 重写带走）。留着它就是一个"看起来还有人会用"的公开助手。

Run: `cd service && grep -rn "parse_audio_features\|AudioFeatures" dramaclip/engines/narration/ --include=*.py`

Expected: **无输出**。（`AudioFeatures` 在 `engines/narration/` 下的唯一两处引用是 `pipeline.py:15` 的 import 与 `:54` 的形参，两者都随本步消失。`engines/analysis/models.py` 的定义、`engines/semantic/ranker.py` 与 `api/analysis.py` 的使用**都不在这个 grep 的路径里**，它们照旧。）

- [ ] **Step 6: 迁既有测试调用点（实测 24 处 `build_*` + 3 处 `build_plan`）**

逐个文件给字面替换。**每个文件的 import 区都是 ruff 的 isort 实跑结果**（上一批为 B7b 付过账：给"新增一行"这种指令，执行者照做就会 I001，而门禁写着"Expected: 无输出"）。

| 文件 | import 区（整块替换后的字面内容） | 调用点替换 |
|---|---|---|
| `tests/engines/narration/test_modes.py` | 删 `from dramaclip.engines.analysis.models import AudioFeatures` 整行；在 `from dramaclip.engines.narration import pipeline` 之后加 `from dramaclip.engines.narration.casting import stamp` | 5 处 `build_raw_clip("ep1", …)` / `build_intro("ep1", …)` → `build_raw_clip(stamp([(1, "ep1", _scenes())]), …)`；`build_intro("ep1", [], _STRATEGY)` → `build_intro([], _STRATEGY)`；`test_highlights_not_required` 那行**必须折成四行**（实测 114 字符 → E501）：<br>`    plan = build_raw_clip(`<br>`        stamp([(1, "ep1", _scenes())]),`<br>`        [HighlightSegment(start=0, end=6, score=80)],`<br>`        _STRATEGY,`<br>`    )`；`test_build_plan_refuses_dialogue_rule_arrangement` 的实参从 `("dialogue_narration", "ep1", _scenes(), [], [], AudioFeatures(), {})` 改成 `("dialogue_narration", stamp([(1, "ep1", _scenes())]), [], {}, {})`；**并把 `test_raw_clip_opens_with_highest_conflict` 的断言消息从「截断预算（含首尾豁免）」改成「截断预算（只有首场景豁免）」、上界从 `max_duration_s + 12` 收紧到 `max_duration_s`**（豁免已删，留着 `+12` 就是一条松掉的断言，而那句散文会作为关于代码的假话被提交——B9 同类） |
| `tests/engines/narration/test_modes_w5.py` | 加 `from dramaclip.engines.narration.casting import stamp`（isort 位置：`models` 那行**之前**） | 4 处：`build_cross("ep1", _scenes(), X)` → `build_cross(stamp([(1, "ep1", _scenes())]), X)`（两处）；`build_ultra_short("ep1", _scenes(), _STRATEGY)` 同法；`build_ultra_short("ep1", [], _STRATEGY)` → `build_ultra_short([], _STRATEGY)` |
| `tests/engines/narration/test_modes_w8.py` | 同上 | 4 处 `build_full("ep1", _scenes(), _STRATEGY)` → `build_full(stamp([(1, "ep1", _scenes())]), _STRATEGY)`；`build_full("ep1", [], _STRATEGY)` → `build_full([], _STRATEGY)` |
| `tests/engines/narration/test_modes_p2.py` | 同上 | 3 处：`build_dual_host` 两处、`build_monologue` 一处；空表那处 → `build_dual_host([], _STRATEGY)` |
| `tests/engines/narration/test_modes_w9.py` | 加 `from dramaclip.engines.narration import casting` 与 `from dramaclip.engines.narration.casting import stamp`（两行，isort 顺序：`import casting` 在 `from … import stamp` 之前；`models` 那行排在两者之后） | 4 处 `build_subtitle_flow("ep1", _scenes(), _segments(), _STRATEGY)` → `build_subtitle_flow(stamp([(1, "ep1", _scenes())]), _material(), _STRATEGY)`；空场景那处 → `build_subtitle_flow([], _material(), _STRATEGY)`。**并在 `_segments()` 之后新增**：<br>`def _material() -> casting.MaterialByEpisode:`<br>`    return {"ep1": casting.EpisodeMaterial(number=1, asr=_segments())}` |
| `tests/engines/narration/test_ducked_narration.py` | 加 `from dramaclip.engines.narration.casting import stamp` | `:149` 那行**必须折成三行**（实测 103 字符 → E501）：<br>`    plan = build_full(`<br>`        stamp([(1, "ep1", scenes)]), StrategySpec(min_duration_s=10, max_duration_s=120)`<br>`    )` |
| `tests/api/test_narration_audio_chain.py` | 加 `from dramaclip.engines.narration.casting import stamp` | `_full_plan` 里 `build_full(episode_id, _scenes(), StrategySpec(min_duration_s=10))` → `build_full(stamp([(1, episode_id, _scenes())]), StrategySpec(min_duration_s=10))`（**保留 `episode_id` 这个形参名**，它由夹具传入，只是现在当集 id 用） |
| `tests/api/test_narration_no_downgrade.py` | 加 `from dramaclip.engines.narration.casting import stamp` | 两处 `build_full("ep1", _SCENES, StrategySpec(min_duration_s=10))` → `build_full(stamp([(1, "ep1", _SCENES)]), StrategySpec(min_duration_s=10))` |

- [ ] **Step 7: 写跨集性质测试**

新建 `service/tests/engines/narration/test_cross_episode_arrangement.py`（**单集行为由各 `test_modes*.py` 守着，本文件只钉跨集才存在的性质**）：

```python
"""六个规则编排器的跨集取材（规格 §1「每模式产出 1..K 条…跨集方案」）。

单集行为由各 `test_modes*.py` 守着；本文件只钉**跨集才存在**的那些性质。
每一条都对应一个真实的坏法，且每条都做过变异检查（见 Step 9）：

① 段的集号必须来自**它自己的场景**，不来自某个"这一条片属于哪一集"的入参
   ——否则渲染会去另一集的同一秒取画面（`export_plan` 按 `segment.episode_id`
   查 `episode_paths`），出错片而不报错；
② 叙事顺序是播出序（集号 → 集内起点），不是钟表序——活库实测十集的场景起点
   全部从 `0.0` 开始，按 start 排会把十集交错；
③ `_fit_duration` 的预算不得被末场景豁免顶穿——单集时代够不到预算（活库最大
   单集 204.2 场景秒 < `strategy.max_duration_s` 300），跨集两集就到 405.8；
④ `scene_index` 只在**一集内**唯一，跨集时用它做身份比较会认错场景；
⑤ `subtitle_flow` 的金句必须取自该场景**自己那一集**的台词表。
"""

from __future__ import annotations

from dramaclip.engines.analysis.models import AsrSegment
from dramaclip.engines.narration import casting
from dramaclip.engines.narration.casting import stamp
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.narration.modes import build_intro, build_raw_clip
from dramaclip.engines.narration.modes_p2 import build_dual_host, build_monologue
from dramaclip.engines.narration.modes_w5 import build_cross, build_ultra_short
from dramaclip.engines.narration.modes_w8 import build_full
from dramaclip.engines.narration.modes_w9 import build_subtitle_flow
from dramaclip.engines.semantic.models import ConflictScore
from tests.engines.narration.conftest import assert_slots_paired

# 预算刻意给小：让"顶穿预算"这条在两三个场景上就能观察到，不必造几十集夹具
_STRATEGY = StrategySpec(min_duration_s=10, max_duration_s=30)
# intro 要另给一档：`_fit_duration` 在 intro_first 时会从预算里**预留** _INTRO_MAX_S=30s
# 给引子槽位（段长要等 TTS 回填才知道），30s 的预算会被预留吃光、只剩首场景。
_STRATEGY_INTRO = StrategySpec(min_duration_s=10, max_duration_s=90)


def _scene(index: int, start: float, score: int) -> ConflictScore:
    return ConflictScore(scene_index=index, start=start, end=start + 6.0, score=score)


def _two_episodes() -> list[casting.EpisodeScene]:
    """两集，**集内起点完全重合**（都从 0.0 开始）：这是活库的真实形状，不是刁钻构造。"""
    return stamp(
        [
            (1, "ep1", [_scene(0, 0.0, 60), _scene(1, 10.0, 90)]),
            (2, "ep2", [_scene(0, 0.0, 95), _scene(1, 10.0, 40)]),
        ]
    )


def _material() -> casting.MaterialByEpisode:
    return {
        "ep1": casting.EpisodeMaterial(number=1, asr=[]),
        "ep2": casting.EpisodeMaterial(number=2, asr=[]),
    }


def test_every_builder_stamps_the_episode_of_each_segment() -> None:
    """六个编排器逐段盖自己场景的集号；两集都必须在时间轴上出现。"""
    scenes = _two_episodes()
    plans = {
        "raw_clip": build_raw_clip(scenes, [], _STRATEGY),
        "intro_narration": build_intro(scenes, _STRATEGY_INTRO),
        "cross_narration": build_cross(scenes, _STRATEGY),
        "ultra_short_hook": build_ultra_short(scenes, _STRATEGY),
        "full_narration": build_full(scenes, _STRATEGY),
        "dual_host_chat": build_dual_host(scenes, _STRATEGY),
        "inner_monologue": build_monologue(scenes, _STRATEGY),
        "subtitle_flow": build_subtitle_flow(scenes, _material(), _STRATEGY),
    }
    for mode, plan in plans.items():
        assert plan.timeline, f"{mode} 出了个空时间轴"
        used = {segment.episode_id for segment in plan.timeline}
        assert used <= {"ep1", "ep2"}, f"{mode} 盖了个不存在的集号：{used}"
        if mode == "ultra_short_hook":
            continue  # 单场景片，恒为一集；它自己的用例钉"取的是全剧最高分那一集"
        assert "ep2" in used, (
            f"{mode} 的时间轴里没有第 2 集——那不是跨集方案，是单集方案换了个说法"
        )


def test_ultra_short_is_a_single_scene_film_and_says_which_episode() -> None:
    """超短悬念版三个段压在同一个场景上，故恒为一集——但那一集必须是**全剧**最高分那集。

    规格 §1 要的是一条方案**可以**跨集取画面，不是每条方案**必须** ≥2 集。
    为跨集而把 15 秒的悬念版拆成两集，会毁掉这个模式的全部卖点（一个镜头一个反差）。
    """
    plan = build_ultra_short(_two_episodes(), _STRATEGY)
    assert {segment.episode_id for segment in plan.timeline} == {"ep2"}, (
        "95 分在 ep2，取的却是别的集"
    )
    assert len(plan.timeline) == 3


def test_ultra_short_breaks_a_cross_episode_score_tie_by_episode_number() -> None:
    """同分取**集号小**的那一集，而不是取输入顺序里的第一个。

    夹具把 ep2 排在输入的第一位、两集同为 95 分：`max(scenes, key=lambda s: s.score)`
    会返回输入顺序里的第一个（ep2），于是"整组重规划"两次可能取到不同的集——
    而输入顺序来自 `episodes_repo.list_by_project`，那个顺序没有契约。
    活库实测 333 个场景只有 19 个不同分值，同分不是边角情况。
    """
    tied = stamp(
        [
            (2, "ep2", [_scene(0, 0.0, 95)]),
            (1, "ep1", [_scene(0, 0.0, 95)]),
        ]
    )
    plan = build_ultra_short(tied, _STRATEGY)
    assert {segment.episode_id for segment in plan.timeline} == {"ep1"}, (
        "同分该按集号定序（取 ep1），实取的是输入顺序里的第一个"
    )


def test_segments_follow_broadcast_order_not_clock_order() -> None:
    """两集的 0.0s 是两段不同画面：先按集号、再按集内起点。

    按 start 排会得到 ep1@0、ep2@0、ep1@10、ep2@10 —— 十集这么交错出来的时间线
    谁也不是，而它不报错、不降级，成片看着像"剪得很碎"。
    """
    plan = build_full(_two_episodes(), _STRATEGY)
    assert [(segment.episode_id, segment.start) for segment in plan.timeline] == [
        ("ep1", 0.0),
        ("ep1", 10.0),
        ("ep2", 0.0),
        ("ep2", 10.0),
    ]


def test_fit_duration_never_overshoots_the_budget() -> None:
    """末场景不再享受预算豁免：跨集之后豁免会把成片顶过 `strategy.max_duration_s`。

    夹具按活库的量级造：每集 20 个 7.9s 的场景（活库实测最长单场景就是 7.9s），
    三集共 474 场景秒，预算 30s。**实测**：新实现给出 23.7s（≤30），恢复末场景豁免
    给出 **31.6s**（>30）——而九模式门禁的时长断言是 `duration_s > strategy.max_duration_s`
    即失败。活库尺度上同一个差值是 300 → **307.9s**。
    """
    scenes = stamp(
        [
            (
                number,
                f"ep{number}",
                [_scene(index, index * 8.0, 90) for index in range(20)],
            )
            for number in (1, 2, 3)
        ]
    )
    strategy = StrategySpec(min_duration_s=10, max_duration_s=30)
    for mode, plan in (
        ("raw_clip", build_raw_clip(scenes, [], strategy)),
        ("intro_narration", build_intro(scenes, strategy)),
    ):
        total = sum(segment.end - segment.start for segment in plan.timeline)
        assert total <= strategy.max_duration_s, f"{mode} 顶穿了预算：{total}s > 30s"


def test_intro_reserves_headroom_for_the_hook_slot() -> None:
    """引子槽位的段长是 TTS 回填时才定的，故编排期必须给它**预留**预算。

    不预留就两头都吃满：活库实测四集的一手 planned 298.80s、引子实测音频 22.48s
    （编排期只给它 5.17s）⇒ 成片约 313s，顶穿 `strategy.max_duration_s`=300，
    而九模式门禁的时长断言正是 `duration_s > strategy.max_duration_s`。
    预留 `_INTRO_MAX_S` 之后同一手 planned 269.06s ⇒ 成片约 283.6s，落回窗口内。
    """
    scenes = stamp(
        [
            (number, f"ep{number}", [_scene(index, index * 8.0, 90) for index in range(20)])
            for number in (1, 2, 3)
        ]
    )
    strategy = StrategySpec(min_duration_s=10, max_duration_s=300)
    plan = build_intro(scenes, strategy)
    total = sum(segment.end - segment.start for segment in plan.timeline)
    assert total <= strategy.max_duration_s - 30.0, (
        f"引子没预留槽位余量：正文吃掉了 {total}s，预算只有 {strategy.max_duration_s}s"
    )


def test_intro_keeps_its_slot_when_the_first_scene_alone_exceeds_the_budget() -> None:
    """首场景仍然无条件保留：`intro_narration` 的旁白槽位挂在它上面，丢了就没有解说。"""
    scenes = stamp([(1, "ep1", [ConflictScore(scene_index=0, start=0.0, end=90.0, score=90)])])
    plan = build_intro(scenes, StrategySpec(min_duration_s=10, max_duration_s=30))
    assert len(plan.timeline) == 1
    assert plan.timeline[0].narration_id == "intro-1"
    assert_slots_paired(plan, "intro_narration")


def test_raw_clip_best_first_swap_survives_a_scene_index_collision() -> None:
    """`scene_index` 只在一集内唯一：跨集时按 index 判"开场是不是最高分"会认错场景。

    夹具让两集都有一个 `scene_index=1` 的场景，且最高分那个在 ep2：
    按 index 比较的实现会认定"开场已经是最高分"而不前置，按身份比较才会换。
    """
    scenes = stamp(
        [
            (1, "ep1", [_scene(1, 0.0, 72), _scene(2, 10.0, 75)]),
            (2, "ep2", [_scene(1, 0.0, 99)]),
        ]
    )
    plan = build_raw_clip(scenes, [], _STRATEGY)
    first = plan.timeline[0]
    assert first.episode_id == "ep2" and first.start == 0.0, (
        f"开场应为全剧最高冲突（ep2@0.0，99 分），实得 {first.episode_id}@{first.start}"
    )


def test_cross_narration_segment_carries_the_anchor_episode() -> None:
    """旁白段的画面延续到**下一个场景**，故它的集号必须是锚点的集号。

    沿用上一个原声段的集号会让渲染去另一集的同一秒取画面——`export_plan` 按
    `segment.episode_id` 查 `episode_paths`，查得到、只是查错了，于是不报错地出错片。
    """
    scenes = stamp(
        [
            (1, "ep1", [_scene(0, 0.0, 95)]),
            (2, "ep2", [_scene(0, 0.0, 90)]),
        ]
    )
    plan = build_cross(scenes, _STRATEGY)
    narration_segments = [s for s in plan.timeline if s.audio == "narration"]
    assert narration_segments, "夹具前提塌了：交叉解说必须有旁白段"
    for segment in narration_segments:
        assert segment.episode_id in {"ep1", "ep2"}
    # picked 按播出序是 [ep1@0, ep2@0]，故第一个旁白段的锚点是 ep2
    assert narration_segments[0].episode_id == "ep2", (
        f"旁白段该盖锚点（ep2）的画面，实得 {narration_segments[0].episode_id}"
    )


def test_subtitle_flow_takes_each_line_from_its_own_episode() -> None:
    """金句必须取自该场景**自己那一集**的台词表：两集秒轴重合时会捞到别集的句子。"""
    scenes = stamp(
        [
            (1, "ep1", [_scene(0, 0.0, 95)]),
            (2, "ep2", [_scene(0, 0.0, 90)]),
        ]
    )
    material: casting.MaterialByEpisode = {
        "ep1": casting.EpisodeMaterial(
            number=1, asr=[AsrSegment(start=1.0, end=4.0, text="第一集的金句")]
        ),
        "ep2": casting.EpisodeMaterial(
            number=2, asr=[AsrSegment(start=1.0, end=4.0, text="第二集的金句")]
        ),
    }
    plan = build_subtitle_flow(scenes, material, _STRATEGY)
    # 按**段序号**取值，不按集号：末尾还有一个 CTA 卡片段复用最后一集的尾部画面，
    # 用 {episode_id: text} 收会把两个 ep2 段压成一个，断言就在读错的对象。
    lines = [(segment.episode_id, segment.subtitle_text) for segment in plan.timeline]
    assert lines == [
        ("ep1", "第一集的金句"),
        ("ep2", "第二集的金句"),
        ("ep2", "结局太爽了！点下方看全集 →"),
    ], lines
```

- [ ] **Step 8: 跑测试确认通过（含活库实测）**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration tests/api/test_narration_audio_chain.py tests/api/test_narration_no_downgrade.py -q`

Expected: PASS（`test_casting.py` 9 条 + `test_cross_episode_arrangement.py` 10 条 + `test_conflict_windows.py` 12 条 + `tests/engines/narration` 既有用例全绿；scratch 实测这一组共 **127** 条通过）

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api -q 2>&1 | tail -20`

Expected: **红，且红的地方全部可预期**——`tests/api/test_produce.py`（以及 Task 6 改名后的 `test_plan_variants.py`）里打 `narration.produce` / `generate_plans` 的用例，因为 `api/narration.py` 还在用**旧签名**调 `build_plan`（`_generate_one` 传七个位置参数，新签名只收五个）。**这不是本任务要修的**：`api/narration.py` 的调用点由 Task 6 Step 7 第 11 点整体重写。逐条核对红的用例都落在 `tests/api/test_produce.py`、`tests/api/test_data_paths.py` 与 `tests/api/test_narration_*` 之外的**编排调用点**上；若红在别处，那是本任务改坏了什么，就地修掉。

**活库实测（只读 `data/data.db`，用真编排器算 planned 源秒，不渲染、不写库）**——这张表是本任务唯一能证明"跨集真的发生了、且没有顶穿预算"的证据，落地后照抄一遍填进《Task N 落地后的实测修正》。取材集用规则类的第一手 `[2,5,6,9]`（活库十集按 top 窗排名 `[6,7,8,2,3,4,9,10,1,5]`、`deal_windows(…, 3)` 的第一手）；`strategy.max_duration_s` 取活库 settings 实测值 **300**：

| 模式 | ep1 单集 planned(s) | 跨集一手 planned(s) | 段数（单集→跨集） | 时间轴上的集数 |
|---|---|---|---|---|
| `raw_clip` | 15.13 | **117.89** | 3 → 21 | **4** |
| `intro_narration` | 192.20 | **269.06**（预留前是 298.80） | 46 → 58 | **2**（见下） |
| `cross_narration` | 51.57 | 57.24 | 12 → 12 | **3** |
| `ultra_short_hook` | 14.77 | 14.40 | 3 → 3 | **1**（设计如此，C13） |
| `full_narration` | 34.50 | 42.04 | 8 → 8 | **3** |
| `subtitle_flow` | 30.57 | 36.24 | 7 → 7 | **3** |
| `dual_host_chat` | 34.50 | 42.04 | 8 → 8 | **3** |
| `inner_monologue` | 34.50 | 42.04 | 8 → 8 | **3** |

**读这张表的三件事**：

1. **`intro_narration` 一手点了 4 集，时间轴上只出现 2 集**。不是 bug：它没有场景条数上限（与其余五个模式的 `_MAX_SCENES` 不同），`_fit_duration` 按播出序填充、预算 270s 在 ep5 就用完了，ep6/ep9 一帧都拿不到。**后果是落库的 `episode_ids` 必须从建好的时间轴反推**，不能抄角度点名的那份，否则卡片的「取材集区间」会列两集没出现的集（§9.5 假文案类）。Task 6 Step 7 第 11 点的 `_plan_one` 因此写 `used_ids = sorted({segment.episode_id for segment in plan.timeline})`——与 `script_driver.script_dialogue_plan` 同一个口径（它的 `used_ids` 逐字就是这么算的），配 `test_episode_ids_come_from_the_timeline_not_the_brief`。
2. **planned 源秒 ≠ 成片秒**：`synthesize_narration_texts` 会把每个旁白/ducked 段的 `end` 改成 `start + 实测音频时长`。P-1.5 Task 10 的实测比值（成片/planned）是 `intro_narration` 1.09、`full_narration` 1.44、`dual_host_chat` 1.71、`inner_monologue` 1.45、`cross_narration` 1.25、`ultra_short_hook` 1.05、`raw_clip`/`subtitle_flow` 1.02–1.06。按这些比值推跨集成片：最长的 `intro_narration` ≈ 269.06 × 1.09 ≈ **293s**（预留前是 313s，**顶穿 300**），其余全部 ≤ 120s。这就是 Step 4 那两处预算改动的全部理由，也是 Task 9 Step 2.8 断言"门禁时长阈值一个字都不用改"的依据。
3. **`raw_clip` 从 15s 变成 118s**（7.8 倍）。这是本裁决最容易被低估的一条产品后果：它不再是一条"三镜头爽点剪辑"，而是一条两分钟的多集混剪。阈值上合法（≤300）、门禁上会过，但**形态变了**。已写进《开放问题》#1 与交付报告，交业主定夺。

- [ ] **Step 9: 变异检查**

下表每一行的"必须红的用例"都是把破坏后的代码真跑一遍得到的（`D:/tmp` scratch 装配，非推断；跑完已还原并复跑基线确认全绿）：

| # | 破坏 | 必须红的用例（实测） |
|---|---|---|
| 1 | `_fit_duration` 恢复末场景豁免：`if index != 0 and …` 改成 `is_edge = index == 0 or index == len(ordered) - 1` + `if not is_edge and …` | `test_fit_duration_never_overshoots_the_budget` |
| 2 | `_fit_duration` 的预算预留去掉：`- (_INTRO_MAX_S if intro_first else 0.0)` 改成 `- 0.0` | `test_intro_reserves_headroom_for_the_hook_slot` |
| 3 | `_fit_duration` 的首场景豁免也去掉（`if index != 0` 改成 `if True`） | `test_intro_keeps_its_slot_when_the_first_scene_alone_exceeds_the_budget` |
| 4 | `casting.episode_order` 退化成钟表序：返回式改成 `(scene.start, scene.number, scene.scene_index)` | `test_segments_follow_broadcast_order_not_clock_order` |
| 5 | `casting.score_order` 去掉三个次键：返回式改成 `(-scene.score,)` | `test_ultra_short_breaks_a_cross_episode_score_tie_by_episode_number` **与** `test_score_order_is_deterministic_across_input_order`（实测两条同时红） |
| 6 | `build_raw_clip` 的身份比较改回按 `scene_index`：`if ordered[0] is not best` → `if ordered[0].scene_index != best.scene_index` | `test_raw_clip_best_first_swap_survives_a_scene_index_collision` |
| 7 | `build_cross` 的旁白段沿用上一个原声段的集号：`episode_id=anchor.episode_id` → `episode_id=scene.episode_id` | `test_cross_narration_segment_carries_the_anchor_episode` |
| 8 | `build_ultra_short` 改回 `max(scenes, key=lambda s: s.score)` | `test_ultra_short_breaks_a_cross_episode_score_tie_by_episode_number` |
| 9 | `build_subtitle_flow` 的金句摊平取台词：`casting.dialogue_of(material, scene.episode_id)` → `[a for m in material.values() for a in m.asr]` | `test_subtitle_flow_takes_each_line_from_its_own_episode` |
| 10 | `casting.stamp` 改成逐字段抄（漏掉 `reason`） | `test_stamp_attaches_the_episode_identity_of_the_row_it_came_from`（第二个断言，实测报 `reason` 缺失）。**`test_stamp_survives_a_new_field_on_conflictscore` 抓不到这一条**——它比的是**键集合**，逐字段抄只要把五个键都写上就过；两条用例各守一半，别删任何一条 |
| 11 | `casting.dialogue_of` 的 `except KeyError: raise` 改成 `return []` | `test_dialogue_of_raises_on_a_missing_episode_instead_of_looking_silent` |
| 12 | `casting.label_of` 的 `except KeyError: raise` 改成 `return ""` | `test_label_of_names_the_episode_for_the_copy_prompt` |
| 13 | `deal_windows` 改成切块（见 Task 3b Step 5 #7） | Task 3b 的两条用例（本文件不红——发窗不在这里测，**别为此在本文件加用例**，那只是把同一条不变量抄两遍） |
| 14 | `_fit_duration` 里 `episode_id=scene.episode_id` 改成 `episode_id=ordered[0].episode_id`（即"整条片属于第一集"的老写法） | `test_every_builder_stamps_the_episode_of_each_segment`（`intro_narration` 与 `raw_clip` 两格都红）。**这一条是整张表里最贵的**：它模拟的正是"编排器仍然认为一条片只属于一集"这个旧假设，而它不报错、只出错片 |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_casting.py tests/engines/narration/test_cross_episode_arrangement.py -q`

- [ ] **Step 10: lint / 类型门禁 + 提交**

Run: `cd service && ../.venv/Scripts/ruff.exe check . && ../.venv/Scripts/mypy.exe dramaclip`

Expected: **两条都无输出、退出码 0**。（scratch 实测：`ruff check .` → `All checks passed!`；`mypy --strict dramaclip` → `Success: no issues found in 95 source files`。这一条门禁**此时就能跑通**，因为本任务不改 `api/narration.py`——它仍然用旧签名调 `build_plan`，mypy 会报它；**若 mypy 报了 `api/narration.py` 的 `build_plan` 调用，那是预期的，记下来留给 Task 6，不要在本任务里去改那个文件**。除 `api/narration.py` 之外任何一处报错都要就地修掉。）

```bash
git add service/dramaclip/engines/narration/casting.py service/dramaclip/engines/narration/modes/__init__.py service/dramaclip/engines/narration/modes_w5.py service/dramaclip/engines/narration/modes_w8.py service/dramaclip/engines/narration/modes_p2.py service/dramaclip/engines/narration/modes_w9.py service/dramaclip/engines/narration/pipeline.py service/tests/engines/narration/test_casting.py service/tests/engines/narration/test_cross_episode_arrangement.py service/tests/engines/narration/test_modes.py service/tests/engines/narration/test_modes_w5.py service/tests/engines/narration/test_modes_w8.py service/tests/engines/narration/test_modes_p2.py service/tests/engines/narration/test_modes_w9.py service/tests/engines/narration/test_ducked_narration.py service/tests/api/test_narration_audio_chain.py service/tests/api/test_narration_no_downgrade.py
git commit -m "feat(narration): 取材层 casting + 六编排器跨集化，一条方案可从多集取画面（规格 §1）"
```

（**逐路径 add，禁止 `git add service/tests/engines/narration`**：那是整个目录，会卷走同树另一位工程师/另一个代理新加的文件，违反《开工前置》末段的提交纪律。上面 17 个路径就是本任务真改的全部。）

**本任务不能独立构建**：`api/narration.py::_generate_one` 仍在用旧签名调 `build_plan`，所以这一次提交之后 `mypy` 与 `tests/api` 是红的，直到 Task 6 Step 7 重写它。这与 Task 6 Step 9 的处境同类（那里是契约两侧与前端调用点），**故本任务的提交信息里必须写明"调用点由 Task 6 接手"**，否则中间任何一个提交点上看树的人都会以为坏了。若不接受一个红的中间提交，就把 Step 10 改成"只暂存不提交"，与 Task 6 Step 10 一起在 Task 9 Step 8 提交。

---

## Task 4: 成稿链——卖点角度进 prompt + **槽位台词按集取用**（两条链同形）

角度只影响选题是不够的：`copywriter` 若不知道这条片的卖点，K 条方案的**文案**会趋同，而重叠度量只看取材、拦不住"同一批画面配三段同义解说"。本任务把角度块接进两条成稿链。

**本任务还有第二半，是 2026-09-12 裁决逼出来的真缺陷（《修订记录》C7）**：`write_plan_copy` 今天只收**一张摊平的** `asr_segments`，`_slot_block` 用它逐槽做 `seg.start < segment.end and seg.end > segment.start` 过滤。区间是**集内相对秒**，而活库实测十集的场景起点全部从 `0.0` 开始——集与集的秒轴互相覆盖。单集时代这个过滤不可能错；**跨集时间轴上它必然把别的集的对白喂给编剧**，而 system prompt 明写「情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件」，于是模型会照着错的台词写出一段通顺、可信、说的却不是这段画面的解说。不报错、不降级、成片看着正常。两半合在一个任务里做，是因为它们改的是同一个签名、同一批调用点、同一个测试文件——分两步会把 `write_plan_copy` 的签名改两遍、把 Step 5 那张"逐个补调用点"的清单跑两遍。

**Files:**
- Modify: `service/dramaclip/engines/narration/copywriter.py`（`write_plan_copy` 的签名 + `user_prompt` 块；**`_slot_block` 整函数替换**；import 区）
- Modify: `service/dramaclip/engines/narration/scriptwriter.py:206-249`（`write_script_episodes` 的签名 + `user_prompt` 块）
- Modify: `service/dramaclip/engines/narration/script_driver.py:62-116`（`script_dialogue_plan` 整函数：签名 `:62-67`、docstring `:68-76`、`write_script_episodes(...)` 调用 `:94-102`）
- Modify: `service/dramaclip/api/narration.py:229-260`（临时补 `angle_block=""`，Task 6 整体重写）
- Modify: `service/tests/engines/narration/test_copywriter.py`、`test_scriptwriter.py`、`test_script_driver.py`、`test_script_episodes.py`
- **不动**：`service/dramaclip/engines/narration/casting.py`（Task 3c 已建，本任务只消费它的 `MaterialByEpisode` / `dialogue_of` / `label_of`）

- [ ] **Step 1: 写失败测试**

在 `service/tests/engines/narration/test_copywriter.py` 末尾追加（该文件已有 `FakeLlm`、`_plan()`、`_lines()`、`_SETTINGS`、`_SEGMENTS`、`llm` fixture，直接复用）：

```python
_ANGLE_BLOCK = (
    "\n本条片的取材角度：复仇线"
    "\n这条角度为什么成立：第 3 集反杀最狠"
    "\n开场钩子首句（第一个槽位据此下笔，可改写措辞但不得换卖点）：他跪着进了门"
)


def test_angle_block_reaches_the_prompt(llm: Any) -> None:
    """角度是 K 条方案唯一的差异化来源：它没进 prompt，K 条就只是同一部片切 K 次。"""
    llm.queue = [_lines()]
    copywriter.write_plan_copy(
        _plan(), _SEGMENTS, _SETTINGS, mode_label="全片解说", angle_block=_ANGLE_BLOCK
    )
    prompt = llm.calls[0]
    assert "复仇线" in prompt, "角度名未进 prompt"
    assert "第 3 集反杀最狠" in prompt, "选题理由未进 prompt"
    assert "他跪着进了门" in prompt, "钩子首句未进 prompt"


def test_angle_block_is_not_written_into_the_copy(llm: Any) -> None:
    """角度块是给模型的指令，不是文案：落库的 text 必须仍是模型答的那句。"""
    llm.queue = [_lines()]
    plan = copywriter.write_plan_copy(
        _plan(), _SEGMENTS, _SETTINGS, mode_label="全片解说", angle_block=_ANGLE_BLOCK
    )
    assert all("复仇线" not in text.text for text in plan.narration_texts)
    assert all("他跪着进了门" not in text.text for text in plan.narration_texts)
```

在 `service/tests/engines/narration/test_script_driver.py` 末尾追加：

```python
def test_angle_block_is_forwarded_to_the_script_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """跨集链的角度注入：与单集链共用 angles.prompt_block 的措辞，不得各写一份。"""
    monkeypatch.setattr(script_driver, "LlmClient", FakeLlmClient)
    FakeLlmClient.queue = [dict(_VALID_PAYLOAD)]
    script_driver.script_dialogue_plan(
        _EPISODES, dict(_SETTINGS), angle_block="\n本条片的取材角度：复仇线"
    )
    assert any("复仇线" in call[1] for call in FakeLlmClient.calls), (
        "角度块没转交到编剧 prompt"
    )
```

该文件若尚无 `_VALID_PAYLOAD`（它目前在 `test_scriptwriter.py`），把它连同其构造所需的最小字段复制到 `test_script_driver.py` 顶部并同名；若 `FakeLlmClient.calls` 目前只存 user 串，改成存 `(system, user)` 二元组并同步该文件里所有 `calls[0]` 断言——**两条成稿链的替身必须同形**，否则角度块的断言在两侧写法不一致，将来只有一侧会被发现坏了。

- [ ] **Step 1b: 写"台词串集"的失败测试（2026-09-12 裁决新增，本任务最关键的两条用例）**

`service/tests/engines/narration/test_copywriter.py`：先把夹具迁到新签名（**三处，逐字给**），再在文件末尾追加两条用例。

1. import 区加 `casting`（isort 位置：`from dramaclip.engines.analysis.models import AsrSegment` 之后、`from dramaclip.engines.narration import copywriter` 那一行合并进去）：

```python
from dramaclip.engines.narration import casting, copywriter
```

2. `_SEGMENTS` 之后新增单集夹具（**`_SEGMENTS` 本身保留**，它是 `EpisodeMaterial.asr` 的值）：

```python
# 单集夹具：一张只有一集的取材原料表。跨集的用例在下面自己搭两集。
_MATERIAL: casting.MaterialByEpisode = {
    "ep1": casting.EpisodeMaterial(number=1, asr=_SEGMENTS)
}
```

3. `_plan()` 整函数替换（`build_full` 的首参在 Task 3c 已换）：

```python
def _plan():
    return build_full(casting.stamp([(1, "ep1", _SCENES)]), StrategySpec(min_duration_s=10))
```

4. **全部既有 `write_plan_copy(...)` 调用的第二个实参从 `_SEGMENTS` 改成 `_MATERIAL`**（实测 9 处）。其中 `test_slot_without_transcript_forbids_invention` 原来传的是**空表 `[]`**，它要改成一张"有集、没台词"的表——**不能改成 `{}`**：`{}` 会撞上 `dialogue_of` 的缺键抛错，那条用例测的本来是"该区间无台词"这个**合法**分支，两个分支必须分开（这正是 Step 3b 的 `dialogue_of` 抛错与本用例的分界）：

```python
def test_slot_without_transcript_forbids_invention(llm: Any) -> None:
    """无转写可依据时（该区间一句台词没有）必须明写"不得编造"：每个槽位都得看到这句。"""
    llm.queue = [_lines()]
    silent = {"ep1": casting.EpisodeMaterial(number=1, asr=[])}
    copywriter.write_plan_copy(_plan(), silent, _SETTINGS, mode_label=_MODE_LABEL)
    prompt = llm.calls[0]
    assert prompt.count("（该区间无台词转写") == len(_SCENES), "每个空区间槽位都要有禁止编造的提示"
```

5. 文件末尾追加两条用例：

```python
def _two_episode_plan() -> tuple[Any, casting.MaterialByEpisode]:
    """跨集夹具：两个槽位压在**同样的 12.0-22.0s**，只是分属两集。

    秒轴刻意重合，因为活库实测十集的场景起点全部从 `0.0` 开始——集与集的集内相对秒
    互相覆盖是常态而不是边角情况。摊平一张 ASR 表按秒过滤的实现，在这里会把两集的
    对白都塞进每一个槽位。
    """
    scenes = casting.stamp(
        [
            (1, "ep1", [ConflictScore(scene_index=0, start=12.0, end=22.0, score=90)]),
            (2, "ep2", [ConflictScore(scene_index=0, start=12.0, end=22.0, score=88)]),
        ]
    )
    plan = build_full(scenes, StrategySpec(min_duration_s=10))
    material: casting.MaterialByEpisode = {
        "ep1": casting.EpisodeMaterial(
            number=1, asr=[AsrSegment(start=13.0, end=16.0, text="第一集的原话")]
        ),
        "ep2": casting.EpisodeMaterial(
            number=2, asr=[AsrSegment(start=13.0, end=16.0, text="第二集的原话")]
        ),
    }
    return plan, material


def test_a_slot_is_grounded_in_its_own_episodes_dialogue(llm: Any) -> None:
    """跨集时间轴上，槽位只能读**它那一集**的台词（规格 §1 跨集的前置条件）。

    这是本轮最关键的一条用例：错的取材不会报错、不会降级，成片看着完全正常，
    而解说讲的是另一集的事。system prompt 明写「情节、细节、称谓只能来自给定台词」，
    所以模型会老老实实照着**喂错的那份台词**写——缺陷在喂料侧，不在模型侧。

    前两个断言钉的是**夹具前提**：两集的秒轴必须重合，否则摊平实现也能碰巧答对，
    这条用例就变成一条永远绿、什么也没守着的断言（B6 同一类）。
    """
    plan, material = _two_episode_plan()
    assert [seg.episode_id for seg in plan.timeline] == ["ep1", "ep2"], "夹具前提塌了"
    assert [(seg.start, seg.end) for seg in plan.timeline] == [(12.0, 22.0)] * 2, (
        "夹具前提塌了：两集的秒轴必须重合，否则摊平实现也能碰巧答对"
    )
    llm.queue = [
        {
            "lines": [
                {"id": text.id, "text": f"{text.id} 的解说"}
                for text in plan.narration_texts
            ]
        }
    ]
    copywriter.write_plan_copy(
        plan, material, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
    )
    prompt = FakeLlm.calls[0]
    head, _, tail = prompt.partition("[full-2]")
    assert "第一集的原话" in head and "第二集的原话" not in head, (
        "第一个槽位读到了别的集的台词"
    )
    assert "第二集的原话" in tail and "第一集的原话" not in tail, (
        "第二个槽位读到了别的集的台词"
    )
    assert "第1集" in head and "第2集" in tail, (
        "跨集时间轴上槽位不报集名，等于没报区间——模型无从判断相邻两槽是不是同一条线"
    )


def test_a_slot_whose_episode_is_missing_from_the_material_raises(llm: Any) -> None:
    """缺键 ≠「这一集没有台词」：静默当成没台词会让编剧写出一段什么都不说的解说。

    `_slot_block` 本来就有"该区间无台词转写"这一支（素材事实，合法，见上面那条
    `test_slot_without_transcript_forbids_invention`），所以缺键必须走**另一条**路。
    `match` 只写到「槽位 full-2：集 ep2」为止，不写后半句：`dialogue_of` 与 `label_of`
    各有一句自己的消息，写死后半句会让这条用例绑死"哪个查找先抛"，而两者都抛才对。
    两条消息各自由 `test_casting.py` 钉住。
    """
    plan, material = _two_episode_plan()
    del material["ep2"]
    llm.queue = [_lines()]
    with pytest.raises(ValueError, match=r"槽位 full-2：集 ep2"):
        copywriter.write_plan_copy(
            plan, material, _SETTINGS, mode_label=_MODE_LABEL, angle_block=""
        )
    assert llm.calls == [], "缺料就该在发请求之前拦住，不该先付一次成稿"
```

（`AsrSegment` / `ConflictScore` / `pytest` / `Any` 该文件已 import，直接复用；`build_full` 与 `StrategySpec` 也已有。**不要新增 `from dramaclip.engines.narration.modes_w8 import build_full` 这类重复 import**，ruff 会报 F811。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_copywriter.py -q -k angle_block`

Expected: FAIL —— `TypeError: write_plan_copy() got an unexpected keyword argument 'angle_block'`

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_copywriter.py -q -k "own_episodes_dialogue or missing_from_the_material"`

Expected: FAIL —— 同样报 `unexpected keyword argument 'angle_block'`（Step 1b 的两条用例都传了它）。**此时它们还没有真正测到"台词串集"**：先让签名过，再在 Step 3b 之后看它们是否真的能抓住摊平实现（Step 7 的变异 #4 就是这件事）。

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_script_driver.py -q -k angle_block`

Expected: FAIL —— `TypeError: script_dialogue_plan() got an unexpected keyword argument 'angle_block'`

- [ ] **Step 3: `copywriter.write_plan_copy` 接角度块 + 换成按集取料**

`service/dramaclip/engines/narration/copywriter.py`：

1. import 区改一行（`AsrSegment` 在本文件将**不再有引用**——`_slot_block` 的第二参换成了 `MaterialByEpisode`，留着就是 F401）：

```python
from dramaclip.engines.narration import casting, scriptwriter
```

（原状是两行：`from dramaclip.engines.analysis.models import AsrSegment` 与 `from dramaclip.engines.narration import scriptwriter`。**删掉 `AsrSegment` 那一行**，把 `casting` 合并进 `scriptwriter` 那一行——分两行写 ruff 会报 I001，而 Step 8 的门禁写着"Expected: 无输出"，B7b 同一类。）

2. 签名整块替换（`angle_block` 与 `mode_label` 同为**必填**关键字，理由与 P-1.5 把 `mode_label` 定为必填一致：可省的卖点等于可省的差异化）：

```python
def write_plan_copy(
    plan: PlanData,
    material: casting.MaterialByEpisode,
    settings: dict[str, str],
    *,
    mode_label: str,
    angle_block: str,
    trace_dir: Path | None = None,
) -> PlanData:
    """填满 plan 的全部旁白槽位并置 planner=llm_script；任何不合格都抛异常。

    `material` 按集分开（episode_id → 集号 + 该集台词表）：一条方案的时间轴可以横跨
    多集（规格 §1），而槽位区间是**集内相对秒**，故每个槽位只能读它自己那一集的台词。
    理由与实测数字见 `_slot_block`。
    """
```

3. `user_prompt` 整块替换（角度块紧跟模式行、在风格行之前——卖点是"写什么"，风格是"怎么写"，前者约束更强）：

```python
    user_prompt = (
        f"项目：{project_name}"
        + (f"（题材：{genre}）" if genre else "")
        + f"\n模式：{mode_label}"
        + angle_block
        + "\n文案槽位：\n"
        + _slot_block(plan.narration_texts, plan.timeline, material)
        + (f"\n\n解说风格要求：{directives}" if directives else "")
    )
```

4. 模块 docstring 末尾（`单集槽位模式（intro/cross/…）共用本模块；跨集剧本驱动（dialogue_narration）走 scriptwriter，两条链共享 FUNDAMENTALS。` 那两行**整块替换**——"单集槽位模式"这个说法在裁决之后是假话）：

```python
槽位模式（intro/cross/ultra_short/full/dual_host/inner_monologue）共用本模块；
剧本驱动（dialogue_narration）走 scriptwriter，两条链共享 FUNDAMENTALS。
两类的方案都可以跨集取材（规格 §1）：本模块按 `segment.episode_id` 逐槽取台词，
scriptwriter 那边则把整份跨集转写按集分组喂给模型、由模型自己排集号。
卖点角度由 `angles.prompt_block` 措辞、经 `angle_block` 注入；两条链共用那一段字。
```

- [ ] **Step 3b: `_slot_block` 整函数替换（2026-09-12 裁决新增）**

这是 C7 那个真缺陷的修法本体。**`_sanitize` 与 `_SYSTEM_PROMPT` 一字不动**——缺陷不在"模型答得对不对"，在"我们喂给它的料对不对"。

```python
def _slot_block(
    texts: list[NarrationText],
    segments: list[TimelineSegment],
    material: casting.MaterialByEpisode,
) -> str:
    """每个槽位一段：职责 + 它压在的画面区间 + **它那一集**区间内的台词。

    台词必须按 `segment.episode_id` 取，不能拿一张摊平的 ASR 表按秒过滤：区间是
    **集内相对秒**，活库实测十集的场景起点全部从 `0.0` 开始，集与集的秒轴互相覆盖，
    于是第 3 集 12-20s 的槽位会捞到第 7 集 12-20s 的对白。而 system prompt 明写
    「情节、细节、称谓只能来自给定台词，禁止编造台词之外的事件」——模型会老老实实照着
    **错的台词**写出一段通顺、可信、说的却不是这段画面的解说。不报错、不降级、
    成片看着正常，正是本仓最贵的那一类缺陷。跨集时间轴（规格 §1）让这个缺陷从
    "不可能发生"变成"必然发生"，故按集取台词是跨集的前置条件，不是可选优化。

    集名（`casting.EpisodeMaterial.label`）也进块：跨集时间轴上「画面区间 12.0-20.0s」
    不说是哪一集就等于没说，模型无从判断相邻两槽是不是同一条线。
    """
    by_id = {segment.narration_id: segment for segment in segments if segment.narration_id}
    lines: list[str] = []
    for text in texts:
        segment = by_id.get(text.id)
        if segment is None:
            raise ValueError(f"槽位 {text.id} 没有配对画面段：编排器漏写 narration_id")
        try:
            pool = casting.dialogue_of(material, segment.episode_id)
            label = casting.label_of(material, segment.episode_id)
        except ValueError as exc:
            # 缺键是装配漏了一集，不是"这一集没台词"：点名到槽位，否则错误串里只有
            # 一个 uuid，运维看不出是哪一条片的哪一段。
            raise ValueError(f"槽位 {text.id}：{exc}") from exc
        lines.append(f"[{text.id}] 要做的事：{text.brief}")
        lines.append(f"  取材：{label}，画面区间：{segment.start:.1f}-{segment.end:.1f}s")
        inside = [
            seg for seg in pool if seg.start < segment.end and seg.end > segment.start
        ]
        if inside:
            lines.append("  区间内台词：")
            lines.extend(
                f"    {scriptwriter.clock(seg.start)}-{scriptwriter.clock(seg.end)} "
                f"{seg.text.strip()}"
                for seg in inside
            )
        else:
            lines.append("    （该区间无台词转写：只按职责与前后槽位写，不得编造具体情节）")
    return "\n".join(lines)
```

**三处必须逐字核对的地方**（每一处都是一个静默坏法）：

1. `f"  取材：{label}，画面区间：…"` —— 行首**两个空格**、`取材：` 与 `画面区间：` 之间是**全角逗号**。Step 1b 的 `test_a_slot_is_grounded_in_its_own_episodes_dialogue` 断言 `"第1集" in head`，靠的就是这一行；格式改了断言会红，那是好事，但别为了过断言把集名塞到别处去。
2. `except ValueError` **只包两个查找**，不包 `inside` 的过滤与后面的拼装。把 `try` 扩到整个循环体会让"该区间无台词"那一支也被当成缺键吞掉——两个分支必须分得开（Step 1b 第 4 点为此专门留了 `test_slot_without_transcript_forbids_invention`）。
3. `raise ValueError(f"槽位 {text.id}：{exc}") from exc` —— `from exc` 不能省：省了之后 traceback 里看不到 `dialogue_of` 那句原文，运维只会看到"槽位 full-2：…"半句话。

- [ ] **Step 4: `scriptwriter` 与 `script_driver` 接角度块**

`service/dramaclip/engines/narration/scriptwriter.py`：

1. `write_script_episodes` 签名整块替换（`angle_block` 必填，放在 `project_name` 之后、`style_directives` 之前）：

```python
def write_script_episodes(
    llm: LlmClient,
    episode_inputs: list[dict[str, Any]],
    *,
    target_min_s: float,
    target_max_s: float,
    project_name: str,
    angle_block: str,
    style_directives: str = "",
    trace_path: Path | None = None,
) -> Script:
```

2. `user_prompt` 里 `{cross_block}\n` 那一行之后插入一行 `f"{angle_block}\n"`，替换后的整块是：

```python
    user_prompt = (
        f"项目：{project_name}\n"
        f"参考时长：{target_min_s:.0f}-{target_max_s:.0f} 秒（仅作参考，不是硬限制）。\n"
        f"最高优先级是剧情完整与吸引力：铺垫果断压缩，冲突和反转给足戏份；"
        f"宁可略长，也不要为凑时长删掉关键冲突。\n"
        f"{cross_block}\n"
        f"{angle_block}\n"
        f"台词转写：\n" + transcript_block
        + f"{style_block}"
    )
```

`service/dramaclip/engines/narration/script_driver.py`：

3. `script_dialogue_plan` 签名整块替换：

```python
def script_dialogue_plan(
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    *,
    angle_block: str,
    trace_dir: Any = None,
) -> tuple[PlanData, list[str]]:
```

4. 其 docstring 的第二段（`口味层由调用方经 resolve_run_style 注入 …` 之后）补一句：

```python
    卖点角度经 angle_block 注入编剧 prompt，措辞由 angles.prompt_block 独家持有。
```

5. `write_script_episodes(...)` 调用里加实参 `angle_block=angle_block,`（放在 `project_name=` 之后、`style_directives=` 之前，与形参顺序一致）。

- [ ] **Step 5: 补齐所有既有调用点**

`angle_block` 在三处都是必填、`material` 换了类型，故所有调用点必须显式改。先找齐：

Run: `cd service && grep -rn "write_plan_copy(\|write_script_episodes(\|script_dialogue_plan(" . --include=*.py`

Expected: 命中 `dramaclip/api/narration.py` 两处、`dramaclip/engines/narration/script_driver.py` 一处，以及 `tests/engines/narration/test_copywriter.py`、`test_scriptwriter.py`、`test_script_driver.py`、`test_script_episodes.py`。逐个补：

- `service/dramaclip/api/narration.py` 的 `copywriter.write_plan_copy(plan, asr_segments, settings, …)`：第二个实参改成 `material`，并加 `angle_block="",`。**这个文件里此时没有 `material` 这个变量**——`_generate_one` 只有一张摊平的 `asr_segments`。就地拼一张单集表顶上（Task 6 Step 7 第 11 点会把它换成 `_casting_for` 的真装配）：

```python
        # Task 6 重写为按角度注入 + 按集装配；这两行只在本任务与下一次提交之间存活。
        material = {
            episode_id: casting.EpisodeMaterial(
                number=int(episodes[0]["episode_number"]), asr=asr_segments
            )
        }
```

  同时在该文件的 import 区把 `casting` 合并进既有那一行（isort：`casting` < `copywriter`）：

```python
from dramaclip.engines.narration import casting, copywriter, script_driver, scriptwriter
```

  `script_driver.script_dialogue_plan(...)` 那一处只加 `angle_block="",`（它不吃 `material`，跨集转写走 `episode_inputs`）。
- `service/tests/engines/narration/test_copywriter.py`：所有既有 `write_plan_copy(...)` 调用加 `angle_block=""`（Step 1 新增的两条传 `_ANGLE_BLOCK`，Step 1b 新增的两条已在代码块里写好）。**第二个实参已在 Step 1b 第 4 点全部迁到 `_MATERIAL`，本步不要再动。**
- `service/tests/engines/narration/test_scriptwriter.py`：`_run()` 助手加 `angle_block=""`。
- `service/tests/engines/narration/test_script_driver.py`、`test_script_episodes.py`：所有 `script_dialogue_plan(...)` 调用加 `angle_block=""`（Step 1 新增的那条除外）。
- `service/tests/api/test_produce.py`：`_FakeLlm.chat_json` 的槽位正则 `r"^\[([^\]]+)\] 要做的事："` **不受影响**——Step 3b 只改了它**下面**那一行（`画面区间：` → `取材：…，画面区间：…`），槽位头一行的格式一个字没动。若该文件有直接调 `write_plan_copy` 的用例，同法补 `angle_block=""` 并把第二参改成单集 `material` 表。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration tests/api -q`

Expected: PASS（`tests/api/test_analysis.py` 的既有隔离 flake 除外——它属另一位工程师，不修不碰）。scratch 实测 `test_copywriter.py` 从 11 条增到 **13** 条全绿。

- [ ] **Step 7: 变异检查**

下表 4/5/6 三行是 2026-09-12 裁决新增的，"必须红的用例"都是 scratch 实跑结果（非推断）：

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `copywriter` 的 user_prompt 里删掉 `+ angle_block` | `test_angle_block_reaches_the_prompt` |
| 2 | `scriptwriter` 的 user_prompt 里删掉 `f"{angle_block}\n"` | `test_angle_block_is_forwarded_to_the_script_prompt` |
| 3 | `copywriter` 把 `angle_block` 挪到 `_slot_block(...)` 之后（塞进槽位块尾部） | **不红**——说明"角度块在 prompt 里的位置"不是被测行为。不必为此加用例：位置只影响模型注意力，不影响任何可观察输出，钉住它等于把测试写成实现的镜像 |
| **4** | **`_slot_block` 的 `pool = casting.dialogue_of(material, segment.episode_id)` 改成摊平：`pool = [a for m in material.values() for a in m.asr]`** | **`test_a_slot_is_grounded_in_its_own_episodes_dialogue`（实测红，报"第一个槽位读到了别的集的台词"）。这是 C7 那个真缺陷的唯一守卫——它红，说明"跨集时间轴上编剧读的是别的集的台词"这条已经回来了** |
| **5** | **`casting.dialogue_of` 的 `except KeyError: raise` 改成 `return []`，且 `casting.label_of` 的同样改成 `return ""`（两处必须一起改）** | **`test_a_slot_whose_episode_is_missing_from_the_material_raises` + `test_casting.py` 的两条（`test_dialogue_of_raises_…` / `test_label_of_…`）。⚠️ 只改一处不会红：另一处的 `except KeyError: raise` 会顶包，实测（scratch）单独改 `dialogue_of` 时 `test_copywriter.py` 全绿、只有 `test_casting.py` 红一条。这类"两个守卫互相顶包"的变异必须一起破坏才测得出，写在这里免得下一个人以为用例失效了** |
| **6** | **`_slot_block` 里 `label = casting.label_of(...)` 与那一行 `f"  取材：{label}，…"` 一起删掉** | **`test_a_slot_is_grounded_in_its_own_episodes_dialogue` 的第三个断言（`"第1集" in head`）。它守的不是正确性而是可写性：跨集时间轴上槽位不报集名，模型就无从判断相邻两槽是不是同一条线，"相邻两条要能连读成一条故事线"那句 system prompt 会失效** |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_copywriter.py tests/engines/narration/test_casting.py tests/engines/narration/test_script_driver.py -q`

- [ ] **Step 8: 提交**

```bash
git add service/dramaclip/engines/narration/copywriter.py service/dramaclip/engines/narration/scriptwriter.py service/dramaclip/engines/narration/script_driver.py service/dramaclip/api/narration.py service/tests/engines/narration/test_copywriter.py service/tests/engines/narration/test_scriptwriter.py service/tests/engines/narration/test_script_driver.py service/tests/engines/narration/test_script_episodes.py service/tests/api/test_produce.py
git commit -m "feat(narration): 卖点角度注入两条成稿链；槽位台词改为按集取用（跨集时间轴的前置条件）"
```

（**不许写 `service/tests/engines/narration`**：那是整个目录，会卷走同树另一位工程师/另一个代理新加的文件，违反《开工前置》末段的提交纪律。上面九个路径就是本任务真改的全部——`tests/engines/narration` 下另有 13 个文件（`test_modes*.py`、`test_tts_audio_isolation.py`、`conftest.py` 等），本任务一个都不碰。`service/tests/api/test_produce.py` 只在 Step 5 真补了 `angle_block=""` 时才 add；没改就从命令里去掉，别 add 一个没有变更的路径。）

---

## Task 5: 配音的唯一调用点 `_voice`（内容寻址已在 `9b42f24` 落地）

**本任务原先叫「配音目录按作业与变体隔离（K 条互相覆盖的必修 bug）」，那个 bug 已经不存在了。** 一小时前落地的 `9b42f24` 把它修在了**拥有路径的那一层**：`pipeline._content_addressed_audio(work_dir, slot_id, text, voice, engine)`（`engines/narration/pipeline.py:213-227`）把文件名变成 `{slot_id}-{sha1(text|voice|engine)[:12]}.mp3`，配 `_synthesize_into`（`:230-247`）的缓存优先、uuid 暂存名、`os.replace` 原子换入、`finally` 清理。守卫它的是 `service/tests/engines/narration/test_tts_audio_isolation.py` 六例（重规划、并发、缓存复用、voice/engine 换键、失败无残留、0 字节占位不算命中），全部经变异检验。

**所以本任务只剩一件真事**：给 `plan_variants` 一个**唯一的配音出口**——一个知道 tts 目录与 models 目录在哪里的地方。今天这两个路径拼在 `_generate_one` 的尾部（`api/narration.py:262-265`），而 Task 6 要删掉那个函数；K 条变体的配音要有一个共用入口，否则每个调用点各拼一次路径，迟早拼出两个不同的目录。

**为什么不做目录分层（原计划的核心内容，已删）**：按作业或按变体分目录**在内容寻址之下不再有正确性收益**，而且有实际代价——

- **正确性收益为零**：路径由 `(slot_id, text, voice, engine)` 决定，同名 ⟺ 同内容，K 条变体不可能互相覆盖。
- **代价是真的**：分目录会让 `pipeline` 的**缓存优先在 api 层失效**。`test_identical_copy_is_synthesised_once` 钉的正是"同文案不二次付费"（`docs/service/02 §6`）；按作业分目录之后，整组重规划与「重掷此条」都要为**没改过的槽位**再付一次配音。
- **原来那三条变异检查全是死的**：把 tts 目录改回 `context.work_dir / "tts"`、去掉 `job_id`、去掉变体号——内容寻址单独就能让路径互异，三条改回去**一条用例都不红**。留着它们是一张假的安全网，比没有更坏（它让人以为这里被测着）。

**原来那个 `_voice` docstring 会作为一句关于代码的假话被提交**（"K 条同模式变体因此算出同一批文件名；共用一个 tts 目录时后一条会覆盖前一条的音频"）。那正是 `loudnorm` 键名那次的失败形态：一个说得通的故事被烤进注释，下游所有人都会信它。本任务的 docstring 只写**当前代码真做的事**。

**Files:**
- Modify: `service/dramaclip/api/narration.py`（在 `_collect_episode_inputs`（实测 `:275`）之前新增 `_voice`；`_generate_one` 尾部 `:262-265` 改成调它）
- Modify: `service/dramaclip/engines/narration/pipeline.py:233-238`（`_synthesize_into` 的 docstring，见 Step 5）
- Modify: `service/tests/api/test_produce.py`（Task 6 会把它 `git mv` 成 `test_plan_variants.py`）

- [ ] **Step 1: 写失败测试**

追加到 `service/tests/api/test_produce.py`。文件顶部的模型 import 要**合并进既有那一行**（现在是 `from dramaclip.engines.narration.models import PlanData`），不要另起一行——ruff 的 isort 会报 I001：

```python
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
```

（`Harness`、`pipeline`、`narration_api`、`pytest`、`Path`、`sqlite3` 该文件已有，直接复用。**不要复用它的 `_StubTts`**：那个替身写 0 字节，而 `_synthesize_into` 的缓存命中要求**非空**文件，0 字节的第二轮会重新合成——用它写下面第二条用例会得到一个假绿。）

```python
def _variant_plan(copy_prefix: str) -> PlanData:
    """同模式同槽位 id、只有文案不同的方案：id 确定性重复正是内容寻址要隔离的东西。"""
    return PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=2.0, audio="ducked", narration_id="full-1"
            )
        ],
        narration_texts=[
            NarrationText(id="full-1", text=f"{copy_prefix}·第一段解说", brief="推进")
        ],
    )


class _TextWritingTts:
    """把文案原样写进"音频"文件：读文件内容即知这是谁的音。

    与 tests/engines/narration/test_tts_audio_isolation.py 的替身同一手法——那个文件的
    docstring 逐字写着「只断言"两条路径不同"抓不住 stale-pointer 回归，内容断言才抓得住」。
    本文件在 api 层沿用同一条规矩。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, _voice: str | None, out_path: Path) -> Path:
        assert text.strip(), "语言层没填上文案，槽位还是空的"
        self.calls.append(text)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(text.encode("utf-8"))
        return out_path


def test_voice_gives_each_variant_its_own_audio(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_voice` 是 plan_variants 唯一的配音出口，它给出的目录让内容寻址照常生效。

    **本用例不是 test_tts_audio_isolation.py 的重复**：那六例守的是 pipeline 层
    （文件名怎么算、缓存怎么判、失败怎么清），本用例守的是 **api 层到 pipeline 的接线**——
    `_voice` 传错目录、传错 models_dir、或者干脆忘了调 synthesize_narration_texts，
    那六例一条都不会红。断言读**文件内容**而不是比路径，理由同上。
    """
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    engine = _TextWritingTts()
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)
    settings = dict(harness.context.settings)

    voiced = [
        narration_api._voice(harness.context, _variant_plan(prefix), settings)
        for prefix in ("角度一", "角度二")
    ]

    assert len(engine.calls) == 2, f"两条方案各一次配音，实得 {engine.calls}"
    for plan in voiced:
        text = plan.narration_texts[0]
        assert text.audio_path, "配音后 audio_path 仍是空的"
        content = Path(text.audio_path).read_text(encoding="utf-8")
        assert content == text.text, (
            f"audio_path 指向的不是这条方案自己的音：内容={content!r}，应为={text.text!r}"
        )
    first_path = voiced[0].narration_texts[0].audio_path
    second_path = voiced[1].narration_texts[0].audio_path
    assert first_path != second_path, "文案不同却落在同一路径——内容寻址没生效"


def test_voice_keeps_the_cross_call_cache(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文案相同的槽位只合成一次：`_voice` 的目录**不得随调用变化**。

    这条用例是"不要给 tts 目录加作业号/变体号/随机数"的唯一自动化守卫。加进去之后
    路径仍然互异（所以上面那条隔离用例照样绿），但 pipeline 的缓存优先
    （docs/service/02 §6、test_tts_audio_isolation.py::test_identical_copy_is_synthesised_once）
    在 api 层就失效了：整组重规划与「重掷此条」都会为**没改过的槽位**再付一次配音。
    """
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    engine = _TextWritingTts()
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: engine)
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)
    settings = dict(harness.context.settings)

    first = narration_api._voice(harness.context, _variant_plan("同一份文案"), settings)
    calls_after_first = len(engine.calls)
    second = narration_api._voice(harness.context, _variant_plan("同一份文案"), settings)

    assert calls_after_first == 1
    assert len(engine.calls) == 1, "第二次调用又付了一遍配音：目录随调用变化了"
    assert second.narration_texts[0].audio_path == first.narration_texts[0].audio_path
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_produce.py -q -k voice`

Expected: FAIL —— 两条都报 `AttributeError: module 'dramaclip.api.narration' has no attribute '_voice'`

- [ ] **Step 3: 建 `_voice`**

`service/dramaclip/api/narration.py`，在 `_collect_episode_inputs`（实测 `:275`）之前新增：

```python
def _voice(context: AppContext, plan: PlanData, settings: dict[str, str]) -> PlanData:
    """配音：plan_variants 唯一的配音出口，只负责给出 tts 目录与 models 目录。

    **路径隔离不是本函数的事**：文件名由 `pipeline._content_addressed_audio` 按
    `(slot_id, text, voice, engine)` 内容寻址（commit 9b42f24），同名 ⟺ 同内容，
    所以 K 条同模式变体、并发的两个作业、重规划的两轮都不可能互相覆盖。
    本函数**不得**给这个目录加作业号/变体号/随机数——那会让 pipeline 的缓存优先
    在 api 层失效（`test_tts_audio_isolation.py::test_identical_copy_is_synthesised_once`
    钉的"同文案不二次付费"），而换不来任何正确性收益；`test_voice_keeps_the_cross_call_cache`
    守着这一条。

    **无条件调用，不要包一层 `if plan.narration_texts`**：无槽位时（raw_clip /
    subtitle_flow）`synthesize_narration_texts` 自己早退，但它先跑 `_assert_voiceable`——
    那是"带旁白段却没有文案表"的静音片唯一会被拦下的地方，跳过它等于把 §3.3.1 的
    禁止级降级从后门放回。

    这些音频文件因此是承重存储：《定案一》让配音归规划侧，方案可能在几小时后、
    几次重启后才被 `export.submit` 渲染，届时读的就是这里回填的 `audio_path`。
    全仓没有任何路径清理 work_dir（`shutil.rmtree` 只出现在 `api/models.py:119`，
    删的是模型目录），这个事实就此成为契约。**并且内容寻址意味着文案相同的两条方案
    共用同一个文件**，所以将来的回收站不能按作业或按时间删——见《P-3 交接规格》第 1 条。
    """
    return narration_pipeline.synthesize_narration_texts(
        plan, settings, context.work_dir / "tts", context.data_dir / "models"
    )
```

并把 `_generate_one` 尾部的四行（实测 `api/narration.py:262-265`）：

```python
    if plan.narration_texts:
        tts_dir = context.work_dir / "tts"
        models_dir = context.data_dir / "models"
        plan = narration_pipeline.synthesize_narration_texts(plan, settings, tts_dir, models_dir)
```

替换为一行（`_generate_one` 在 Task 6 整体删除，此处只为让本任务的测试与既有套件同时成立）：

```python
    plan = _voice(context, plan, settings)
```

（**这一行顺带让 `_assert_voiceable` 对无槽位模式也开始生效**——原来的 `if plan.narration_texts:` 把整段跳过了。这不是行为回归：`_assert_voiceable` 对 `raw_clip`/`subtitle_flow` 是空转（`modes.build_raw_clip` 与 `modes_w9.build_subtitle_flow` 的段全是 `audio="original"`、都不写 `narration_id`），而它**能**拦住"带 narration/ducked 段却没有文案表"的自相矛盾方案。Step 4 的全量回归会验这一点。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_produce.py tests/engines/narration/test_tts_audio_isolation.py tests/api/test_narration_audio_chain.py -q`

Expected: PASS（新增 2 条 + 既有全绿）。后两个文件是 `9b42f24` **已落地的守卫**，本任务一行 pipeline 合成逻辑都没改，它们必须照旧全绿——若红了，说明 `_voice` 或 Step 3 那一行改动碰坏了什么，就地修，**不要改它们的断言**。

- [ ] **Step 5: 改 `_synthesize_into` 的 docstring（它点名了 Task 6 要删的三个函数）**

`service/dramaclip/engines/narration/pipeline.py`，`_synthesize_into` 的 docstring（实测 `:233-238`）整块替换：

```python
    """缓存优先 + 暂存落位：命中即复用，未命中先写临时名、成功后原子搬进最终路径。

    临时名把两种脏产物挡在最终路径之外：合成失败留下的半截 mp3（当场清掉，
    否则下一轮会把它当缓存命中）与并发写同名文件（同模式的 K 条变体、以及执行池里
    并行的多个规划作业都可能同时写一个 slot_id，hardware.max_parallel_jobs 默认 2）
    ——os.replace 原子换入，读者永远只见完整文件。
    """
```

原文逐字写着「与并发写同名文件（`_run_generation_parallel` 双线程、produce 与 generate_plans 重叠）」，那三个名字 Task 6 全部删掉。**不改的后果有两层**：一是注释描述一个不存在的并发来源（假文案，规格 §9.5）；二是 Task 10 Step 6 与《完成判据》#6 的死码 grep 会在这里**永久命中**，把"Expected: 无输出"变成一条假门禁——执行者要么以为坏了，要么去改这个并不属于本任务的文件（B9）。改法是把并发来源如实换成 P-2a 之后的真形状。

Run: `cd service && grep -rn "_run_generation_parallel\|generate_plans\|_run_produce" dramaclip/engines/narration/pipeline.py`

Expected: 无输出。

- [ ] **Step 6: 变异检查**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `_voice` 整函数改成 `return plan`（不调 `synthesize_narration_texts`） | `test_voice_gives_each_variant_its_own_audio`（`audio_path` 为空那条断言） |
| 2 | tts 目录里掺入任何**随调用变化**的成分（最省事：`context.work_dir / "tts" / uuid4().hex`，等价于"按作业/按变体分目录"那一类改动的共同效果） | `test_voice_keeps_the_cross_call_cache`（合成次数 1 → 2）。**这条是原计划三条变异检查的唯一替身**：原来那三条（改回共享目录 / 去掉 job_id / 去掉变体号）在内容寻址之下全都红不了，已删 |
| 3 | `models_dir` 实参改成 `None` | **不红**——两条用例的 TTS 都是替身，`models_dir` 无人读。这是可接受的：它的真实消费者是 `tts.factory.create`，由 `tests/engines/tts` 侧守着；在此为它加断言等于把测试写成实现的镜像 |
| 4 | Step 3 那一行改回 `if plan.narration_texts: plan = _voice(...)` | **不红**，且**这是有意的**：条件调用与无条件调用在九模式上的可观察行为相同（无槽位模式两条路都什么也不做）。差别只出现在"带旁白段却没有文案表"那种自相矛盾方案上——那条由 `pipeline._assert_voiceable` 的既有用例守着，本任务不重复登记 |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_produce.py -q -k voice`

- [ ] **Step 7: 全量回归 + 提交**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest -q`

Expected: PASS（既有 `tests/api/test_analysis.py` 的隔离 flake 除外，它属另一位工程师，不修不碰）

Run: `cd service && ../.venv/Scripts/ruff.exe check . && ../.venv/Scripts/mypy.exe dramaclip`

Expected: 两条都无输出、退出码 0。

```bash
git add service/dramaclip/api/narration.py service/dramaclip/engines/narration/pipeline.py service/tests/api/test_produce.py
git commit -m "refactor(narration): 配音收成唯一出口 _voice，注释随 9b42f24 的内容寻址更正"
```

---

## Task 6: `narration.plan_variants` —— 只规划不渲染

**Files:**
- Modify: `service/dramaclip/api/narration.py`
- Modify: `service/dramaclip/infra/config.py:34`
- Modify: `protocol/schemas/narration.json`
- Modify: `protocol/ts/index.ts`
- Rename: `service/tests/api/test_produce.py` → `service/tests/api/test_plan_variants.py`
- Modify: `service/tests/api/test_data_paths.py:8,18`

- [ ] **Step 1: 加 K 的全局默认值**

`service/dramaclip/infra/config.py`，`DEFAULTS` 里 `"narration.style_id": "auto",` 之后插入：

```python
    # 每模式的方案数 K（规格 §4.3「方案数 K ▾」的全局默认；项目级覆盖走 projects.settings）
    "narration.variants_per_mode": "3",
```

- [ ] **Step 2: 改名测试文件、修 import**

Run: `cd service && git mv tests/api/test_produce.py tests/api/test_plan_variants.py`

Expected: 无输出；`git status --short` 里显示为 `R  service/tests/api/test_produce.py -> service/tests/api/test_plan_variants.py`（**必须是 `R` 而不是 `D`+`??`**，否则历史断在这里，Task 9 Step 6 的对照表就无从按原用例名检索）。

`service/tests/api/test_data_paths.py:8` 的 import 改为：

```python
from tests.api.test_plan_variants import Harness, _seed_project_with_analysis
```

`service/tests/api/test_plan_variants.py` 的文件 docstring 第 1 行改为：

```python
"""narration.plan_variants / export.submit：规划与渲染拆开后的端到端（确定性数据直种）。"""
```

- [ ] **Step 3: 写失败测试**

在 `service/tests/api/test_plan_variants.py` 里，`_seed_project_with_analysis` 之后新增多集种子（**2026-09-12 裁决后种子从 3 集改成 6 集**：选题替身给每条角度两集且各条互不相交，K=3 就需要 2K=6 集；3 集时三条角度会是 `{1,2}/{2,3}/{1,3}`，两两共集 ⇒ 取材重叠 1/3，`overlap_max == 0.0` 那条断言就假红了）：

```python
def _seed_project_with_episodes(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    count: int,
) -> str:
    """建项目 + count 集，每集直种**时间区间互不相交**的分析数据，全部标 done。

    集与集的场景时间刻意错开（第 i 集从 100*i 秒起）：这样「两条角度取不同集」的
    取材重叠恒为 0，用例才不必去猜编排器会挑中哪几段。**注意这与生产形状相反**——
    活库实测十集的场景起点全部从 0.0 开始，集与集的秒轴互相覆盖；错开是为了让
    `overlap` 的读数可预期，跨集秒轴重合那条性质由 `test_casting.py` 与
    `test_cross_episode_arrangement.py` 在引擎层单独钉。
    源文件是同一个 sample_video 复制 count 份——本种子只服务规划路径，不渲染。
    """
    for index in range(1, count + 1):
        shutil.copy(sample_video, tmp_path / f"ep{index}.mp4")
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    project = harness.rpc("project.create", {"name": "多集剧", "source_path": str(tmp_path)})
    harness.rpc("project.scan_episodes", {"project_id": project["id"]})
    project_id = str(project["id"])
    for episode in episodes_repo.list_by_project(memory_db, project_id):
        number = int(episode["episode_number"])
        offset = 100.0 * number
        scenes = [
            {
                "scene_index": i,
                "start": offset + i * 10.0,
                "end": offset + i * 10.0 + 8.0,
                "score": 40 + i * 15,
            }
            for i in range(3)
        ]
        analysis_repo.upsert(
            memory_db,
            str(episode["id"]),
            asr_segments=json.dumps(
                [
                    {"start": offset + 0.2, "end": offset + 3.0, "text": f"第 {number} 集台词一"},
                    {"start": offset + 4.0, "end": offset + 7.0, "text": f"第 {number} 集台词二"},
                ]
            ),
            scene_data="[]",
            audio_features=AudioFeatures().model_dump_json(),
            conflict_scores=json.dumps(scenes),
            highlights=json.dumps(
                [
                    {
                        "scene_index": 2,
                        "start": offset + 20.0,
                        "end": offset + 28.0,
                        "score": 64,
                        "reason": "冲突",
                    }
                ]
            ),
        )
        episodes_repo.set_status(memory_db, str(episode["id"]), "done")
    return project_id


def _stub_language_and_tts(
    monkeypatch: pytest.MonkeyPatch, llm_calls: list[tuple[str, str]]
) -> None:
    """选题、成稿、配音三处替身：规划路径的端到端用例不该等真 LLM 与真 TTS。"""

    class _Llm:
        def __init__(self, _config: Any, timeout_s: float = 60.0) -> None:
            self.timeout_s = timeout_s

        def chat_json(self, system: str, user: str) -> Any:
            llm_calls.append((system, user))
            if "选题操盘手" in system:  # angles._SYSTEM_PROMPT
                wanted = int(re.search(r"需要 (\d+) 条", user).group(1))  # type: ignore[union-attr]
                # 每条角度给**两集、且各条互不相交**（{1,2} / {3,4} / {5,6}）：
                # ① 每条方案因此真的是跨集（规格 §1），用例才测得到裁决要的东西；
                # ② 互不相交 ⇒ 取材重叠恒为 0，`overlap_max == 0.0` 那条断言才成立；
                # ③ 各条的集组合互不相同 ⇒ 成稿前那道 `_reject_same_episode_sibling`
                #    不会误拦。**这三条一起要求种子至少 2K 集**，故本文件的种子是 6 集。
                return {
                    "angles": [
                        {
                            "name": f"角度{i}",
                            "reason": f"第 {2 * i - 1}、{2 * i} 集这条线最狠",
                            "hook": f"第 {2 * i - 1} 集的开场钩子",
                            "episode_numbers": [2 * i - 1, 2 * i],
                        }
                        for i in range(1, wanted + 1)
                    ]
                }
            if "风格库" in system:  # styles._SELECT_SYSTEM_PROMPT
                return {"style_id": "shuanggan", "reason": "全剧靠反问推进"}
            slots = re.findall(r"^\[([^\]]+)\] 要做的事：", user, flags=re.MULTILINE)
            return {"lines": [{"id": slot, "text": f"{slot} 的解说"} for slot in slots]}

    monkeypatch.setattr(angles, "LlmClient", _Llm)
    monkeypatch.setattr(copywriter, "LlmClient", _Llm)
    monkeypatch.setattr(script_driver, "LlmClient", _Llm)
    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _StubTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)


_LLM_SETTINGS = {
    "llm.base_url": "http://llm.test/v1",
    "llm.api_key": "sk-test",
    "llm.model": "test-model",
}


def test_plan_variants_writes_k_plans_without_rendering(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """出口判据本身：阶段③ 只看方案不渲染——K 条方案落库，一条 export 记录都不建。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")
    assert result["k"] == 3 and result["batch_id"] == result["job_id"]

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert len(plans) == 3
    assert [row["variant_index"] for row in plans] == [1, 2, 3]
    assert [row["angle"] for row in plans] == ["角度1", "角度2", "角度3"]
    assert all(row["angle_reason"] for row in plans)
    assert plans[0]["overlap_max"] is None, "首条没有兄弟，重叠率是「无从比」"
    assert all(row["overlap_max"] == 0.0 for row in plans[1:]), "三集互异取材，重叠应为 0"
    assert len({tuple(row["episode_ids"]) for row in plans}) == 3, "三条角度取的是同一集"

    assert harness.rpc("export.list", {"project_id": project_id}) == [], (
        "规划阶段不得建任何出片记录——那正是 produce 时代的病"
    )
    for row in plans:
        plan = PlanData.model_validate(row["plan_data"])
        assert plan.planner == "llm_script"
        assert all(text.audio_path for text in plan.narration_texts), "方案落库时必须已配音"

    selection_calls = sum(1 for system, _user in calls if "选题操盘手" in system)
    assert selection_calls == 1, f"选题应每模式一次，实得 {selection_calls} 次"


def test_one_variant_failure_does_not_kill_its_siblings(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败粒度=单条方案：第 2 条配音缺件，第 1、3 条照样落库。

    这是 P-1.5 的「失败粒度=单条方案」从**模式级**下沉到**变体级**：
    原状 try/except 包着整个模式（_run_produce 与 run_group 都是），
    一条变体的 TTS 失败会带走同模式其余 K-1 条。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    real_voice = narration_api._voice
    seen: list[int] = []

    def voice_except_second(context: Any, plan: Any, settings: Any) -> Any:
        """按调用序号失败第二条：`_voice` 不再有 index 形参（Task 5 重写后是三个入参）。"""
        seen.append(len(seen) + 1)
        if len(seen) == 2:
            raise RuntimeError("旁白 full-1 合成失败（引擎=edge）：云端不可达")
        return real_voice(context, plan, settings)

    monkeypatch.setattr(narration_api, "_voice", voice_except_second)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))

    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "合成失败" in error, f"失败没点名到角度与原因：{error}"
    assert "全片解说·角度1:" not in error and "全片解说·角度3:" not in error, (
        f"兄弟变体被牵连了：{error}"
    )
    assert seen == [1, 2, 3], f"第 2 条失败后应继续跑第 3 条，实得 {seen}"

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["variant_index"] for row in plans] == [1, 3], "只有失败那条不该落库"
    assert str(result["job_id"]) not in harness.context.cancel_events, "cancel_events 未释放"


def test_one_mode_failure_does_not_kill_other_modes(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """选题失败只带走它自己那个模式的 K 条，其余模式照常出方案。

    记账口径：选题失败按 K 条记，否则界面会把「这个模式的 K 条全没了」
    显示成「这个模式本来就没有方案」。

    **模式对刻意选成一个解说类 + 一个规则类**（`full_narration` + `raw_clip`）：
    这正是 B2/R1 的回归形状——两族不同源（《定案四》），一族在选题上炸了，
    另一族既不该被牵连、也不该被拖去调 LLM。原计划用这一条同时验两件事，
    但没写明，故这里把意图钉进 docstring。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    real_select = angles.select_angles

    def select_except_full(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("mode_label") == "全片解说":
            raise ValueError("选题未产出 3 条合格角度：网关 502")
        return real_select(*args, **kwargs)

    monkeypatch.setattr(angles, "select_angles", select_except_full)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration", "raw_clip"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert error.count("全片解说") == 3, f"选题失败应按 K 条记账，实得：{error}"
    assert "纯原片剪辑" not in error, f"规则类被解说类的选题失败牵连了：{error}"

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert {row["narration_mode"] for row in plans} == {"raw_clip"}, "另一个模式被牵连了"
    assert len(plans) == 3
    assert all(row["angle"] == "" for row in plans), "规则类没有模型选的卖点角度"


def test_rule_modes_never_construct_an_llm_client(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """规格 §4.2：仅「纯原片剪辑」「字幕金句流」不依赖 LLM（B2/R1 的主守卫）。

    钉的是**不构造客户端**，不是"构造了但失败"：替身在 `__init__` 里就炸，
    于是任何一次选题/成稿调用都会当场红，而不是等一个 240 秒超时。
    **故意不配 `llm.*`**——规则类必须在这种设置下也能出满 K 条；
    这正是原计划会挂的地方（`angles.select_angles` 对未配置抛 `LlmUnavailable`）。

    顺带钉住 `planner == "rule"`：`scripts/verify_modes.py` 的 `EXPECT_PLANNER`
    把这两个模式钉在 `"rule"`，规划侧一旦把它们拖进成稿链，九模式门禁会一起红。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)

    class _NoLlm:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            raise AssertionError("规则类模式不得构造 LlmClient（规格 §4.2）")

    monkeypatch.setattr(angles, "LlmClient", _NoLlm)
    monkeypatch.setattr(copywriter, "LlmClient", _NoLlm)
    monkeypatch.setattr(script_driver, "LlmClient", _NoLlm)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["raw_clip", "subtitle_flow"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert len(plans) == 6, f"两个规则模式各 3 条，实得 {len(plans)}"
    assert {row["narration_mode"] for row in plans} == {"raw_clip", "subtitle_flow"}
    for mode in ("raw_clip", "subtitle_flow"):
        rows = [row for row in plans if row["narration_mode"] == mode]
        assert [row["variant_index"] for row in rows] == [1, 2, 3]
        assert len({tuple(row["episode_ids"]) for row in rows}) == 3, (
            f"{mode} 的 3 条取的是同一集——那不是 3 条互异方案，是 1 条复制 3 份"
        )
        assert all(row["angle"] == "" and row["angle_reason"] == "" for row in rows)
        assert rows[0]["overlap_max"] is None, "首条没有兄弟"
        assert all(row["overlap_max"] == 0.0 for row in rows[1:]), "不同集必然零重叠"
        built = PlanData.model_validate(rows[0]["plan_data"])
        assert built.planner == "rule", f"{mode} 被拖进了成稿链：planner={built.planner}"
        assert built.timeline, f"{mode} 出了个空时间轴的方案"


def test_rule_mode_yields_fewer_than_k_and_leaves_a_trace(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
) -> None:
    """全剧只分析完一集时，轮转发窗只够 1 手 → 规则类只出 1 条，且必须留痕。

    规格 §1 允许「每模式产出 **1..K** 条」，所以少出不是失败；但 §3.3 禁止静默：
    少出必须留痕，否则界面会把「这个模式只出了 1 条」显示成「这个模式本来就只能出 1 条」。
    **两条留痕各钉一条断言**：`_rule_variants` 对"少发几手"与"某一手只取到一集"分别打一行
    （《定案四》第 3 点），后者是跨集裁决新长出来的义务——卡片写着"跨集方案"，
    实际只取一集时必须说清楚。本用例不需要任何 LLM/TTS 替身——规则类两个都不碰
    （上一条用例钉死了这一点）。
    """
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["raw_clip"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert len(plans) == 1, f"一集只发得出一手，实得 {len(plans)} 条"
    assert plans[0]["variant_index"] == 1
    assert plans[0]["overlap_max"] is None
    logged = [str(item) for item in harness.sent]
    assert any("轮转发窗只够 1 手" in item and "本模式出 1 条" in item for item in logged), (
        f"少出方案却没留痕（规格 §3.3）：{harness.sent}"
    )
    assert any("其中 1 手只取到一集" in item for item in logged), (
        f"一集的手没被点名成「只取到一集」（卡片会写着跨集而实际没有）：{harness.sent}"
    )


def test_rejected_angle_does_not_pay_for_copy(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7：同一组取材集的两条角度，其重叠闸门必须排在**成稿之前**，否则被拦的白付一次 LLM。

    可判定性是证明出来的、不是猜的：`_plan_one` 的非剧本分支里，角度只进
    `copywriter` 的 `angle_block`，**不进 `build_plan`**——
    `build_plan(mode, scenes, highlights, material, settings)`
    五个入参没有一个来自角度名或理由，而 `scenes`/`material` 都由 `_casting_for`
    从 `variant.episode_numbers` 确定性装配。故时间轴是 `(mode, 取材集组合)` 的纯函数，
    同一组集 ⇒ 同一条时间轴 ⇒ Jaccard = 1.0，成稿前就该判得出来。

    成稿调用数按 copywriter 的 system prompt 认（`_SYSTEM_PROMPT` 首句是
    「你是短剧推广解说编剧」），与选题（「选题操盘手」）、口味层（「风格库」）三者互不混淆。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    # 三条角度全指向第 1 集：与 test_overlapping_angle_is_dropped_not_stored 同一夹具，
    # 但这条用例量的是**成稿次数**，不是错误文案
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name=f"角度{i}", reason=f"理由{i}", hook=f"钩子{i}", episode_numbers=[1]
            )
            for i in (1, 2, 3)
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    copy_calls = sum(1 for system, _user in calls if "解说编剧" in system)
    assert copy_calls == 1, (
        f"被拦的两条角度仍各付了一次成稿，实得 {copy_calls} 次（应为 1）——"
        "闸门排在成稿之后，那笔钱在库里也无从重算"
    )


def test_unknown_episode_in_a_brief_fails_only_that_variant(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_casting_for` 的缺号分支：点名集不在已完成集里就抛，绝不悄悄换一集顶上。

    这条用例是 Task 6 Step 10 变异 #10 的唯一守卫。没有它，把 `_casting_for` 的
    raise 改成"只用点得到的那几集"（或退回 `episodes[0]`）全套照绿——而那正是
    「K 条其实是同一部片切 K 次」的根源之一（每条角度都被悄悄换成同一批集）。
    **跨集之后这条分支的语义从"换一集"变成"少一集"**，两种都禁止：一次点名**全部**
    缺号再抛，运维才知道要补哪几集，而不是补完一集再炸一集。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name="角度1", reason="理由1", hook="钩子1", episode_numbers=[1]
            ),
            angles.AngleBrief(
                name="角度2", reason="理由2", hook="钩子2", episode_numbers=[99]
            ),
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "不在已完成分析的集里" in error, error
    assert "全片解说·角度1:" not in error, f"兄弟变体被牵连了：{error}"
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["angle"] for row in plans] == ["角度1"], "只有点名越界那条不该落库"


def test_named_episode_without_an_analysis_row_fails_only_that_variant(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """角度点名的集**没有 `episode_analysis` 行**：抛，点名到集号，不牵连兄弟（Step 10 #10b）。

    生产上这一支被 `angles._sanitize` 挡在前面（它的 `known_numbers` 取自 `episode_inputs`，
    而没有分析行的集进不了 `episode_inputs`——`_collect_episode_inputs` 对 `record is None`
    直接 `continue`）。**所以本用例桩掉选题**，验的是 `_casting_for` 自己那一层：两层守卫
    不能只留一层，否则哪天放宽 `_sanitize`（例如允许点名"分析失败的集"以便界面解释原因），
    `_plan_one` 就会拿不到素材、在编排器里出一个空时间轴，报出来的却是"没有可用素材"——
    看不出真因是缺分析行，而规格 §3.3.1 要求的是**点名到集号**的响亮失败。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    ep2 = str(
        next(
            episode["id"]
            for episode in episodes_repo.list_by_project(memory_db, project_id)
            if int(episode["episode_number"]) == 2
        )
    )
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(name="角度1", reason="理由1", hook="钩子1", episode_numbers=[1]),
            angles.AngleBrief(name="角度2", reason="理由2", hook="钩子2", episode_numbers=[2]),
        ],
    )

    real_get = analysis_repo.get

    def get_without_episode_2(conn: sqlite3.Connection, episode_id: str) -> Any:
        """只让第 2 集的分析行消失：其余集照常，兄弟变体才有机会证明自己没被牵连。"""
        return None if episode_id == ep2 else real_get(conn, episode_id)

    monkeypatch.setattr(analysis_repo, "get", get_without_episode_2)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "第 2 集分析记录缺失" in error, error
    assert "全片解说·角度1:" not in error, f"兄弟变体被牵连了：{error}"
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["angle"] for row in plans] == ["角度1"], "只有缺分析行那条不该落库"


def test_episode_ids_come_from_the_timeline_not_the_brief(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """落库的 `episode_ids` 从**建好的时间轴**反推，不抄角度点名的那份（Step 10 #16）。

    卡片四要素之一是「取材集区间」（规格 §4.3），而它的数据源就是这一列。抄点名会把
    一集**一帧都没出现**的集列上去——规格 §9.5 的假文案类，且肉眼查不出来
    （成片看着正常，卡片上多写了一集）。

    夹具是"第 2 集分析过但一个冲突场景都没出"；**生产上不必这么构造**：活库实测
    `intro_narration` 一手点了 4 集 `[2,5,6,9]`、时间轴上只出现 2 集（ep2、ep5），
    因为 `_fit_duration` 按播出序填充、270s 的预算在 ep5 就用完了（Task 3c Step 8 的实测表）。
    同一个口径 `script_driver.script_dialogue_plan` 早就在用（它的 `used_ids` 逐字是
    `sorted({seg.episode_id for seg in plan.timeline})`，`script_driver.py:113`）。

    顺带钉住允许级降级的留痕（规格 §3.3）：取不到某一集的画面不是失败，但必须说一声。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    number_to_id = {
        int(episode["episode_number"]): str(episode["id"])
        for episode in episodes_repo.list_by_project(memory_db, project_id)
    }
    # 第 2 集：分析行在、冲突场景表为空（analysis_repo.upsert 是整行覆盖，故原地重种一次）
    analysis_repo.upsert(
        memory_db,
        number_to_id[2],
        asr_segments=json.dumps([{"start": 200.2, "end": 203.0, "text": "第二集台词"}]),
        scene_data="[]",
        audio_features=AudioFeatures().model_dump_json(),
        conflict_scores="[]",
        highlights="[]",
    )
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name="角度1", reason="理由1", hook="钩子1", episode_numbers=[1, 2]
            )
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert len(plans) == 1
    timeline = PlanData.model_validate(plans[0]["plan_data"]).timeline
    assert {segment.episode_id for segment in timeline} == {number_to_id[1]}, (
        "夹具前提塌了：第 2 集没有冲突场景，时间轴上不该出现它"
    )
    assert plans[0]["episode_ids"] == [number_to_id[1]], (
        f"episode_ids 抄了角度点名的两集，卡片会列一集没出现的集：{plans[0]['episode_ids']}"
    )
    logged = [str(item) for item in harness.sent]
    assert any("第 2 集没有冲突场景" in item for item in logged), (
        f"取不到某一集的画面却没留痕（规格 §3.3）：{harness.sent}"
    )


def test_post_copy_overlap_gate_still_guards_cross_episode_modes(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成稿**之后**那道重叠闸门不能被前置闸门取代：生产上 `dialogue_narration` 只剩它。

    前置闸门按集号判，所以它拦不住"取材集互异、画面却几乎重合"这一类——跨集模式的剧本
    由模型按角度现写，正是这一类（成稿前无从判定，只有事后量得到）。本用例**不真跑跨集模式**
    （那要等真 LLM 写剧本，慢且不确定），而是用度量替身把重叠钉成 0.9、并让两条角度取不同集，
    于是前置闸门必然不触发、红的必然是成稿后那一道。
    **没有这条用例，Task 6 Step 10 的变异 #3 就再也红不了**（前置闸门会顶包）。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    monkeypatch.setattr(overlap, "overlap", lambda _left, _right: 0.9)
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name=f"角度{i}", reason=f"理由{i}", hook=f"钩子{i}", episode_numbers=[i]
            )
            for i in (1, 2)
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "重叠 90%" in error, error
    assert "全片解说·角度1:" not in error, f"首条没有兄弟，不该被拦：{error}"
    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["angle"] for row in plans] == ["角度1"]
    copy_calls = sum(1 for system, _user in calls if "解说编剧" in system)
    assert copy_calls == 2, (
        f"跨集模式成稿前判不了重叠，两条都该付成稿——实得 {copy_calls} 次；"
        "若为 1，说明前置闸门被错误地扩到了 dialogue_narration 之外"
    )


def test_overlapping_angle_is_dropped_not_stored(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取材重叠超 60% 的角度当场不出（规格 §4.3）：不落库、点名到撞了谁。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    # 三条角度全指向第 1 集：取材必然完全相同，后两条该被重叠度量拦下
    monkeypatch.setattr(
        angles,
        "select_angles",
        lambda *a, **k: [
            angles.AngleBrief(
                name=f"角度{i}", reason=f"理由{i}", hook=f"钩子{i}", episode_numbers=[1]
            )
            for i in (1, 2, 3)
        ],
    )

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "failed", status
    error = str(status["error"])
    assert "全片解说·角度2:" in error and "重叠" in error and "100%" in error, error
    assert "全片解说·角度3:" in error, f"第三条也该被拦（它与首条同样取材）：{error}"
    # 断言用「标签+冒号」而不是裸角度名：失败串是 "全片解说·角度2: 取材与「角度1」重叠 100%…"，
    # 里面**必然**出现"角度1"（它点的是撞了谁）。裸名断言会假红。
    assert "全片解说·角度1:" not in error, f"首条不该被拦：{error}"

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert [row["angle"] for row in plans] == ["角度1"], "被拦的角度不该落库"


def test_exclude_plan_ids_reaches_the_selection_prompt(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重掷此条：被排除方案的角度名必须进选题 prompt，否则模型会再提同一个卖点。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    first = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    _wait_terminal(harness, str(first["job_id"]))
    plans = plans_repo.list_by_batch(memory_db, project_id, str(first["batch_id"]))
    assert len(plans) == 1

    calls.clear()
    reroll = harness.rpc(
        "narration.plan_variants",
        {
            "project_id": project_id,
            "modes": ["full_narration"],
            "k": 1,
            "exclude_plan_ids": [plans[0]["id"]],
        },
    )
    _wait_terminal(harness, str(reroll["job_id"]))
    selection_prompts = [user for system, user in calls if "选题操盘手" in system]
    assert len(selection_prompts) == 1
    assert f"不得重复的角度：{plans[0]['angle']}" in selection_prompts[0]
    assert reroll["batch_id"] != first["batch_id"], "重掷是新 batch"
    assert len(plans_repo.list_by_project(memory_db, project_id)) == 2, (
        "方案行只追加、永不覆写：export_jobs.narration_plan_id 必须始终指向当初渲染的那一行"
    )


def test_k_defaults_to_the_settings_value(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """不传 k 时读 narration.variants_per_mode；RPC 回显实际用的 K，界面才不必自己猜。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings["narration.variants_per_mode"] = "2"
    result = harness.rpc(
        "narration.plan_variants", {"project_id": project_id, "modes": ["raw_clip"]}
    )
    assert result["k"] == 2


def test_project_override_beats_the_global_default(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """projects.settings 的第一个消费端（docs/service/01 §6 的已知限制在此关掉）。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings["narration.variants_per_mode"] = "3"
    harness.rpc(
        "project.update_settings",
        {"project_id": project_id, "settings": {"narration.variants_per_mode": 1}},
    )
    result = harness.rpc(
        "narration.plan_variants", {"project_id": project_id, "modes": ["raw_clip"]}
    )
    assert result["k"] == 1, "项目级覆盖没生效，或 JSON 里的 int 没被转成 str"


@pytest.mark.parametrize("k", [0, -1, 9])
def test_k_out_of_range_is_rejected_at_the_rpc_boundary(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path, k: int
) -> None:
    """K 越界必须在派发作业之前拦下：进了作业就只是一条 failed 行，界面拿不到错误码。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="narration.plan_variants",
            params={"project_id": project_id, "modes": ["raw_clip"], "k": k},
        )
    )
    assert response.error is not None and response.error.code == -32303, response


def test_unknown_excluded_plan_is_rejected_at_the_rpc_boundary(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="narration.plan_variants",
            params={
                "project_id": project_id,
                "modes": ["raw_clip"],
                "k": 1,
                "exclude_plan_ids": ["不存在的方案"],
            },
        )
    )
    assert response.error is not None and response.error.code == -32304, response


def test_empty_modes_is_rejected(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    response = harness.router.dispatch(
        RpcRequest(
            id=1,
            method="narration.plan_variants",
            params={"project_id": project_id, "modes": []},
        )
    )
    assert response.error is not None and response.error.code == -32302, response


def test_plan_variants_cancel_releases_the_event(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """作业被取消：cancel_events 必须释放，且已产出的方案行留着（规划成果不因取消而回滚）。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    real_voice = narration_api._voice

    def voice_then_cancel(context: Any, plan: Any, settings: Any) -> Any:
        """配完第一条就取消：`_voice` 三个入参（Task 5 重写后无 job_id/mode/index）。"""
        voiced = real_voice(context, plan, settings)
        for event in context.cancel_events.values():
            event.set()
        return voiced

    monkeypatch.setattr(narration_api, "_voice", voice_then_cancel)
    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 3},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "cancelled", status
    assert str(result["job_id"]) not in harness.context.cancel_events, "cancel_events 未释放"
```

文件顶部补 import（`Any` / `re` / `json` / `shutil` / `sqlite3` / `pytest` / `RpcRequest` / `Path` / `PlanData` 该文件已有）。**`angles` 与 `overlap` 必须合并进既有那一行**，不要另起一行——该文件已有 `from dramaclip.engines.narration import copywriter, pipeline, script_driver, styles`，ruff 的 isort 会报 I001（B7b 同一类，实测）：

```python
from dramaclip.engines.narration import (
    angles,
    copywriter,
    overlap,
    pipeline,
    script_driver,
    styles,
)
from dramaclip.infra.storage.repos import plans as plans_repo
```

（合并成一行是 100 字符，正好压在 `line-length = 100` 的边界上，故这里用带尾逗号的括号形——ruff 认这个形状，且将来加模块不必重新折行。`plans_repo` 那行带 `as` 别名，isort 默认不合并别名导入，所以它单独一行是对的。）

- [ ] **Step 4: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q -k "writes_k_plans or variant_failure or mode_failure or rule_mode or rejected_angle_does_not_pay or unknown_episode or named_episode_without or episode_ids_come_from or post_copy or overlapping_angle or exclude_plan_ids or k_defaults or project_override or k_out_of_range or unknown_excluded or empty_modes or cancel_releases"`

Expected: FAIL —— **18 条新用例**（`k_out_of_range` 参数化 3 项，故实为 **20 项**）全红，两种形态：

- 走 `harness.rpc(...)` 的报 `AssertionError: narration.plan_variants RPC 错误: [-32601] 方法不存在`；
- 走 `harness.router.dispatch(...)` 的三条边界用例报 `assert -32601 == -32303`（或 `-32302`/`-32304`）——方法还没注册，拿到的自然是"方法不存在"。

**`-k` 里刻意不写 `plan_variants`**：Step 2 已把文件改名成 `test_plan_variants.py`，而 `-k` 是按**关键字子串**匹配的，模块名 `test_plan_variants` 含 `plan_variants` → 那样会**静默选中整个文件**，把 Task 9 Step 6 才迁移的旧 produce 用例一起拉进来，红的形态就分不清了。上面 17 个片段没有一个是 `test_plan_variants` 的子串，且**逐条对得上 Step 3 的 18 个函数**（`rule_mode` 一个片段命中两条：`rule_modes_never_construct_an_llm_client` 与 `rule_mode_yields_fewer_than_k_and_leaves_a_trace`）。少写一个片段的后果不是"少跑一条"，是**那条用例在 Step 8 之前从没被看过一眼**，而 Step 8 的 Expected 会把它算进通过数里。

- [ ] **Step 5: 改 schema**

`protocol/schemas/narration.json`：

1. **`x-methods` 里删掉 `narration.generate_plans` 与 `narration.produce` 两个整条目**（分别在该数组的第 1 项与第 3 项）。`generate_plans` 被 `plan_variants(k=1)` 完全覆盖，且它在桌面端零组件调用者（只有 `client.ts:114` 定义 `narrationApi.generatePlans`，无人调用）；`produce` 是本任务拆分的对象。**两个都不留并存条目**——契约测试按集合相等校验，留着就是 Python 侧少注册、schema 侧多登记，立刻红。

2. `x-models.NarrationPlan.properties` 末尾（`created_at` 之后）加五个字段：

```json
        "angle": {
          "type": "string",
          "description": "卖点角度名（界面金色标签）；无解说的模式为空串"
        },
        "angle_reason": {
          "type": "string",
          "description": "模型自选这条角度的理由（规格 §4.3 卡片四要素之一）"
        },
        "variant_index": {
          "type": "integer",
          "description": "1..K 的槽位号；不靠 created_at 推，毫秒精度下同批会撞"
        },
        "overlap_max": {
          "type": ["number", "null"],
          "description": "与同 batch 同模式已接受兄弟方案的最大取材重叠（Jaccard，源素材秒）；null=首条无兄弟"
        },
        "batch_id": {
          "type": ["string", "null"],
          "description": "一次 plan_variants 调用产出全组的标识，取该作业 job_id"
        }
```

3. `x-models` 加两个新模型（放在 `NarrationPlan` 之后、`PlanMode` 之前）：

```json
    "PlanCost": {
      "type": "object",
      "required": ["copy_llm_calls", "tts_calls"],
      "properties": {
        "copy_llm_calls": {
          "type": "integer",
          "description": "本条方案的成稿往返数：有旁白槽位即 1，raw_clip/subtitle_flow 为 0。选题往返是模式级共担，不计在单条账上"
        },
        "tts_calls": {
          "type": "integer",
          "description": "配音段数 = 旁白槽位数"
        }
      }
    },
    "PlanDetail": {
      "type": "object",
      "required": ["plan", "cost"],
      "properties": {
        "plan": { "$ref": "#/x-models/NarrationPlan" },
        "cost": { "$ref": "#/x-models/PlanCost" }
      }
    }
```

4. `x-methods` 加两条（放在 `narration.list_plans` 之后）：

```json
    {
      "name": "narration.plan_variants",
      "summary": "阶段③：为选中模式各产出 K 条卖点互异的方案，只规划不渲染（job）",
      "params": {
        "type": "object",
        "required": ["project_id", "modes"],
        "properties": {
          "project_id": { "type": "string" },
          "modes": {
            "type": "array",
            "minItems": 1,
            "items": { "$ref": "#/x-models/PlanMode" }
          },
          "k": {
            "type": "integer",
            "minimum": 1,
            "maximum": 8,
            "description": "每模式方案数；缺省读 narration.variants_per_mode（项目级覆盖优先）。注意 minimum/maximum 在本仓**只是文档**：transport/rpc.py 的 Router.dispatch 不做 JSON Schema 校验，越界由 api/narration.plan_variants 里手写的 `if not 1 <= k <= _MAX_VARIANTS` 拦下并回 -32303。若将来给 Router 加上统一 schema 校验，必须同批决定这两个错误码由谁发（见 P-2a 计划《定案三》末段）"
          },
          "exclude_plan_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "重掷此条：被替换的方案，其角度名进选题排除清单。方案行永不覆写"
          }
        },
        "additionalProperties": false
      },
      "result": {
        "type": "object",
        "required": ["job_id", "k", "batch_id"],
        "properties": {
          "job_id": { "type": "string" },
          "k": { "type": "integer" },
          "batch_id": {
            "type": "string",
            "description": "本组方案的 batch_id（等于 job_id），供 narration.list_plans 按组取"
          }
        }
      }
    },
    {
      "name": "narration.get_plan",
      "summary": "单条方案详情 + 成本账（阶段③ 只读详情、成品库跳回方案）",
      "params": {
        "type": "object",
        "required": ["plan_id"],
        "properties": { "plan_id": { "type": "string" } },
        "additionalProperties": false
      },
      "result": { "$ref": "#/x-models/PlanDetail" }
    }
```

5. `narration.list_plans` 的 `params.properties` 加一个可选过滤（`required` 保持只有 `project_id`）：

```json
          "batch_id": {
            "type": "string",
            "description": "只取该 batch（一次 plan_variants 调用）的方案；缺省取项目全部"
          }
```

- [ ] **Step 6: 同步 `METHOD_NAMES` 与 TS 类型**

`protocol/ts/index.ts`：

1. `METHOD_NAMES` 里 `'narration.generate_plans',` 与 `'narration.produce',` 两行替换为：

```ts
  'narration.plan_variants',
  'narration.get_plan',
```

（`'narration.list_plans'` 与 `'narration.list_styles'` 原位不动。`export.start` → `export.submit` 在 Task 8 做——两处一起改会让本任务的提交无法独立通过契约测试。）

2. `NarrationPlan` 接口追加五个只读字段（放在既有字段之后）：

```ts
  /** 卖点角度名（界面金色标签）；无解说的模式为空串。 */
  readonly angle?: string;
  /** 模型自选这条角度的理由（规格 §4.3 卡片四要素之一）。 */
  readonly angle_reason?: string;
  /** 1..K 的槽位号。 */
  readonly variant_index?: number;
  /** 与同 batch 同模式已接受兄弟方案的最大取材重叠；null=首条无兄弟。 */
  readonly overlap_max?: number | null;
  /** 一次 plan_variants 调用产出全组的标识（= 该作业 job_id）。 */
  readonly batch_id?: string | null;
```

3. 在 `NarrationPlan` 之后新增三个类型：

```ts
/** 一条方案的成本账（规格 §4.4 成本预估卡数据源）。 */
export interface PlanCost {
  readonly copy_llm_calls: number;
  readonly tts_calls: number;
}

/** narration.get_plan 返回体。 */
export interface PlanDetail {
  readonly plan: NarrationPlan;
  readonly cost: PlanCost;
}

/** narration.plan_variants 返回体。 */
export interface PlanVariantsResult {
  readonly job_id: string;
  readonly k: number;
  readonly batch_id: string;
}
```

- [ ] **Step 7: 写 `plan_variants`**

`service/dramaclip/api/narration.py`：

1. 文件 docstring 整块替换：

```python
"""narration 命名空间：规划（plan_variants / list_plans / get_plan）与风格清单。

规划与渲染在此分开（规格 §6 的拆分）：本模块只产出方案行，一条 status='ready' 的行
就是可渲染的成品输入（含配音音频路径），渲染归 export.submit。
任务级上下文（项目名、题材、跨集转写、口味层风格）统一在 _inject_run_settings 装配一次。
"""
```

2. import 区**整块替换**（不是"加两行"——那样 ruff 会报 I001，而 Step 9 的门禁写着"Expected: 无输出"）。实测：本仓 `.venv/Scripts/ruff.exe` 的 isort 要求 ① `from dataclasses import dataclass` 落在 stdlib 块里、`from typing import Any` **之前**（同块内 `import x` 先于 `from x import y`，且 dataclasses < typing）；② `angles`/`casting`/`overlap` **合并进**既有的 `from dramaclip.engines.narration import …` 那一行；③ 带 `as` 别名的导入不合并，各自一行；④ `from dramaclip.engines.narration.casting import …`（无别名）排在 `… import pipeline as narration_pipeline`（有别名）**之前**；⑤ `from dramaclip.infra import config` 排在 `from dramaclip.infra.storage.repos import …` 之前：

```python
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.narration import (
    angles,
    casting,
    copywriter,
    overlap,
    script_driver,
    scriptwriter,
)
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.casting import EpisodeScene, MaterialByEpisode
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.infra import config
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError
```

（上面这块**不含第 1 点的 docstring**，从 `from __future__` 起接到 docstring 之后即可。与现状逐行对比，动了四处：新增 `from dataclasses import dataclass`；`copywriter, script_driver, scriptwriter` 那行扩成六个名字并**因超过 100 字符而折成括号形**（合并成一行是 `from dramaclip.engines.narration import angles, casting, copywriter, overlap, script_driver, scriptwriter`，实测 **105 字符** → E501，故必须折行（上一轮 B7b 记的 96 字符是**没有 `casting`** 的那一版，加了它就过线了））；新增 `from dramaclip.engines.narration.casting import EpisodeScene, MaterialByEpisode`（`_casting_for` 的返回类型注解要用）；新增 `from dramaclip.infra import config`。**`from dramaclip.api.export import ExportRun, render_export` 与 `from dramaclip.infra.storage.repos import exports as exports_repo` 这两行在本点仍然保留**——`_run_produce` 还在用它们，第 12 点删函数时才一起删；提前删会让本步骤之后的树连 import 都过不去。）

3. 错误码常量区（`_ERR_MODE_UNSUPPORTED` 之后）加：

```python
_ERR_VARIANTS_OUT_OF_RANGE = -32303
_ERR_PLAN_NOT_FOUND = -32304
```

4. 模式集合区（`_NARRATION_MODES` 之后）加：

```python
# 剧本驱动的唯一模式。2026-09-12 裁决之后**九个模式都能在一条方案里跨集取画面**
# （Task 3c 的 casting 层给六个规则编排器补上了集身份），所以这个集合不再表示
# "只有它能跨集"——那是一句已经作废的话，留着它就是留下一句关于代码的假话。
# 它现在只表示一件事：**这条方案的时间轴不是 (mode, 取材集) 的纯函数**，
# 因为剧本由模型按角度现写（script_driver.script_dialogue_plan）。于是成稿**前**那道
# 重叠闸门（_reject_same_episode_sibling）对它无效，只能靠成稿**后**的 _worst_overlap 兜。
_SCRIPT_DRIVEN_MODES = frozenset({"dialogue_narration"})

# 界面 K 选择器的上限。再往上选题 prompt 会退化成让模型凑数，
# 而凑出来的角度正是重叠度量要拦的东西——不如在这里就拦掉。
_MAX_VARIANTS = 8
```

**规则类不再另立一个集合**：它就是 `frozenset(SUPPORTED_MODES) - _NARRATION_MODES`（= `_NO_TTS_MODES`），分流处直接写 `if mode in _NARRATION_MODES: … else: …`。理由与本文件既有那句注释同一条——「派生自上面两个集合，**绝不另立第四份手抄模式清单**」。九模式在仓里已经有三面镜子（`SUPPORTED_MODES` / `pipeline.MODE_LABELS` / `desktop/src/components/modeMeta.ts`，见 P-1.5 Task 4 的实测修正），再加一份"规则类清单"就是第四面，而它一旦漂移，坏的正是《定案四》那条用户定案。

5. `register` 整函数替换：

```python
def register(router: Router, context: AppContext) -> None:
    router.register("narration.plan_variants", lambda params: plan_variants(context, params))
    router.register("narration.list_plans", lambda params: list_plans(context, params))
    router.register("narration.get_plan", lambda params: get_plan(context, params))
    router.register("narration.list_styles", lambda _params: list_styles(context))
```

6. 删掉 `generate_plans` 整个函数（原 `:58-85`）。

7. `list_plans` 整函数替换：

```python
def list_plans(context: AppContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """项目方案列表；给了 batch_id 就只取那一组（阶段③ 按组显示）。"""
    project_id = str(params.get("project_id", ""))
    batch_id = params.get("batch_id")
    if batch_id is not None:
        return plans_repo.list_by_batch(context.conn, project_id, str(batch_id))
    return plans_repo.list_by_project(context.conn, project_id)
```

8. 在 `list_plans` 之后新增 `get_plan` 与 `plan_cost`：

```python
def get_plan(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """单条方案详情 + 成本账（规格 §5 #18 阶段③ 详情、#33 成品库跳回方案）。

    list_plans 一次返回项目全部方案连同整份 plan_data；K×模式条数上来之后它不再是
    「看一条」的合理入口，故单条走这里。
    """
    plan_id = str(params.get("plan_id", ""))
    row = plans_repo.get(context.conn, plan_id)
    if row is None:
        raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
    return {"plan": row, "cost": plan_cost(row)}


def plan_cost(row: dict[str, Any]) -> dict[str, int]:
    """一条方案的成本账（规格 §4.4 成本预估卡的数据源）。

    两个数都是恒等推导，故不落库：存下来只多一处会漂的副本（docs/04 §5.2）。
    成稿次数是「有旁白槽位即 1」——§3.3.1 之后不存在「零次 LLM 的解说方案」，
    而 raw_clip / subtitle_flow 没有槽位、确实零次。配音段数就是槽位数。
    **选题往返不在此账上**：它是模式级共担，一个 batch 的选题次数
    = 该 batch 里 DISTINCT narration_mode 的数量。

    **这是"落库口径"，不是"花销口径"，两者可以差**：被成稿后那道重叠闸门拦掉的角度
    已经付了一次成稿，却**不留行**，所以把一个 batch 的 plan_cost 逐条相加会得到
    比真实 LLM 花销**小**的数（最多差 K − 已落库条数）。P-2a 把可判定的那一半前置了
    （`_reject_same_episode_sibling`：同模式同集的两条角度，其时间轴是 (mode, episode_id)
    的纯函数，故重叠必然 100%，成稿前即可拦，一次成稿都不付）；剩下的残余只在
    `dialogue_narration` 上——它的剧本由模型按角度现写，成稿前无从判定。
    详见《定案二》的 R7 段。规格 §4.4 的成本卡是**提交前的预估**（渲染成本），
    与本函数的口径不同，两者不要互相顶替。
    """
    plan = PlanData.model_validate(row["plan_data"])
    voiced = len(plan.narration_texts)
    return {"copy_llm_calls": 1 if voiced else 0, "tts_calls": voiced}
```

9. 新增 `_effective_settings`（放在 `_inject_run_settings` 之前）：

```python
def _effective_settings(context: AppContext, project_id: str) -> dict[str, str]:
    """全局默认 + 项目级覆盖（规格 §4.3 的「默认 + 覆盖」）。

    覆盖值一律 str() 后叠加：Settings 的值类型是 str，而 projects.settings 是 JSON，
    里面的 K 会是 int——不转就在 config.get_int 的 int() 上侥幸通过、
    在别处的字符串拼接上炸。value 为 None 表示「恢复默认」（P-1 的 update_settings
    语义），故跳过而不是写成字符串 "None"。
    """
    settings = dict(context.settings)
    for key, value in projects_repo.get_settings(context.conn, project_id).items():
        if value is not None:
            settings[str(key)] = str(value)
    return settings
```

10. 新增会合点类型与重叠助手（放在 `_effective_settings` 之后）：

```python
@dataclass(frozen=True)
class _Variant:
    """一条待产出的方案：取材意图（名字/理由/集号）+ 成稿时注入的角度块。

    **两个模式族在这个形状上会合**（《定案四》）：解说类的 name/reason 出自选题模型
    （`angles.AngleBrief`）、angle_block 出自 `angles.prompt_block`；规则类
    （raw_clip / subtitle_flow）的三者一律空串，只有 episode_numbers 有值——
    它来自全剧 top-K 冲突窗的确定性推导，不经任何模型。

    会合的收益是失败粒度、进度记账、重叠闸门、配音、落库这五件事**只写一遍**：
    分流只发生在"这条方案从哪来"，不发生在"这条方案怎么落库"。
    name 为空时点名一律退回「第 N 条」（见 `_slot_label`），不许把空串拼进错误文案。
    """

    name: str
    reason: str
    episode_numbers: list[int]
    angle_block: str


def _slot_label(variant: _Variant, index: int) -> str:
    """点名用的人读标签：解说类是角度名，规则类没有角度名，退回「第 N 条」。"""
    return variant.name or f"第{index}条"


@dataclass(frozen=True)
class _OverlapHit:
    """与一条已接受兄弟方案的重叠：名字用来点名，比值用来判阈值与落库。"""

    name: str
    ratio: float


def _worst_overlap(
    plan: PlanData, accepted: list[tuple[_Variant, PlanData]]
) -> _OverlapHit | None:
    """与同模式已接受兄弟里最像的那条比；没有兄弟时回 None（不是 0.0）。

    None 与 0.0 是两件事，落库时必须分得开：前者是「无从比」，后者是「比过、全异」。
    点名走 `_slot_label`：规则类的 name 是空串，直接把空串拼进错误文案会得到
    「取材与「」重叠 …」这种半句话。
    """
    worst: _OverlapHit | None = None
    for index, (variant, other) in enumerate(accepted, start=1):
        ratio = overlap.overlap(plan, other)
        if worst is None or ratio > worst.ratio:
            worst = _OverlapHit(name=_slot_label(variant, index), ratio=ratio)
    return worst


def _reject_same_episode_sibling(
    mode: str, variant: _Variant, accepted: list[tuple[_Variant, PlanData]]
) -> None:
    """成稿**之前**的重叠闸门（R7）：同模式、**同一组取材集**的两条角度，取材必然逐秒相同。

    这不是启发式，是可证的：`_plan_one` 的非剧本分支里，`variant` 只进 `copywriter` 的
    `angle_block`，**不进 `build_plan`**——Task 3c 之后 `build_plan(mode, scenes,
    highlights, material, settings)` 的五个入参没有一个来自角度名或理由，而 `scenes` 与
    `material` 都由 `_casting_for` 从 `variant.episode_numbers` 确定性装配。故时间轴是
    `(mode, 取材集组合)` 的纯函数：同一组集 ⇒ 同一份场景表 ⇒ 同一条时间轴 ⇒
    Jaccard = 1.0，必然超过 60% 阈值。

    **跨集之后这道闸门不但没失效，覆盖面还大了**：原先它按"同集"判（`episode_id` 相等），
    现在按"同一组集"判（`frozenset` 相等）。两条角度都点 `{3, 7}` 与都点 `{3}` 一样必拦；
    点 `{3, 7}` 与点 `{3, 8}` 则放过去，交给成稿后的 `_worst_overlap` 实量。

    既然成稿前就可判，就不该先付一次 LLM 成稿再拦：被拦的角度不落库，
    那笔钱在 narration_plans 里也无从重算（《定案二》的 R7 段）。

    `dialogue_narration` 走不到这里（它在 `_SCRIPT_DRIVEN_MODES` 里：剧本由模型按角度
    现写，**同一组集**也能写出两条压在几乎同一段画面上的剧本，成稿前无从判定），
    那条残余由成稿后的 `_worst_overlap` 兜住——
    `test_post_copy_overlap_gate_still_guards_cross_episode_modes` 钉住那道兜底没被拆掉。
    """
    if mode in _SCRIPT_DRIVEN_MODES:
        return
    wanted = frozenset(variant.episode_numbers)
    for index, (sibling, _plan) in enumerate(accepted, start=1):
        if frozenset(sibling.episode_numbers) == wanted:
            raise ValueError(
                f"取材与「{_slot_label(sibling, index)}」重叠 100%，"
                f"超过 {overlap.OVERLAP_LIMIT:.0%}"
                "——同模式同取材集的两条角度逐秒相同，这条角度不出（规格 §4.3）"
            )
```

11. 新增 `plan_variants`、两个模式族的意图来源、以及共用的 runner（放在 `_collect_episode_inputs` 之后，取代原 `produce`/`_run_produce` 的位置）：

```python
def plan_variants(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段③：为选中模式各产出 K 条方案，只规划不渲染（规格 §6 的拆分）。

    K 的取值顺序：入参 > 项目级覆盖 > 全局默认。回显实际用的 K，界面不必自己算一遍。
    所有可同步判定的错都在派发作业之前抛——进了作业就只是一条 failed 行，
    界面拿不到错误码（docs/service/01 §4 长任务模式第 1 步）。

    **条数按模式族分别算**（规格 §4.3 ④，用户定案）：解说类 = K 条角度，
    规则类 = 全剧 top-K 冲突窗（按集去重后可少于 K，规格 §1 允许 1..K 条）。
    分流在 runner 里，本入口对两族一视同仁：它只管把 K 与模式收下来、把错抛在派发前。
    """
    project_id = str(params.get("project_id", ""))
    if projects_repo.get(context.conn, project_id) is None:
        raise RpcDomainError(_ERR_PROJECT_NOT_FOUND, f"项目不存在: {project_id}")
    modes = [str(mode) for mode in params.get("modes", [])]
    invalid = [mode for mode in modes if mode not in SUPPORTED_MODES]
    if invalid:
        raise RpcDomainError(_ERR_MODE_UNSUPPORTED, f"模式暂未支持: {', '.join(invalid)}")
    if not modes:
        raise RpcDomainError(_ERR_MODE_UNSUPPORTED, "至少选择一个模式")
    done_episodes = [
        episode
        for episode in episodes_repo.list_by_project(context.conn, project_id)
        if episode["status"] == "done"
    ]
    if not done_episodes:
        raise RpcDomainError(_ERR_NO_ANALYSIS, "没有已完成分析的集，请先运行智能分析")

    settings = _effective_settings(context, project_id)
    raw_k = params.get("k")
    k = (
        config.get_int(settings, "narration.variants_per_mode")
        if raw_k is None
        else int(raw_k)
    )
    if not 1 <= k <= _MAX_VARIANTS:
        raise RpcDomainError(
            _ERR_VARIANTS_OUT_OF_RANGE,
            f"方案数 K 必须在 1~{_MAX_VARIANTS} 之间，实得 {k}",
        )
    exclude_plan_ids = [str(item) for item in params.get("exclude_plan_ids", [])]
    excluded_angles = _excluded_angle_names(context, exclude_plan_ids)

    job_id = context.job_store.create("narration", ref_id=project_id)
    cancel_event = threading.Event()
    context.cancel_events[job_id] = cancel_event
    context.executor.submit(
        _run_plan_variants,
        context,
        job_id,
        project_id,
        done_episodes,
        modes,
        k,
        excluded_angles,
        bool(exclude_plan_ids),
        cancel_event,
    )
    return {"job_id": job_id, "k": k, "batch_id": job_id}


def _excluded_angle_names(context: AppContext, exclude_plan_ids: list[str]) -> list[str]:
    """重掷此条：把被替换方案的角度名交给选题，别再提同一个卖点。

    方案不存在在此抛（RPC 边界），不留到作业里——那只会变成一条 failed 行。
    规则类方案的 angle 是空串，故它贡献不出排除项（《定案四》：规则类的重掷是空操作，
    由 runner 如实留痕，不在这里假装排除了什么）。
    """
    names: list[str] = []
    for plan_id in exclude_plan_ids:
        row = plans_repo.get(context.conn, plan_id)
        if row is None:
            raise RpcDomainError(_ERR_PLAN_NOT_FOUND, f"编排方案不存在: {plan_id}")
        if row["angle"]:
            names.append(str(row["angle"]))
    return names


def _run_plan_variants(
    context: AppContext,
    job_id: str,
    project_id: str,
    episodes: list[dict[str, Any]],
    modes: list[str],
    k: int,
    excluded_angles: list[str],
    rerolled: bool,
    cancel_event: threading.Event,
) -> None:
    """逐模式取 K 条方案意图 → 逐条 成稿+配音+落库。

    **两族分流只发生在下面那个 `if mode in _NARRATION_MODES`**（《定案四》）：
    解说类的 K 条来自 `angles.select_angles`（一次 LLM 调用），规则类
    （raw_clip / subtitle_flow）的 K 条来自全剧 top-K 冲突窗（**零 LLM**，
    规格 §4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」）。分流之后，
    失败粒度、进度记账、重叠闸门、配音、落库五件事走同一段代码（`_Variant` 是会合点）。

    失败粒度是**单条方案**：try/except 包在变体循环**内**，一条的 LLM/TTS 失败
    既不带走了它的 K-1 个兄弟，也不带走别的模式。这是 P-1.5「失败粒度=单条方案」
    从模式级下沉到变体级——被本任务删掉的那两个旧 runner，try 都包着整个模式。
    """
    try:
        context.job_store.mark_running(job_id)
        settings = _effective_settings(context, project_id)
        try:
            episode_inputs = _inject_run_settings(context, settings, episodes, modes)
        except Exception as exc:  # noqa: BLE001 - 任务级装配失败必须落进 jobs 表，不能留 running
            _settle_failed(context, job_id, str(exc))
            context.notifier.log("error", f"任务上下文装配失败: {exc}")
            return

        total = len(modes) * k
        done_count = 0
        failures: list[str] = []
        for mode in modes:
            if cancel_event.is_set():
                break
            label = narration_pipeline.MODE_LABELS.get(mode, mode)
            try:
                if mode in _NARRATION_MODES:
                    variants = _angle_variants(
                        context, mode, label, episode_inputs, settings, k, excluded_angles
                    )
                else:
                    variants = _rule_variants(
                        context, label, episodes, k, rerolled=rerolled
                    )
            except Exception as exc:  # noqa: BLE001 - 取意图失败 = 这个模式的 K 条全没了
                # 按 K 条记账：界面才不会把「这个模式一条都没出」显示成「这个模式本来就没有方案」
                failures.extend(f"{label}·第{i}条: {exc}" for i in range(1, k + 1))
                context.notifier.log("error", f"{label} 取方案意图失败: {exc}")
                done_count += k
                context.job_store.set_progress(
                    job_id, round(done_count / total * 100, 1), f"{label} 选题失败"
                )
                continue

            accepted: list[tuple[_Variant, PlanData]] = []
            for index, variant in enumerate(variants, start=1):
                if cancel_event.is_set():
                    break
                tag = f"{label}·{_slot_label(variant, index)}"
                try:
                    _reject_same_episode_sibling(mode, variant, accepted)
                    plan, used_ids = _plan_one(
                        context, mode, episodes, episode_inputs, settings, variant
                    )
                    worst = _worst_overlap(plan, accepted)
                    if worst is not None and worst.ratio > overlap.OVERLAP_LIMIT:
                        raise ValueError(
                            f"取材与「{worst.name}」重叠 {worst.ratio:.0%}，"
                            f"超过 {overlap.OVERLAP_LIMIT:.0%}——这条角度不出（规格 §4.3）"
                        )
                    plan = _voice(context, plan, settings)
                    plans_repo.create(
                        context.conn,
                        project_id,
                        mode,
                        used_ids,
                        plan.model_dump(),
                        angle=variant.name,
                        angle_reason=variant.reason,
                        variant_index=index,
                        overlap_max=None if worst is None else worst.ratio,
                        batch_id=job_id,
                    )
                    accepted.append((variant, plan))
                except Exception as exc:  # noqa: BLE001 - 单条方案失败不中断兄弟与其他模式
                    failures.append(f"{tag}: {exc}")
                    context.notifier.log("error", f"{tag} 方案失败: {exc}")
                done_count += 1
                context.job_store.set_progress(
                    job_id, round(done_count / total * 100, 1), tag
                )

        if cancel_event.is_set():
            context.job_store.mark_cancelled(job_id)
        elif failures:
            detail = "; ".join(failures)
            context.job_store.mark_failed(job_id, detail)
            context.notifier.log("error", f"部分方案失败: {detail}")
        else:
            context.job_store.set_progress(job_id, 100.0)
            context.job_store.mark_completed(job_id)
    except Exception as exc:  # noqa: BLE001 - 逐变体守卫之外的抛出没人接就是一行永停 running
        _settle_failed(context, job_id, f"规划任务异常终止: {type(exc).__name__}: {exc}")
    finally:
        context.cancel_events.pop(job_id, None)


def _angle_variants(
    context: AppContext,
    mode: str,
    label: str,
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    k: int,
    excluded_angles: list[str],
) -> list[_Variant]:
    """解说类：一次选题调用 → K 条卖点互异的角度（《定案二》）。

    选题失败即整个模式失败（按 K 条记账，见 runner）：不许拿残缺的凑数，
    那是 §3.3.1 禁止级「假装有 K 条」。

    **没有 `cross_episode` 这个入参**（2026-09-12 裁决后从 `angles.select_angles` 删掉了）：
    规格 §1 的「跨集方案」是每个模式的定义性属性，不是某几个模式的开关。
    """
    briefs = angles.select_angles(
        mode,
        mode_label=label,
        k=k,
        episode_inputs=episode_inputs,
        settings=settings,
        excluded=excluded_angles,
        trace_dir=context.data_dir / "logs" / "llm",
    )
    return [
        _Variant(
            name=brief.name,
            reason=brief.reason,
            episode_numbers=brief.episode_numbers,
            angle_block=angles.prompt_block(brief),
        )
        for brief in briefs
    ]


def _rule_variants(
    context: AppContext,
    label: str,
    episodes: list[dict[str, Any]],
    k: int,
    *,
    rerolled: bool,
) -> list[_Variant]:
    """规则类（raw_clip / subtitle_flow）：全剧冲突窗排名 → 轮转发成 K 手，一手一条方案。

    规格 §4.3 ④「规则类 = 全剧 top-K 冲突窗（两者不同源，已由用户定案）」定的是**条数**，
    规格 §1「跨集方案」定的是**每条的形状**；轮转发窗同时满足两者（《定案四》第 2 点、
    `pipeline.deal_windows` 的 docstring）。§4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」
    照旧：**本函数不发任何网络请求**——把它们拖进 `angles.select_angles` 就等于把
    "不依赖 LLM"改成"依赖 LLM"，而 select_angles 对未配置抛 LlmUnavailable，
    纯剪辑作业会整族失败（B2/R1）。`test_rule_modes_never_construct_an_llm_client` 钉住。

    name/reason/angle_block 一律空串（《定案四》第 4 点）：规则类没有模型自选的卖点角度，
    也没有旁白槽位去读钩子；界面卡片靠「取材集区间」+ variant_index 区分。
    窗口出处改走 notifier 逐条留痕——那是 §3.3 要求的可见性通道，也是"为什么是这几集"
    唯一可核对的记录。
    """
    scored: list[tuple[int, list[ConflictScore]]] = []
    for episode in episodes:
        record = analysis_repo.get(context.conn, str(episode["id"]))
        if record is None:
            continue
        scored.append(
            (int(episode["episode_number"]), _parse_conflicts(record["conflict_scores"]))
        )
    # limit 给"全部集数"：榜单在这里的用途是**给全集排名**，条数由下面的发窗决定。
    # max(..., 1) 只为让 scored 为空时落到下面那句"无从取窗"，而不是 limit<1 的抛错——
    # 两条都是失败，但前者说的是产品事实，后者说的是调用方传错了参数。
    windows = narration_pipeline.top_conflict_windows(scored, max(len(scored), 1))
    if not windows:
        raise ValueError(f"{label}：全剧没有任何带冲突分的场景，无从取窗")
    hands = narration_pipeline.deal_windows(windows, k)
    if len(hands) < k:
        # 规格 §1 允许「每模式产出 1..K 条」，但 §3.3 禁止静默：少出必须留痕，
        # 否则界面会把「这个模式只出了 N 条」显示成「这个模式本来就只能出 N 条」。
        context.notifier.log(
            "info",
            f"{label}：全剧只有 {len(windows)} 集带冲突窗，轮转发窗只够 {len(hands)} 手，"
            f"本模式出 {len(hands)} 条（规格 §1 的 1..K 条）",
        )
    thin = sum(1 for hand in hands if len(hand) < 2)
    if thin:
        # 集数 < 2 × K 时必有手退化成一集：互不相交的多集手至少需要 2 × K 集。
        # 这是算术不是缺陷，但界面卡片写着"跨集方案"，实际只取一集时必须说清楚。
        context.notifier.log(
            "info",
            f"{label}：全剧只有 {len(windows)} 集带冲突窗、不足 2×{k} 集，"
            f"其中 {thin} 手只取到一集（跨集需要至少 2×K 集才发得开）",
        )
    if rerolled:
        # 窗口榜是确定性的，且规则类的 angle 是空串（贡献不出排除项）：
        # 「重掷此条」对规则类必然原样再出同一条方案。如实说出来，别让用户以为生效了。
        context.notifier.log(
            "info",
            f"{label}：规则类方案由全剧冲突榜确定性推导，「重掷此条」不会改变结果；"
            "要换方案请改方案数或补素材（《定案四》）",
        )
    for rank, hand in enumerate(hands, start=1):
        context.notifier.log(
            "info",
            f"{label}·第 {rank} 条：取第 {'、'.join(str(number) for number in hand)} 集"
            "（全剧冲突窗轮转发窗，不经选题模型）",
        )
    return [
        _Variant(name="", reason="", episode_numbers=hand, angle_block="")
        for hand in hands
    ]


def _plan_one(
    context: AppContext,
    mode: str,
    episodes: list[dict[str, Any]],
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    variant: _Variant,
) -> tuple[PlanData, list[str]]:
    """按取材意图产出一条方案（未配音、未落库）。返回 (方案, **实际用到**的集 id)。

    取材集由意图决定、且一条方案可以横跨多集（规格 §1），不再恒取 episodes[0]——
    那是「K 条其实是同一部片切 K 次」的根源之一。

    返回的集 id 从**建好的时间轴**反推，不用意图点名的那份：编排器可能一帧都没用上
    某一集（活库实测 `intro_narration` 一手点了 4 集、时间轴上只出现 2 集，因为
    `_fit_duration` 按播出序填充、预算在第 2 集就用完了），照点名写进
    `narration_plans.episode_ids` 会让卡片的「取材集区间」列一集没出现的集——
    那是 §9.5 的假文案类。`script_driver.script_dialogue_plan` 早就是这么做的
    （它的 used_ids 逐字是 `sorted({seg.episode_id for seg in plan.timeline})`），
    这里沿用同一个口径。

    **不落库**：`plans_repo.create` 只在 runner 里发生一次，那里才有 batch_id /
    variant_index / overlap_max 三个只有 runner 知道的值。

    **两个分支的缺号守卫不对称，是有意的**：非剧本分支经 `_casting_for` 自己校验缺号
    （它从 `episodes`——全部 done 集——装配，那份清单比选题看到的宽）；剧本分支直接过滤
    `episode_inputs`，不再校验一遍，因为 `angles._sanitize` 的 `known_numbers` 逐字就是
    `{int(ep["number"]) for ep in episode_inputs}`——**同一份清单**。在这里再抄一道守卫，
    就是 docs/04 §5.2 禁止的"同一概念双处定义"，而且两处一旦漂移（例如 `_collect_episode_inputs`
    将来放宽成"没有转写也收进来"），先炸的是那条抄来的。
    """
    trace_dir = context.data_dir / "logs" / "llm"

    if mode == "dialogue_narration":
        wanted = set(variant.episode_numbers)
        scoped = [
            episode for episode in episode_inputs if int(episode["number"]) in wanted
        ]
        if not scoped:
            raise ValueError(f"角度「{variant.name}」的取材集都没有转写")
        context.notifier.log(
            "info",
            f"跨集输入：{len(scoped)} 集 → "
            f"每集约 {scriptwriter.transcript_sampling_quota(len(scoped))} 段摘录",
        )
        return script_driver.script_dialogue_plan(
            scoped, settings, angle_block=variant.angle_block, trace_dir=trace_dir
        )

    scenes, highlights, material = _casting_for(context, episodes, variant)
    plan = narration_pipeline.build_plan(mode, scenes, highlights, material, settings)
    if not plan.timeline:
        # 空时间轴的方案渲染出来是一部 0 秒的片；规划期就该说清楚，不留到导出
        raise ValueError(
            f"取材集 {sorted(set(variant.episode_numbers))} 没有可用素材，这条角度出不了片"
        )
    if plan.narration_texts:
        # 规则类两个模式走不到这里（它们的编排器不产槽位），故 angle_block 恒为空串
        # 也不会被任何人读到——这不是"悄悄留了个空值"，是两族的会合点本来就用不上它。
        # material 按集分开传：跨集时间轴上每个槽位只能读它自己那一集的台词（Task 4 Step 3b）。
        plan = copywriter.write_plan_copy(
            plan,
            material,
            settings,
            mode_label=narration_pipeline.MODE_LABELS.get(mode, mode),
            angle_block=variant.angle_block,
            trace_dir=trace_dir,
        )
    used_ids = sorted({segment.episode_id for segment in plan.timeline})
    return plan, used_ids


def _casting_for(
    context: AppContext,
    episodes: list[dict[str, Any]],
    variant: _Variant,
) -> tuple[list[EpisodeScene], list[HighlightSegment], MaterialByEpisode]:
    """把意图点名的那几集装配成编排器要吃的三样东西（场景表 / 高光表 / 逐集台词）。

    集身份在这里注入（`casting.stamp`）：`episode_analysis.conflict_scores` 是**按集一行**
    的 JSON，集身份就是那一行的主键，所以活库已有的分析结果一行都不用改、
    不需要迁移、也不需要重跑分析（《修订记录》C3）。

    点名集不在已完成集里时**一次点名全部缺号**再抛：逐个抛会让第一条缺号掩盖其余的，
    运维补完一集再跑又炸一集。绝不悄悄换一集顶上，也绝不只用点得到的那几集——被本函数
    取代的老写法是 `_generate_one` 里无条件的一句 `episode_id = str(episodes[0]["id"])`，
    那正是「K 条其实是同一部片切 K 次」的根源之一（每条方案都取第 1 集）。
    """
    wanted = sorted(set(variant.episode_numbers))
    by_number = {int(episode["episode_number"]): episode for episode in episodes}
    missing = [number for number in wanted if number not in by_number]
    if missing:
        raise ValueError(f"取材集 {missing} 不在已完成分析的集里")

    scenes_by_episode: list[tuple[int, str, list[ConflictScore]]] = []
    highlights: list[HighlightSegment] = []
    material: MaterialByEpisode = {}
    for number in wanted:
        episode_id = str(by_number[number]["id"])
        record = analysis_repo.get(context.conn, episode_id)
        if record is None:
            raise ValueError(f"第 {number} 集分析记录缺失（本条方案点名要取它）")
        conflicts = _parse_conflicts(record["conflict_scores"])
        if not conflicts:
            # 分析过但一个冲突场景都没出：这一集对时间轴贡献为零。留痕而不是静默剔除，
            # 否则卡片上的「取材集区间」会列一集实际上一帧都没出现的集（规格 §3.3）。
            context.notifier.log(
                "info", f"第 {number} 集没有冲突场景，本条方案取不到它的画面"
            )
        scenes_by_episode.append((number, episode_id, conflicts))
        highlights.extend(_parse_highlights(record["highlights"]))
        material[episode_id] = casting.EpisodeMaterial(
            number=number,
            asr=narration_pipeline.parse_asr_segments(record["asr_segments"]),
        )
    return casting.stamp(scenes_by_episode), highlights, material
```

12. 删掉 `_generate_one`（原 `:211-272`）、`produce`（原 `:310-333`）、`_run_produce`（原 `:336-413`）、`_newest_ready_plan`（原 `:416-423`）四个函数，**以及随之失去引用的三行 import**：

```python
from dramaclip.api.export import ExportRun, render_export
from dramaclip.infra.storage.repos import exports as exports_repo
```

（**`exports_repo` 那行原计划漏了**（B7a）。实测：它在 `api/narration.py:21` 导入，全文件唯一使用点是 `:377` 的 `exports_repo.create(...)`，那一行在 `_run_produce` 里，随该函数一起消失 → ruff 报 **F401**，而 Step 9 的门禁写着"Expected: 无输出、退出码 0"。`ExportRun`/`render_export` 的唯一使用点同样在 `_run_produce`（`:386-394`）。删完 `api/narration.py` 不再依赖 `api/export.py` 任何东西——**这本身就是"规划侧不碰渲染"的一条静态证据**，值得在提交信息里说一句。）

Run: `cd service && grep -rn "_generate_one\|_run_produce\|_newest_ready_plan\|render_export\|exports_repo\|ExportRun\|_run_generation_parallel\|generate_plans" dramaclip/api/narration.py`

Expected: 无输出。**新写的代码里也不许出现这些名字**（连注释都不行）：Task 10 Step 6 与《完成判据》#6 会拿同一批名字对全 `service/dramaclip` 做死码对账，一处散文命中就会把那条门禁变成假的（B9 就是这么来的）。上面第 11 点的 docstring 因此只说"被本任务删掉的那两个旧 runner"，不点名。

- [ ] **Step 8: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q -k "writes_k_plans or variant_failure or mode_failure or rule_mode or rejected_angle_does_not_pay or unknown_episode or named_episode_without or episode_ids_come_from or post_copy or overlapping_angle or exclude_plan_ids or k_defaults or project_override or k_out_of_range or unknown_excluded or empty_modes or cancel_releases"`

Expected: PASS（**18 条新增用例、20 个参数化项**：Step 3 原有的 11 条 + 上一轮审查为 B2/R1 与 R7 新增的 5 条（`rule_modes_never_construct_an_llm_client` / `rule_mode_yields_fewer_than_k_and_leaves_a_trace` / `rejected_angle_does_not_pay_for_copy` / `unknown_episode_in_a_brief_fails_only_that_variant` / `post_copy_overlap_gate_still_guards_cross_episode_modes`）+ 本轮为跨集裁决新增的 2 条（`named_episode_without_an_analysis_row_fails_only_that_variant` / `episode_ids_come_from_the_timeline_not_the_brief`，对应《定案二》失败模式表的 #10b 与 #16）。`-k` 的片段选择理由见 Step 4。

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/transport/test_contract_sync.py -q`

Expected: **PASS**。Step 5 删掉了 schema 里的 `generate_plans`/`produce`、Step 7 删掉了 Python 侧的注册，两侧集合同步收窄；`plan_variants`/`get_plan` 两侧同步新增。`export.start` 此时两侧都还在（Task 8 才动），故仍相等。**若这里红，说明 Step 5 与 Step 7 的方法集合没对齐——先修齐再往下走，不要靠 Task 9 兜。**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20`

Expected: **此时全套是红的，且红的地方全部可预期**：① `tests/api/test_plan_variants.py` 里那些还打 `narration.produce` / `narration.generate_plans` 的既有用例（Task 9 Step 6 迁移）；② `tests/api/test_data_paths.py`（Task 9 Step 5 迁移）。**逐条核对红的用例都在这两处**——若还有第三处红，那是本任务改坏了什么，就地修掉，不要留给 Task 9。

- [ ] **Step 9: 确认本任务不能独立提交**

契约两侧已对齐，但**这个提交仍然无法独立构建**，理由有三条，全部在 Task 9 里解决：

1. `desktop/src/services/client.ts:112,120` 仍调 `'narration.produce'` 与 `'narration.generate_plans'`，而 `METHOD_NAMES` 里已经没有这两个名字——`rpc<T>(method: MethodName, …)` 的形参类型是 `MethodName`，故 `npm run typecheck` 必红。
2. `scripts/verify_modes.py:459` 仍派发 `narration.produce`，运行时会拿到 `-32601`——九模式门禁就此失效。**而且这里还有一个更隐蔽的坑（B1）**：那个 `Router()` 是在模式循环里**逐轮新建**的（`:456-457`），只 `narration_api.register(router, ctx)` 了一句，而 `export_api` 连 import 都没有（`:39` 只导了 `narration as narration_api`）。所以"把派发改成 `export.submit`"这一步**单改派发必红九个模式**：`Router.dispatch` 查不到方法就回 `-32601 方法不存在`。Task 9 Step 2 的第 1 点就是补这两行，别跳过。
3. `tests/api/test_plan_variants.py` 与 `test_data_paths.py` 里还有一批打旧方法的用例，`pytest` 必红。

所以 Task 6 的 Step 10 只暂存不提交，提交动作在 Task 9 的 Step 8 一次完成（docs/04 §4「每个提交可独立构建」）。

Run: `cd service && ../.venv/Scripts/ruff.exe check dramaclip && ../.venv/Scripts/mypy.exe dramaclip`

Expected: 无输出、退出码 0。若 mypy 报 `re.search(...).group(1)` 的 `Optional`，测试夹具里已给了 `# type: ignore[union-attr]`；若报 `_wait_terminal` 返回值的字段访问，按报错补断言而不是加 ignore。

- [ ] **Step 10: 变异检查 + 暂存（不提交）**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `_run_plan_variants` 的内层 `try/except` 上移一层，包住整个 `for index, variant` 循环 | `test_one_variant_failure_does_not_kill_its_siblings`（`seen == [1, 2, 3]`） |
| 2 | 取意图失败的 `failures.extend(... for i in range(1, k + 1))` 改成 `failures.append(f"{label}: {exc}")` | `test_one_mode_failure_does_not_kill_other_modes`（`error.count("全片解说") == 3`） |
| 3 | 成稿后的 `if worst is not None and worst.ratio > overlap.OVERLAP_LIMIT: raise` 整块删掉 | `test_post_copy_overlap_gate_still_guards_cross_episode_modes`。**注意它不再红 `test_overlapping_angle_is_dropped_not_stored`**：那条用例的三条角度同集，现在由成稿**前**的 `_reject_same_episode_sibling` 拦下（R7 的前置闸门会顶包）。这正是本轮要补那条用例的原因——否则删掉这道闸门全套照绿 |
| 4 | `overlap_max=None if worst is None else worst.ratio` 改成 `overlap_max=0.0 if worst is None else worst.ratio` | `test_plan_variants_writes_k_plans_without_rendering`（`overlap_max is None` 那条断言） |
| 5 | `if not 1 <= k <= _MAX_VARIANTS: raise` 整块删掉 | `test_k_out_of_range_is_rejected_at_the_rpc_boundary` |
| 6 | `_excluded_angle_names` 的 `if row is None: raise` 改成 `continue` | `test_unknown_excluded_plan_is_rejected_at_the_rpc_boundary` |
| 7 | `if not modes: raise` 整块删掉 | `test_empty_modes_is_rejected` |
| 8 | `_effective_settings` 的 `str(value)` 改成 `value` | `test_project_override_beats_the_global_default` |
| 9 | `batch_id=job_id` 改成 `batch_id=None` | `test_plan_variants_writes_k_plans_without_rendering`（`list_by_batch` 取不到任何行） |
| 10 | `_casting_for` 的 `if missing: raise` 改成"只用点得到的那几集"（`wanted = [n for n in wanted if n in by_number]`，删掉 raise） | `test_unknown_episode_in_a_brief_fails_only_that_variant`（Step 3 已给出完整代码；原计划这里写的是"补一条"，那是本计划自己禁止的占位符）。**别写成 `return episodes[0]` 那种单集时代的破坏形态**——`_casting_for` 返回的是三样东西，退回一集要伪造整份装配，破坏得不像真缺陷，红了也说明不了什么 |
| **10b** | **`_casting_for` 的 `if record is None: raise ValueError(f"第 {number} 集分析记录缺失…")` 改成 `continue`（跳过这一集继续装配其余的）** | **`test_named_episode_without_an_analysis_row_fails_only_that_variant`（Step 3 新增）。跳过之后 `scenes_by_episode` 少一集、`build_full` 照样出片、作业 `completed`，于是"点名的集取不到"变成了一部静默少一集的片——正是《定案二》失败模式表第 2 行要拦的形态。这条与 #10 各守一半：#10 守"集号不存在"，#10b 守"集号存在但没有分析行"，两个 raise 删掉任一个另一条用例都不红** |
| **11** | **`_run_plan_variants` 里的 `if mode in _NARRATION_MODES:` 分流删掉，改成无条件调 `_angle_variants`** | **`test_rule_modes_never_construct_an_llm_client`（替身在 `__init__` 里就炸，所以红得干脆）。这是 B2/R1 的主守卫：它红，说明"仅两个纯剪辑模式不依赖 LLM"这条用户定案被推翻了。跨集裁决没有动这条分流的理由，只是动了它**下游**的东西（`_rule_variants` 从"一集一条"改成"轮转发窗"），故本行原样保留** |
| 12 | `_rule_variants` 的 `if len(hands) < k:` 那段 `notifier.log` 整块删掉 | `test_rule_mode_yields_fewer_than_k_and_leaves_a_trace`（第一条留痕断言）。少出方案本身仍然合法（规格 §1 的 1..K），红的是**静默**。**原表这里写的是 `if len(windows) < k:`——那是 C9 轮转发窗之前的判据**，`windows` 是集排名（一集一窗），`hands` 才是发出去的条数；照着旧名去找那一行会找不到，或者更糟，改错一处 |
| 13 | `_reject_same_episode_sibling` 的第一行改成 `if True: return`（即前置闸门失效） | `test_rejected_angle_does_not_pay_for_copy`（成稿次数 1 → 3）。**`test_overlapping_angle_is_dropped_not_stored` 不会红**——成稿后那道闸门会顶包，方案照样不落库；差别只在"有没有白付两次成稿"，而那正是 R7 要修的 |
| 14 | `_reject_same_episode_sibling` 的 `if mode in _SCRIPT_DRIVEN_MODES: return` 整块删掉 | **本文件不红**——`dialogue_narration` 的端到端规划路径在本批次**没有自动化覆盖**（要真 LLM 写剧本，或给 `script_driver` 造一个能产出可控跨集时间轴的替身）。它由九模式真机门禁覆盖，而 Task 11 Step 3 原先只跑 `full_narration`，故上一轮补了 **Step 3b：加跑一次 `dialogue_narration`**。**不要为了"让这条变异能红"而给剧本模式造一个假剧本替身**——那会钉住替身的形状而不是产品的行为。（**常量名与理由都随 C10 换过**：它不再表示"只有这个模式能跨集"——裁决之后九个都能——只表示"这条方案的时间轴不是 `(mode, 取材集组合)` 的纯函数，成稿前判不了重叠"。删掉这行豁免的后果也随之换了：不是"把单集模式误当跨集"，而是**给 `dialogue_narration` 加了一道判不了的前置闸门**，同一组集的两条剧本第二条会被误拦，而它们其实可能压在完全不同的画面上） |
| 15 | `_rule_variants` 的 `if rerolled:` 那段 `notifier.log` 整块删掉 | **本文件不红**：没有用例断言这条留痕（它只在"重掷一条规则类方案"时出现，而那条路径要 P-2.5 的阶段③ 才有入口）。**记在《已知不做》**，等阶段③ 落地时补用例；此处保留代码是因为 §3.3 禁止静默，而不是因为测到了 |
| **16** | **两处破坏各红一半，都在 `test_episode_ids_come_from_the_timeline_not_the_brief` 上：① `_plan_one` 末尾的 `used_ids = sorted({segment.episode_id for segment in plan.timeline})` 改成用 `_casting_for` 点名装配的那份集 id（让它多返回一个 `wanted_ids`，`_plan_one` 直接返回它）；② `_casting_for` 里 `if not conflicts:` 那段 `notifier.log` 整块删掉** | **① 红 `episode_ids == [number_to_id[1]]` 那条断言（实得两集，其中一集一帧都没出现）；② 红「第 2 集没有冲突场景」那条留痕断言。这一行是《定案二》失败模式表第 3 行的落点，也是 Task 3c Step 8 实测表第 1 条注记（活库 `intro_narration` 一手点 4 集、时间轴上只出现 2 集）的唯一自动化守卫。两处必须分开破坏：它们红的是同一条用例的不同断言，一起改就看不出是哪一半失效了** |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q`

暂存（**不提交**，提交在 Task 9）：

```bash
git add service/dramaclip/api/narration.py service/dramaclip/infra/config.py protocol/schemas/narration.json protocol/ts/index.ts service/tests/api/test_plan_variants.py service/tests/api/test_data_paths.py
```

Run: `git status --short`

Expected: 上述路径为 `A`/`M`（已暂存），且 `tests/api/test_produce.py` 显示为已改名。

---

## Task 7: `narration.get_plan` 的用例补齐

`get_plan` 的实现与 schema 已在 Task 6 落地（它与 `plan_variants` 共用 `NarrationPlan` 模型，分两次改 schema 会让契约测试红两轮）。本任务只补它自己的用例——**实现先于用例是这里的例外，理由是契约同步的原子性；例外必须显式记账，故本任务独立成一步而不是混进 Task 6。**

**跨集裁决对本任务的两个问题，都是"核对过、结论是不用改"，故把证据写在这里而不是留给下一个人重算一遍**：

1. **返回体够不够拼出卡片的「取材集区间」（规格 §4.3 ③ 四要素之一）？够。** 两样东西都已在行里：`narration_plans.episode_ids`（`repos/plans.py::_row_to_dict` 把这一列 `json.loads` 成 `list[str]`，且 Task 6 的 `_plan_one` 保证它是**时间轴反推**出来的那份，见 Step 10 #16）与 `plan_data.timeline[*].episode_id/start/end`（逐段的集内相对秒）。**集号不在返回体里，是有意的**：`episode_ids` 存的是集 id，而集号由既有的 `project.get`（`protocol/schemas/project.json` 的 `Episode.episode_number`）给出——在 `PlanDetail` 里再抄一份集号就是 docs/04 §5.2 禁止的"同一概念双处定义"，而两处一旦漂移，卡片会写着"第 3-7 集"而时间轴上其实是另外几集。区间怎么显示（`第2-9集` 还是逐集列举）是 P-2.5 阶段③ 的展示决策。
2. **`plan_cost` 在一条方案跨集时还算得对吗？对，两个数都与集数无关。** `copy_llm_calls` 数的是**成稿往返**：`copywriter.write_plan_copy` 一次调用把全部槽位拼进**一个** prompt（`copywriter.py:114-121` 的 `user_prompt` 由 `_slot_block(全部 texts, …)` 一次生成），它的循环是 `for _ in range(_ATTEMPTS)`（重试，`:125-133`）而不是"逐集一次"；剧本链同理（`scriptwriter.write_script_episodes` 把整份跨集转写按集分组塞进**一个** prompt：`transcript_block` 在 `:227`、`user_prompt` 拼装在 `:241-249`）。`tts_calls` 数的是**槽位**，`synthesize_narration_texts` 逐槽合成、与集无关。所以跨集只改变"这条片有多长、取了几集的画面"，不改变它的 LLM/TTS 账——**Step 1 新增的用例把这一条钉成断言**（两集一条方案，`copy_llm_calls` 仍是 1）。

**Files:**
- Modify: `service/tests/api/test_plan_variants.py`

- [ ] **Step 1: 写用例**

追加到 `service/tests/api/test_plan_variants.py`：

```python
def test_get_plan_returns_row_and_cost(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """规格 §5 #18/#33：单条详情 + 成本账。

    **模式刻意选 `intro_narration` 而不是 `full_narration`（B6）**：`modes_w8.build_full`
    每个 `NarrationText` 恰好配一个 `ducked` 段，所以在它身上 `len(plan.timeline)`
    与 `len(plan.narration_texts)` **恒等**——把 `tts_calls` 改成段数也测不出来。
    `modes.build_intro` 是 3 段 1 槽（首段 `narration`、其余 `original`），两者不等，
    于是断言**字面整数**才有意义。原计划的 `tts_calls == len(plan.narration_texts)`
    是把实现自己的公式又算了一遍，那是实现的镜子，不是测试。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["intro_narration"], "k": 1},
    )
    _wait_terminal(harness, str(result["job_id"]))
    plan_id = str(plans_repo.list_by_batch(memory_db, project_id, result["batch_id"])[0]["id"])

    detail = harness.rpc("narration.get_plan", {"plan_id": plan_id})
    assert detail["plan"]["id"] == plan_id
    assert detail["plan"]["angle"] == "角度1"
    plan = PlanData.model_validate(detail["plan"]["plan_data"])
    # 夹具前提：段数 ≠ 槽位数。前提塌了（比如种子或编排器变了）本用例就退化成
    # full_narration 那种恒等式，所以让它自己说出来，而不是悄悄失去鉴别力。
    assert len(plan.timeline) == 3 and len(plan.narration_texts) == 1, (
        f"夹具前提不成立：段数={len(plan.timeline)}、槽位数={len(plan.narration_texts)}；"
        "两者相等时 tts_calls 的断言就测不出任何事了"
    )
    assert detail["cost"] == {"copy_llm_calls": 1, "tts_calls": 1}


def test_get_plan_of_a_silent_mode_costs_no_llm_call(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    """raw_clip 没有旁白槽位：成稿 0 次。成本卡把它算成 1 次就是虚报。"""
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    row = plans_repo.create(
        memory_db,
        project_id,
        "raw_clip",
        ["ep1"],
        PlanData(mode="raw_clip", timeline=[]).model_dump(),
    )
    detail = harness.rpc("narration.get_plan", {"plan_id": str(row["id"])})
    assert detail["cost"] == {"copy_llm_calls": 0, "tts_calls": 0}


def test_get_plan_exposes_the_episodes_a_plan_spans(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """规格 §1 + §4.3 ③：详情要能说出这条方案取了哪几集、每集哪几段。

    三件事各钉一条断言：
    ① `episode_ids` 与时间轴上的集**逐字相等**（不是"包含"）——多写一集，卡片的
      「取材集区间」就列了一集没出现的集（§9.5 假文案类，Task 6 Step 10 #16 的下游）；
    ② 这条方案**真的**跨了两集，否则①是一条永远绿、什么也没守着的断言（B6 同一类）；
    ③ 每集的段可以按 `episode_id` 分开取回，且区间是**集内相对秒**——这才是"区间"
      两个字的可核对形态，也是渲染侧按 `segment.episode_id` 查 `episode_paths` 的同一个键。

    成本账同时钉住"与集数无关"：两集一条方案仍是一次成稿往返（`copywriter` 把全部槽位
    拼进一个 prompt），配音按槽位计。若哪天有人把成稿改成"逐集一次"，这条会红，
    而那时 `plan_cost` 的口径必须同批改（否则成本卡少报）。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    status = _wait_terminal(harness, str(result["job_id"]))
    assert status["status"] == "completed", status.get("error")
    plan_id = str(plans_repo.list_by_batch(memory_db, project_id, result["batch_id"])[0]["id"])

    detail = harness.rpc("narration.get_plan", {"plan_id": plan_id})
    plan = PlanData.model_validate(detail["plan"]["plan_data"])
    spans_by_episode: dict[str, list[tuple[float, float]]] = {}
    for segment in plan.timeline:
        spans_by_episode.setdefault(segment.episode_id, []).append((segment.start, segment.end))

    assert len(spans_by_episode) == 2, (
        f"夹具前提塌了：这条方案只取到 {sorted(spans_by_episode)} 一集，"
        "于是下面那条 episode_ids 断言在单集方案上也恒成立、什么也没守着"
    )
    assert len(plan.narration_texts) == 6, (
        f"夹具前提塌了：两集各 3 个场景应给出 6 个槽位，实得 {len(plan.narration_texts)}"
    )
    assert detail["plan"]["episode_ids"] == sorted(spans_by_episode), (
        f"episode_ids={detail['plan']['episode_ids']} 与时间轴上的集 "
        f"{sorted(spans_by_episode)} 不一致——卡片的「取材集区间」会说谎"
    )
    assert sum(len(spans) for spans in spans_by_episode.values()) == len(plan.timeline), (
        "按集分组丢了段：区间之和必须还原整条时间轴"
    )
    assert all(end > start for spans in spans_by_episode.values() for start, end in spans), (
        "有零长区间：它在 overlap 的口径里不算素材，卡片上却会占一格"
    )
    # 断**字面整数**，不写 `len(plan.narration_texts)`：后者是把实现自己的公式又算一遍
    # （B6 的教训），前提塌了它照样绿。前提由上面那条 6 槽位断言单独守着。
    assert detail["cost"] == {"copy_llm_calls": 1, "tts_calls": 6}


def test_get_plan_unknown_id_raises(
    memory_db: sqlite3.Connection, tmp_path: Path, sample_video: Path
) -> None:
    project_id = _seed_project_with_analysis(memory_db, tmp_path, sample_video)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    response = harness.router.dispatch(
        RpcRequest(id=1, method="narration.get_plan", params={"plan_id": "不存在"})
    )
    assert response.error is not None and response.error.code == -32304, response


def test_list_plans_can_filter_by_batch(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """阶段③ 按组显示：给了 batch_id 就只回那一组，不给就回项目全部。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 6)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    first = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    _wait_terminal(harness, str(first["job_id"]))
    second = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 2},
    )
    _wait_terminal(harness, str(second["job_id"]))

    assert len(harness.rpc("narration.list_plans", {"project_id": project_id})) == 4
    assert len(
        harness.rpc(
            "narration.list_plans",
            {"project_id": project_id, "batch_id": first["batch_id"]},
        )
    ) == 2
```

- [ ] **Step 2: 跑测试**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q -k "get_plan or filter_by_batch"`

Expected: PASS（**5** 条：`get_plan` 四条 + `filter_by_batch` 一条）

- [ ] **Step 3: 变异检查**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `plan_cost` 的 `1 if voiced else 0` 改成 `1` | `test_get_plan_of_a_silent_mode_costs_no_llm_call`（`copy_llm_calls` 0 → 1） |
| 2 | `plan_cost` 的 `tts_calls` 改成 `len(plan.timeline)` | `test_get_plan_returns_row_and_cost`（`tts_calls` 1 → **3**，因为 `intro_narration` 是 3 段 1 槽）。**在原来的 `full_narration` 夹具上这条变异红不了**：`build_full` 每槽恰好一段 `ducked`，两个数恒等（B6） |
| **2b** | **`plan_cost` 的 `copy_llm_calls` 改成按集数计：`len({seg.episode_id for seg in plan.timeline}) if voiced else 0`（"跨集方案每集各成稿一次"这个想当然的口径）** | **`test_get_plan_exposes_the_episodes_a_plan_spans`（`copy_llm_calls` 1 → 2）。这一条是跨集裁决新长出来的破坏形态：单集时代两个口径恒等，谁都红不了；跨集之后只有这条用例能区分它们。若它红，说明有人把"一次成稿往返"与"取了几集"混成了一件事，而 `copywriter.write_plan_copy` 逐字只发一次请求（`copywriter.py:125-133` 的循环是重试次数）** |
| 3 | `get_plan` 的 `if row is None: raise` 改成 `return {"plan": {}, "cost": {}}` | `test_get_plan_unknown_id_raises` |
| 4 | `list_plans` 的 `if batch_id is not None` 分支整块删掉 | `test_list_plans_can_filter_by_batch` |
| **5** | **（无本任务的破坏）**`test_get_plan_exposes_the_episodes_a_plan_spans` 的 `episode_ids` 那一半守的是 Task 6 `_plan_one` 的 `used_ids` 口径 | **破坏与红法登记在 Task 6 Step 10 #16，此处不重复登记**（同一条不变量抄两遍，将来只有一处会被更新，另一处就成了关于测试的假话——Task 3c Step 9 #13 同一条纪律）。本行存在的唯一目的是让读这张表的人知道：这条用例**有**守卫，只是守卫在别的任务里 |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q`

- [ ] **Step 4: 暂存（不提交，提交在 Task 9）**

```bash
git add service/tests/api/test_plan_variants.py
```

---

## Task 8: `export.submit` 取代 `export.start` + 可渲染性守卫

拆分的另一半。`export.start(plan_id)` 今天**零组件调用者**（只有 `desktop/src/services/client.ts:129` 定义 `exportApi.start`，没有任何组件用它），所以直接改名扩参、不留同名并存——docs/04 §5.2 禁止同一概念双处定义，规格 §2.2 也定案「一次性切换，不做新旧并存灰度」。

**Files:**
- Modify: `service/dramaclip/api/export.py`
- Modify: `protocol/schemas/export.json`
- Modify: `protocol/ts/index.ts`
- Modify: `desktop/src/services/client.ts`（`export const exportApi = {` 到它自己的 `} as const;`；实测是 `:127-132`，**不是原计划写的 `:126-133`**——`:126` 与 `:133` 都是空行，按那个范围逐字替换会吃掉上下各一个空行，虽然不致语法错但会连着改到相邻块的格式。认锚点，别认行号）
- Create: `service/tests/api/test_export_submit.py`

- [ ] **Step 1: 写失败测试**

新建 `service/tests/api/test_export_submit.py`：

```python
"""export.submit：把已规划好的方案排队渲染。

本文件钉四件事：① 一条方案一个 export job（取消/重试的粒度必须是单条片）；
② 拒绝路径逐条给理由，而不是一整批一起炸；③ 可渲染性守卫——规划与渲染拆开后，
render_export 只读库里的 plan_data、自己不做任何配音，一版没配音的方案会被
静默渲成哑片（规格 §3.3.1 禁止级）。守卫由 submit 与 retry 共用，两处必须同形；
④ 守卫不得假设"一条片属于一集"（规格 §1）：跨集方案照常提交，而**每一集**的旁白段
都要查到——"前一集配上了、后一集没配上"是跨集才有的哑片形态，单集用例一条都抓不到。
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dramaclip.api import export as export_api
from dramaclip.engines.narration.models import NarrationText, PlanData, TimelineSegment
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage.repos import exports as exports_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest


def _harness(memory_db: sqlite3.Connection, tmp_path: Path) -> SimpleNamespace:
    context = SimpleNamespace(
        conn=memory_db,
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings={},
        notifier=Notifier(lambda _m: None),
        executor=ThreadPoolExecutor(max_workers=2),
        job_store=jobs_mod.JobStore(memory_db),
        cancel_events={},
    )
    router = Router()
    export_api.register(router, context)  # type: ignore[arg-type]
    return SimpleNamespace(context=context, router=router)


def _rpc(harness: SimpleNamespace, method: str, params: dict[str, Any]) -> Any:
    response = harness.router.dispatch(RpcRequest(id=method, method=method, params=params))
    if response.error is not None:
        raise AssertionError(f"{method} RPC 错误: [{response.error.code}] {response.error.message}")
    return response.result


def _dispatch(harness: SimpleNamespace, method: str, params: dict[str, Any]) -> Any:
    return harness.router.dispatch(RpcRequest(id=method, method=method, params=params))


def _voiced_plan(tmp_path: Path, mode: str = "full_narration") -> PlanData:
    """一条已配音的方案：音频文件真的落在盘上（守卫要 stat 它）。"""
    audio = tmp_path / "tts" / "full-1.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"mp3")
    return PlanData(
        mode=mode,
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=1.25, audio="ducked", narration_id="full-1",
                subtitle_text="第一段解说",
            )
        ],
        narration_texts=[
            NarrationText(id="full-1", text="第一段解说", audio_path=str(audio), duration=1.25)
        ],
    )


def _seed_plan(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    plan_data: PlanData,
    *,
    status: str = "ready",
) -> tuple[str, str]:
    project_id = str(projects_repo.create(memory_db, "提交剧", str(tmp_path))["id"])
    plan_id = str(
        plans_repo.create(
            memory_db, project_id, plan_data.mode,
            # 从时间轴反推，与生产同口径（Task 6 的 `_plan_one`）；写死 ["ep1"] 的话
            # 下面那条跨集夹具会落一行自相矛盾的数据（行说一集、时间轴说两集）
            sorted({segment.episode_id for segment in plan_data.timeline}),
            plan_data.model_dump(),
            status=status,
        )["id"]
    )
    return project_id, plan_id


def test_submit_creates_one_export_job_per_plan(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一条方案一个 export job：规格 §4.4 的条级取消/重试要的就是这个粒度。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    project_id, plan_id = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert len(result["exports"]) == 1 and result["rejected"] == []
    entry = result["exports"][0]
    assert entry["plan_id"] == plan_id
    assert entry["export_id"] and entry["job_id"]

    jobs_row = harness.context.job_store.get(str(entry["job_id"]))
    assert jobs_row is not None and jobs_row["type"] == "export"
    assert jobs_row["ref_id"] == entry["export_id"], "export job 的 ref_id 是 export_id"
    assert len(exports_repo.list_by_project(memory_db, project_id)) == 1


def test_submit_dedupes_plan_ids_within_one_call(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一次调用里重复出现的 plan_id 只出一次片——那是纯 bug，不是"再渲一版"。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id, plan_id, plan_id]})
    assert len(result["exports"]) == 1, f"重复 plan_id 出了多部片：{result}"


def test_submit_rejects_each_bad_plan_with_its_own_reason(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """混合批次是常态：坏的逐条给理由，好的一起走，不许一整批炸掉。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, good = _seed_plan(memory_db, tmp_path, _voiced_plan(tmp_path))
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [good, "不存在的方案"]})
    assert [item["plan_id"] for item in result["exports"]] == [good]
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["plan_id"] == "不存在的方案"
    assert "不存在" in result["rejected"][0]["reason"]


def test_submit_rejects_an_unvoiced_narration_plan(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守卫的本体：有旁白段却没有 audio_path 的方案，渲染出来是一部哑片。

    render_export 只读库里的 plan_data，tts_audio_by_segment 对没有 audio_path 的
    方案返回空表，export_plan 收到 `tts_segments or None` 就当这条片本来没有旁白——
    没有解说声、也没有解说字幕，全程静默（规格 §3.3.1 禁止级）。
    """
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    unvoiced = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=2.0, audio="ducked", narration_id="full-1"
            )
        ],
        narration_texts=[NarrationText(id="full-1", text="第一段解说")],
    )
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, unvoiced)
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == []
    assert "没有配音音频" in result["rejected"][0]["reason"]


def test_submit_rejects_a_plan_whose_audio_file_is_gone(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """定案一的代价：配音文件是承重存储，丢了就地拒绝，别等 ffmpeg 报一句看不懂的错。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    plan_data = _voiced_plan(tmp_path)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, plan_data)
    Path(str(plan_data.narration_texts[0].audio_path)).unlink()
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == []
    assert "配音音频已丢失" in result["rejected"][0]["reason"]


def test_submit_rejects_a_plan_that_is_not_ready(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, plan_id = _seed_plan(
        memory_db, tmp_path, _voiced_plan(tmp_path), status="generating"
    )
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == []
    assert "generating" in result["rejected"][0]["reason"]


def test_submit_rejects_an_empty_timeline(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, PlanData(mode="raw_clip"))
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == []
    assert "时间轴为空" in result["rejected"][0]["reason"]


def test_silent_modes_need_no_audio(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """raw_clip / subtitle_flow 没有旁白槽位，守卫对它们是空转——不得顺手拦住。"""
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    silent = PlanData(
        mode="raw_clip",
        timeline=[TimelineSegment(episode_id="ep1", start=0.0, end=5.0, audio="original")],
    )
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, silent)
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["rejected"] == [], f"无解说模式被守卫误拦：{result}"
    assert len(result["exports"]) == 1


def _cross_episode_plan(tmp_path: Path, *, unvoiced: str = "") -> PlanData:
    """一条横跨两集的方案，两集各一个 ducked 槽位；`unvoiced` 点名的那一集不给音频。

    两集的区间刻意**完全重合**（都是 0.0-1.25s）：活库实测十集的场景起点全部从 0.0 开始，
    集与集的集内相对秒互相覆盖。守卫若按 `(start, end)` 认段而不按
    `(episode_id, start, end)`，这两段就会被当成同一段素材——它今天不这么做，
    这两条用例就是钉住它别开始这么做。
    """
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, episode_id in enumerate(("ep1", "ep2"), start=1):
        slot_id = f"full-{index}"
        audio_path: str | None = None
        if episode_id != unvoiced:
            audio = tmp_path / "tts" / f"{slot_id}-{episode_id}.mp3"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes(b"mp3")
            audio_path = str(audio)
        timeline.append(
            TimelineSegment(
                episode_id=episode_id,
                start=0.0,
                end=1.25,
                audio="ducked",
                narration_id=slot_id,
                subtitle_text=f"第{index}段解说",
            )
        )
        texts.append(
            NarrationText(
                id=slot_id,
                text=f"第{index}段解说",
                audio_path=audio_path,
                duration=1.25,
            )
        )
    return PlanData(mode="full_narration", timeline=timeline, narration_texts=texts)


def test_submit_accepts_a_plan_spanning_two_episodes(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规格 §1：一条方案可以横跨多集，守卫不得假设"一条片属于一集"。

    **渲染侧本来就跨集，两处证据都核过（不是推断）**：`render_export` 的 `episode_paths`
    取自 `episodes_repo.list_by_project(conn, project_id)`——项目**全部**集，不是方案点名的
    那几集（`api/export.py:216-219`）；`dialogue_zones` 逐段按 `segment.episode_id` 预取一次
    （`:223-237`），`encoder.export_plan` 的 `zones_cache` 同样按 `episode_id` 分键
    （`encoder.py:358-370`）。所以这条用例红只有一种可能：守卫或提交路径里被人塞进了
    一个"单集"假设。

    **源文件存在性不在守卫里查，是有意的**：`encoder.export_plan` 对**每一段**做
    `episode_paths.get(segment.episode_id)`，缺就抛
    `EpisodeSourceMissing(f"第 {segment.episode_id} 集源文件缺失")`（`encoder.py:360-362`）——
    逐段查、点名到集，比在守卫里再 stat 一遍更靠得住：守卫跑在**提交时**，而源文件可能在
    渲染前才消失（移动盘、手工清理），只有渲染那一刻的检查才是真的。那次抛出会带着集号
    落进 `export_jobs.error` 与队列页（`api/export.py:297-300`）。在守卫里抄一份是
    docs/04 §5.2 的双处定义，还得为拿 `episode_paths` 多查一次库。
    """
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    plan_data = _cross_episode_plan(tmp_path)
    assert len({segment.episode_id for segment in plan_data.timeline}) == 2, "夹具前提塌了"
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, plan_data)
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["rejected"] == [], f"跨集方案被守卫误拦：{result['rejected']}"
    assert len(result["exports"]) == 1


def test_submit_rejects_an_unvoiced_slot_in_the_second_episode(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守卫必须**逐段**查配音，包括第二集那段——这是跨集才存在的哑片形态。

    单集时代"有一条段没配音"与"整条片没配音"是同一件事；跨集之后多了第三种：
    **前一集配上了、后一集没配上**。渲出来是一部前半段有解说、后半段静默的片，
    而规格 §3.3.1 的禁止级逐字是「半条旁白的片子不可交付」。守卫的遍历若被人写成
    "只查第一集"（最省事的错法：`if segment.episode_id != timeline[0].episode_id: continue`），
    单集用例一条都不红——只有这条会红。
    """
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    plan_data = _cross_episode_plan(tmp_path, unvoiced="ep2")
    _project_id, plan_id = _seed_plan(memory_db, tmp_path, plan_data)
    harness = _harness(memory_db, tmp_path)

    result = _rpc(harness, "export.submit", {"plan_ids": [plan_id]})
    assert result["exports"] == [], f"第二集的哑段被放行了：{result['exports']}"
    reason = result["rejected"][0]["reason"]
    assert "没有配音音频" in reason and "ep2" in reason, (
        f"拒绝理由没点名到出问题的集，运维看不出是哪一集没配上：{reason}"
    )


@pytest.mark.parametrize("params", [{}, {"plan_ids": []}, {"plan_ids": "一个字符串"}])
def test_bad_plan_ids_are_rejected_at_the_rpc_boundary(
    memory_db: sqlite3.Connection, tmp_path: Path, params: dict[str, Any]
) -> None:
    harness = _harness(memory_db, tmp_path)
    response = _dispatch(harness, "export.submit", params)
    assert response.error is not None and response.error.code == -32406, response


def test_retry_shares_the_renderability_guard(
    memory_db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守卫必须被 submit 与 retry 共用：只装一侧的话，重试会把哑片渲出来。

    这条用例是"两处同形"的唯一自动化证据——删掉 retry 侧那一次调用，它就红。
    """
    monkeypatch.setattr(export_api, "_run_export", lambda *_a, **_k: None)
    unvoiced = PlanData(
        mode="full_narration",
        timeline=[
            TimelineSegment(
                episode_id="ep1", start=0.0, end=2.0, audio="ducked", narration_id="full-1"
            )
        ],
        narration_texts=[NarrationText(id="full-1", text="第一段解说")],
    )
    project_id, plan_id = _seed_plan(memory_db, tmp_path, unvoiced)
    export_id = exports_repo.create(memory_db, project_id, plan_id, "full_narration")
    exports_repo.mark_failed(memory_db, export_id, "上一轮渲染失败")
    harness = _harness(memory_db, tmp_path)

    response = _dispatch(harness, "export.retry", {"export_id": export_id})
    assert response.error is not None and response.error.code == -32407, response
    assert exports_repo.get(memory_db, export_id)["status"] == exports_repo.STATUS_FAILED, (
        "拒绝必须发生在 CAS 复位之前，否则一次无效重试就把失败记录洗成了 pending"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_export_submit.py -q`

Expected: FAIL —— **12 条用例（`bad_plan_ids` 参数化 3 项，故实为 14 项）**，多数报 `AssertionError: export.submit RPC 错误: [-32601] 方法不存在`；`test_retry_shares_the_renderability_guard` 报的是 `assert response.error.code == -32407`（`export.retry` 今天就注册着，红的是守卫还没装上去，错误码是 `None`）。两种形态都算"如期失败"。

- [ ] **Step 3: 改 `api/export.py`**

1. 模块 docstring 第 1 行改为：

```python
"""export 命名空间：submit（按方案排队渲染）/ retry（幂等重跑）/ list / list_works。"""
```

2. 错误码常量区改为：

```python
_ERR_PLAN_NOT_FOUND = -32401
_ERR_EXPORT_NOT_FOUND = -32404
_ERR_EXPORT_NOT_RETRYABLE = -32405  # 导出域 -32400~-32499（见 common.json x-error-codes）
_ERR_NO_PLANS = -32406
_ERR_PLAN_NOT_RENDERABLE = -32407
```

3. `register` 里 `export.start` 那一行替换为：

```python
    router.register("export.submit", lambda params: submit(context, params))
```

4. 删掉 `start` 整个函数（原 `:97-121`），在原位新增 `submit` 与 `_assert_renderable`：

```python
def submit(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段④：把已规划好的方案排队渲染。规划与渲染就此分开（规格 §6 的拆分）。

    一条方案一个 export job：取消与重试的粒度必须是单条片，而不是一次提交
    （规格 §4.4 的条级 `重掷`/`重试` 与 jobs.cancel 都按这个粒度工作）。
    同一次调用里重复出现的 plan_id 只出一次片；跨两次提交重复渲染同一条方案是合法的
    （换了字幕预设再出一版——规格 §4.3 ④ 的字幕预设与连载模式都是"提交时参数"）。

    坏的方案逐条进 `rejected` 并带理由，好的一起走：混合批次是常态，
    一整批炸掉会让"哪条不能出、为什么"重新变成只有日志里才有的信息。
    """
    raw = params.get("plan_ids")
    if not isinstance(raw, list) or not raw:
        raise RpcDomainError(_ERR_NO_PLANS, "plan_ids 必须是非空数组")
    plan_ids = list(dict.fromkeys(str(item) for item in raw))
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for plan_id in plan_ids:
        plan_row = plans_repo.get(context.conn, plan_id)
        if plan_row is None:
            rejected.append({"plan_id": plan_id, "reason": f"编排方案不存在: {plan_id}"})
            continue
        try:
            plan_data = PlanData.model_validate(plan_row["plan_data"])
            _assert_renderable(plan_row, plan_data)
        except RpcDomainError as exc:
            rejected.append({"plan_id": plan_id, "reason": exc.message})
            continue
        project_id = str(plan_row["project_id"])
        export_id = exports_repo.create(
            conn=context.conn,
            project_id=project_id,
            plan_id=plan_id,
            narration_mode=str(plan_row["narration_mode"]),
        )
        job_id = _submit_export(
            context,
            export_id=export_id,
            project_id=project_id,
            plan_row=plan_row,
            plan_data=plan_data,
        )
        accepted.append(
            {"plan_id": plan_id, "export_id": export_id, "job_id": job_id}
        )
    return {"exports": accepted, "rejected": rejected}


def _assert_renderable(plan_row: dict[str, Any], plan_data: PlanData) -> None:
    """提交/重试前的可渲染性守卫：方案行必须是「拿去就能渲」的成品输入。

    规划与渲染拆开后，render_export 只读库里的 plan_data、自己不做任何配音；
    而 tts_audio_by_segment 对没有 audio_path 的方案返回空表，export_plan 收到
    `tts_segments or None` 就当这条片没有旁白——一版没有解说声、也没有解说字幕的
    片子会被静默渲出来（规格 §3.3.1 禁止级「半条旁白的片子不可交付」）。

    配音音频是规划期落在 cache 里的文件，而提交可能发生在几小时甚至几次重启之后，
    所以"文件还在不在"也必须在这里问一次：等 ffmpeg 去撞，报出来的是
    一句运维看不懂的流映射错误。

    submit 与 retry 共用本函数——只装一侧的话，另一侧会把哑片渲出来。
    """
    if plan_row["status"] != "ready":
        raise RpcDomainError(
            _ERR_PLAN_NOT_RENDERABLE, f"方案状态为 {plan_row['status']}，不可渲染"
        )
    if not plan_data.timeline:
        raise RpcDomainError(_ERR_PLAN_NOT_RENDERABLE, "编排时间轴为空")
    voiced = {text.id: text.audio_path for text in plan_data.narration_texts}
    for segment in plan_data.timeline:
        # ducked（全片解说全程压底旁白）与 narration 同权，两者都必须配到音频
        if segment.audio not in ("narration", "ducked"):
            continue
        audio_path = voiced.get(segment.narration_id or "")
        if not audio_path:
            raise RpcDomainError(
                _ERR_PLAN_NOT_RENDERABLE,
                f"旁白段 {segment.episode_id}@{segment.start} 没有配音音频："
                "这条方案未完成配音，渲染出来会是一版没有解说的哑片",
            )
        if not Path(audio_path).is_file():
            raise RpcDomainError(
                _ERR_PLAN_NOT_RENDERABLE,
                f"配音音频已丢失：{audio_path}（重新规划这条方案即可）",
            )
```

5. `retry` 里，`plan_data = PlanData.model_validate(plan_row["plan_data"])` 那一行之后、CAS 复位 `if not exports_repo.reset_for_retry(...)` 之前，插入一行：

```python
    _assert_renderable(plan_row, plan_data)
```

并在其上方加注释：

```python
    # 守卫排在 CAS 复位之前：一次注定渲染失败的重试不该把 failed 记录洗成 pending，
    # 否则它会被下一次启动清扫当成"崩溃残留"再报一次假原因。
```

6. **修两处会随本任务过期的 docstring**（B9 同类：散文里点着即将消失的名字）。这两处不改，`api/export.py` 里就会留下"有三个调用点、其中一个是 produce"这种关于代码的假话，而 Task 10 Step 6 的死码 grep 也会在这里永久命中：

`ExportRun` 的 docstring（实测 `:50-57`）整块替换为：

```python
    """一次导出渲染的不变输入（export_id 之外全部只读，渲染期间不会改写）。

    收成对象前这些值以位置参数在 submit/retry → _submit_export → _run_export →
    render_export 链路上传递，`export_id` 与 `project_id` 同为 str 且相邻——传颠倒
    不会报错，只会把成片渲染进另一个项目。两处调用点共用一个名字即是收益。
    不含 job_id：那个 job 由 _submit_export 就地创建，与渲染输入无关。
    """
```

`_submit_export` 的 docstring（实测 `:74-78`）整块替换为：

```python
    """建 export 任务 → 注册取消事件 → 投递执行池，返回 job_id。

    submit 与 retry 曾各写一遍这四步；取消事件的注册与 _run_export finally 里的回收
    必须成对，两处各写时漏掉一半就留下 cancel_events 无界增长。
    """
```

（原文分别是「start/retry/produce → _run_export → render_export」「三处调用点」「produce 路径复用 render_export 时那个 job 是 produce job」与「start 与 retry 曾各写一遍这四步」。P-2a 之后：调用点是 `submit`/`retry` **两处**，`produce` 路径随 Task 6 消失，`start` 随本任务改名。`ExportRun` 那句"不含 job_id"的原始理由（produce 复用它时 job 是 produce job）也跟着失效，故换成如实的一句。）

- [ ] **Step 4: 改 `protocol/schemas/export.json`**

把 `x-methods` 里 `export.start` 那一条整体替换为：

```json
    {
      "name": "export.submit",
      "summary": "阶段④：把已规划好的方案排队渲染（一条方案一个 export job；规划归 narration.plan_variants）",
      "params": {
        "type": "object",
        "required": ["plan_ids"],
        "properties": {
          "plan_ids": {
            "type": "array",
            "minItems": 1,
            "items": { "type": "string" },
            "description": "要渲染的方案；同一次调用内重复出现只出一次片"
          }
        },
        "additionalProperties": false
      },
      "result": {
        "type": "object",
        "required": ["exports", "rejected"],
        "properties": {
          "exports": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["plan_id", "export_id", "job_id"],
              "properties": {
                "plan_id": { "type": "string" },
                "export_id": { "type": "string" },
                "job_id": { "type": "string" }
              }
            }
          },
          "rejected": {
            "type": "array",
            "description": "逐条拒绝并给理由：混合批次是常态，不该一整批炸掉",
            "items": {
              "type": "object",
              "required": ["plan_id", "reason"],
              "properties": {
                "plan_id": { "type": "string" },
                "reason": { "type": "string" }
              }
            }
          }
        }
      }
    }
```

**`serial_per_episode` 不在本批次，且这是规格已经裁决过的、不是本计划自己收窄的**：规格 §5 #21（`4228bef` 修订后）逐字把它写成 `export.submit(plan_ids, serial_per_episode=true)` 的**提交时参数**，并注「**本参数归 P-2.5** …P-2 的 `plan_variants` 拆分**不交付它**」，§6 的 P-2 行也写着「**不含 `serial_per_episode`**」。故本步的 schema **只有 `plan_ids` 一个属性**。留给 P-2.5 的两句话，写在这里免得它踩：

1. `"additionalProperties": false` 意味着 P-2.5 必须**在这一条 schema 里补上那个属性**，不能只在 Python 侧读 `params.get(...)`；
2. 而**忘了补也不会红**——`transport/rpc.py::Router.dispatch` 不做任何 JSON Schema 校验（《定案三》末段实测），参数会照样进来、照样生效，只有契约文档在说谎。这是"schema 是文档而不是执行者"这条既有事实的又一个实例，P-2.5 若顺手给 Router 加上校验，就会连带改掉本计划三个手写错误码的归属（同一段末尾已交代）。

- [ ] **Step 5: 同步 `METHOD_NAMES` 与 TS 类型**

`protocol/ts/index.ts`：`METHOD_NAMES` 里 `'export.start',` 替换为 `'export.submit',`；并在 `PlanVariantsResult` 之后新增：

```ts
/** export.submit 接受的一条：方案 → 导出记录 → 任务。 */
export interface ExportSubmission {
  readonly plan_id: string;
  readonly export_id: string;
  readonly job_id: string;
}

/** export.submit 拒绝的一条，带人读理由（规格 §4.4 队列页逐条显示）。 */
export interface ExportRejection {
  readonly plan_id: string;
  readonly reason: string;
}

/** export.submit 返回体。 */
export interface ExportSubmitResult {
  readonly exports: readonly ExportSubmission[];
  readonly rejected: readonly ExportRejection[];
}
```

- [ ] **Step 6: 改 `desktop/src/services/client.ts`**

`exportApi` 整块替换——**按锚点定位**：从 `export const exportApi = {` 那一行起，到它自己的 `} as const;` 那一行止（实测 `:127-132`；原计划写的 `:126-133` 把上下两个空行也算进去了）。**上一块是 `listWorks` 函数（`:105-108`），下一块是 `modelsApi`（`:134` 起），两块都不许碰**：

```ts
export const exportApi = {
  submit: (planIds: string[]): Promise<ExportSubmitResult> =>
    rpc<ExportSubmitResult>('export.submit', { plan_ids: planIds }),
  retry: (exportId: string): Promise<{ job_id: string; export_id: string }> =>
    rpc<{ job_id: string; export_id: string }>('export.retry', { export_id: exportId }),
  list: (projectId: string): Promise<ExportJob[]> =>
    rpc<ExportJob[]>('export.list', { project_id: projectId }),
} as const;
```

文件顶部的 `@dramaclip/protocol` 类型 import 里加上 `ExportSubmitResult`。

（`retry` 一并补进来：它 P-1 就落地了却一直没有客户端封装，而 Task 9 的 `useProduceJob` 需要它才能给出"失败可重试"的最小闭环。**只加封装、不加按钮**——按钮是 P-2.5 队列页的事。）

- [ ] **Step 7: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_export_submit.py tests/api/test_export.py tests/api/test_export_retry.py tests/api/test_export_tts_mapping.py -q`

Expected: PASS（`test_export_submit.py` **12 条 / 14 项**，其余三个文件既有用例全绿）。`test_export_retry.py` 的既有夹具用的是 `raw_clip` + 无 `narration_texts`（`tests/api/test_export_retry.py:41-44`），守卫对它是空转，故不受影响。

**那个夹具还顺手证明了"源文件不在守卫里查"是对的**：它的 docstring（`:38-39`）逐字写着「项目下没有任何 episode，渲染时 encoder 必抛 `EpisodeSourceMissing` —— 确定失败，不需真素材」，即"集源文件缺失"这条路径**已有既有用例守在渲染侧**，而且它守的位置比守卫更好（渲染那一刻，而不是提交那一刻）。本任务不动它——若 Step 3 之后它红了，说明守卫拦下了一件本该由渲染报的事，回去把守卫收窄，**不要改它的断言**。

- [ ] **Step 8: 变异检查**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `submit` 的 `list(dict.fromkeys(...))` 改成 `list(raw)` | `test_submit_dedupes_plan_ids_within_one_call` |
| 2 | `_assert_renderable` 的 `if not audio_path: raise` 整块删掉 | `test_submit_rejects_an_unvoiced_narration_plan` **与** `test_submit_rejects_an_unvoiced_slot_in_the_second_episode`（两条同时红——前者守"整条没配音"，后者守"只有后一集没配音"，删掉这一行两种都放行） |
| 3 | `_assert_renderable` 的 `if not Path(audio_path).is_file(): raise` 整块删掉 | `test_submit_rejects_a_plan_whose_audio_file_is_gone` |
| 4 | `_assert_renderable` 的 `if plan_row["status"] != "ready"` 整块删掉 | `test_submit_rejects_a_plan_that_is_not_ready` |
| 5 | `_assert_renderable` 的 `if not plan_data.timeline` 整块删掉 | `test_submit_rejects_an_empty_timeline` |
| 6 | `_assert_renderable` 的 `if segment.audio not in ("narration", "ducked"): continue` 改成只认 `"narration"` | 本文件不红——**ducked 段无音频这条路径缺一条专属用例**。补一条：把 `_voiced_plan` 的 `audio="ducked"` 保留、`narration_texts` 清空、`timeline` 的 `narration_id` 保留，断言 `rejected[0]["reason"]` 含「没有配音音频」，再对本条变异重跑。（**跨集夹具已经覆盖了一半**：`_cross_episode_plan` 的两段都是 `ducked`，故 #2 那条变异在跨集用例上就红了；本行要补的是**单集** ducked 那一格，两条夹具各守一半，别把 #6 当成已被覆盖而跳过） |
| 7 | `retry` 里新插入的 `_assert_renderable(plan_row, plan_data)` 删掉 | `test_retry_shares_the_renderability_guard` |
| 8 | `retry` 里把 `_assert_renderable` 挪到 `reset_for_retry` **之后** | 同上用例的后半段断言（`status` 仍是 `failed`） |
| 9 | `if not isinstance(raw, list) or not raw: raise` 整块删掉 | `test_bad_plan_ids_are_rejected_at_the_rpc_boundary` |
| **10** | **`_assert_renderable` 的配音遍历里插一行"只查第一集"：`if segment.episode_id != plan_data.timeline[0].episode_id: continue`** | **`test_submit_rejects_an_unvoiced_slot_in_the_second_episode`（`exports` 从 `[]` 变成 1 条，第二集的哑段被放行）。⚠️ 本文件其余 11 条用例一条都不红**——它们的方案全是单集，`timeline[0].episode_id` 恒等于每一段的集号，这行 `continue` 在单集方案上是死代码。这就是"跨集才存在的缺陷"的标准形状：它在旧夹具上不可见，而它放出去的是**半条旁白的片子**（规格 §3.3.1 禁止级） |
| **11** | **（覆盖边界，不是一条待跑的变异）`submit` 在调 `_submit_export` 之前把时间轴裁成第一集：`plan_data = plan_data.model_copy(update={"timeline": [s for s in plan_data.timeline if s.episode_id == plan_data.timeline[0].episode_id]})`（"一条片属于一集"这个旧假设的另一种写法）** | **本文件不红**：裁完的方案仍然可渲染，守卫照过，`test_submit_accepts_a_plan_spanning_two_episodes` 只断言"没被拒"。真正红的是渲染产物，而本文件把 `_run_export` 桩掉了。挡住这种裁剪的是另外两处：Task 6 Step 10 #16 的 `used_ids` 口径、Task 11 Step 2 的落库核对（`episode_ids` 与时间轴逐字相等）。**别为了让本文件能红而去断言渲染产物**——那要把真 ffmpeg 拉进单元测试，而 P-2a 的纪律是"渲染侧一行不动、由真机门禁验" |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_export_submit.py -q`

- [ ] **Step 9: 暂存（不提交，提交在 Task 9）**

```bash
git add service/dramaclip/api/export.py protocol/schemas/export.json protocol/ts/index.ts desktop/src/services/client.ts service/tests/api/test_export_submit.py
```

---

## Task 9: 删 `produce` / `generate_plans`，迁门禁与前端调用点

规格 §6 说的是「**拆** `produce`」，不是"在旁边加两个新方法"。留着的理由只有一个（既有页面还能跑），而那个理由由 Step 4 的一次最小改写满足，不需要留方法。规格 §2.2 定案「一次性切换，不做新旧并存灰度」，docs/04 §5.2 禁止同一概念双处定义。

**Files:**
- Modify: `scripts/verify_modes.py`（**八处**，逐处都是实测锚点：① `:39` 的 import 区；② `:75-85` 的 `EXPECT_PLANNER` 推导散文；③ `:322-347` 的 `_mode_table_drift`（只加一条子集核对）；④ `:351-356` 的 argparse 参数区（`ap`，不是 `parser`）；⑤ `:382` 的 `_generate_one` 注释；⑥ `:438-441` 之后插前置条件停机分支；⑦ `:456-465` 的 Router 装配与单次派发段（换成规划+提交两步）；⑧ `:615-641` 的 `columns`/`values`/打印循环（新增 `集数` 列与跨集断言的落点））
- Modify: `desktop/src/features/narration/useProduceJob.ts`（整文件替换）
- Modify: `desktop/src/services/client.ts`（`export const narrationApi = {` 到它自己的 `} as const;`，实测 `:110-125`）
- Modify: `service/tests/api/test_data_paths.py:18-23`
- Modify: `service/tests/api/test_plan_variants.py`（迁移原 produce 用例）
- Modify: `protocol/schemas/jobs.json`
- **不改**：`scripts/verify_e2e.mjs`（另一位工程师的文件；它有两处会失效的派发，见 Step 1b）

- [ ] **Step 1: 确认 `produce` / `generate_plans` / `export.start` 的全部触点**

Run: `cd /d/PersonProjects/DramaClip && grep -rn "narration.produce\|narration\.generate_plans\|export\.start\|_run_produce\|narrationApi.produce\|narrationApi.generatePlans\|exportApi.start" --include=*.py --include=*.ts --include=*.tsx --include=*.json --include=*.md --include=*.mjs . | grep -v node_modules | grep -v "^./docs/superpowers/plans"`

**`--include=*.mjs` 是本轮补上的（R6）**：原计划的 grep 少了它，于是那句「逐条对账，一条都不许漏」正好漏掉唯一一个 `.mjs` 调用方。

Expected: 到本步骤为止，`service/dramaclip/api/narration.py`、`protocol/schemas/narration.json`、`protocol/ts/index.ts` 里的命中应已被 Task 6/8 清空。剩下的实测命中逐条如下（这是审查时在 `9b42f24` 上跑同一条 grep 得到的**全量**，一条不多一条不少）：

| 命中 | 处置 |
|---|---|
| `service/dramaclip/api/export.py:43` `router.register("export.start", …)` | Task 8 Step 3 第 3 点已改成 `export.submit`；若此处仍有命中，说明 Task 8 没做完，回去补 |
| `desktop/src/services/client.ts:112`（`narration.produce`）、`:120`（`narration.generate_plans`）、`:129`（`export.start`） | `:129` 由 Task 8 Step 6 处理；`:112`/`:120` 由本任务 Step 4 处理 |
| `desktop/src/features/narration/useProduceJob.ts:31` | 本任务 Step 4 整文件替换 |
| `scripts/verify_modes.py:459` | 本任务 Step 2 |
| **`scripts/verify_e2e.mjs:152`（`narration.generate_plans`）与 `:168`（`export.start`）** | **本任务不得编辑**——它是另一位工程师的文件（《开工前置》的提交纪律与《文件结构》的"不动"清单都点着它）。走 Step 1b 书面移交 |
| `service/tests/api/test_data_paths.py:18` | 本任务 Step 5 |
| `service/tests/api/test_plan_variants.py`（原 produce 用例若干处） | 本任务 Step 6 |
| `docs/03-IPC协议规范.md:118,119,131` | Task 10 Step 2 |
| `docs/service/01-传输与API层设计.md:66,67` | Task 10 Step 3 |

`docs/superpowers/specs` 与 `docs/superpowers/plans` 里的历史记述**不改**（它们是当时的真相）；上面的 `grep -v` 已经把本计划目录滤掉了，但没滤 `specs`，若命中 specs 属正常，跳过。

**另外跑一条，专找"名字还在、但已无定义"的散文命中**（B9 的教训：散文命中会让"Expected: 无输出"变成假门禁）：

Run: `cd /d/PersonProjects/DramaClip && grep -rn "_generate_one\|_run_generation_parallel\|_newest_ready_plan" --include=*.py --include=*.mjs . | grep -v node_modules`

Expected: **恰好两条** —— `scripts/verify_modes.py:78`（`EXPECT_PLANNER` 的推导散文）与 `scripts/verify_modes.py:382`（模型目录注释）。两条都由 Step 2 的第 4、5 点改掉。`service/dramaclip/` 下应当**零命中**（`api/narration.py` 由 Task 6 清空，`engines/narration/pipeline.py:236-237` 由 Task 5 Step 5 清空），`scripts/verify_e2e.mjs` 也**零命中**（它用的是 RPC 方法名，不是这些内部函数名）。多于两条就逐条查是谁没改。

- [ ] **Step 1b: 把 `scripts/verify_e2e.mjs` 的两处失效派发书面移交属主（不得自己改）**

`scripts/verify_e2e.mjs` 是另一位工程师的文件（OCR 字幕通道那条线），《开工前置》的提交纪律与《文件结构》的"不动"清单都点着它。但 P-2a 合入之后它会**当场坏**：`:152` 派发 `narration.generate_plans`、`:168` 派发 `export.start`，两个方法都被删了，`Router.dispatch` 会回 `-32601 方法不存在`，那个脚本从此每一步都失败。

**不许悄悄改它**（会把他的暂存与语义一起改掉），也**不许当作没看见**（那就是把一个已知坏掉的东西留在树上）。做这三件事：

1. 在本计划末尾的《Task N 落地后的实测修正》里记一条，逐字写清：文件、两处行号、两个旧方法名、对应的新调用形态（`narration.plan_variants` → 等作业 → `narration.list_plans(batch_id)` → `export.submit(plan_ids)` → 等全部 export job），以及"P-2a 合入即失效"这个时点。
2. 在提交信息里点一句（Task 9 Step 8 的提交信息已含 `BREAKING CHANGE` 段，把这两个行号写进去）。
3. 若仓库有 issue/待办机制，开一条指派给该文件的最近提交者（`git log -1 --format=%an -- scripts/verify_e2e.mjs` 取名字）。**不要替他决定新脚本长什么样**——`:159-166` 那段"每模式取 created_at 最新的一条方案"在有了 `batch_id` 之后有更直接的写法，但那是他的判断。

Run: `cd /d/PersonProjects/DramaClip && git log -1 --format="%h %an %ad" -- scripts/verify_e2e.mjs`

Expected: 打印出该文件最近一次提交的哈希、作者与日期——把作者名写进第 1 条记录里，移交才有收件人。

- [ ] **Step 2: 迁 `scripts/verify_modes.py`（九模式门禁）**

这一步有**八个**改动点（2.1–2.8），缺任何一个门禁都会假红或假绿。逐点做，做完再跑 Step 3。**其中 2.8 是 2026-09-12 跨集裁决新加的**（《修订记录》C12），它同时承载"门禁阈值逐条重新推导"这件事——C6 与《定案二》的表格都把推导数字指到了本步，所以它不是一列新表格那么轻，读之前先看它末尾那张阈值表。

**2.1 补 `export_api` 的 import 与注册（B1——不做这一步，九个模式全红）**

`:39` 的 import 区（`from dramaclip.api import narration as narration_api` 那一行之前，isort 顺序：`export` < `narration`）加一行：

```python
from dramaclip.api import export as export_api
```

（**这一行会让 ruff 的 E402 计数从 12 变 13**，实测如此：`scripts/verify_modes.py` 的 import 区排在 `sys.path.insert(0, str(REPO / "service"))` 之后，所以那 12 条 E402 本来就都在。**没有任何门禁会报它**——`ruff`/`mypy` 的门禁都是 `cd service && …`，`npm run lint` 只覆盖 `desktop` workspace，仓库根没有 ruff 配置。记在这里是为了让"顺手跑一下 ruff scripts/"的人不至于以为自己改坏了什么；**不要为了消掉它把 import 挪到 `sys.path.insert` 之前**，那样会 `ModuleNotFoundError`。）

`:456-457` 的 Router 装配（**它在模式循环内，逐轮新建**）替换为：

```python
        router = Router()
        narration_api.register(router, ctx)
        # export_api 必须一起注册：这个 Router 是循环内逐轮新建的，只注册 narration 的话
        # export.submit 会拿到 -32601 方法不存在，九个模式一起红、门禁 exit 1——
        # 而它是 P-1.5 的出口判据，一小时前才 9/9 通过。
        export_api.register(router, ctx)
```

**2.2 把单次派发换成"规划 + 提交"两步，并加 `--plan-only`（B10）**

原 **7** 行（实测 `:459-465`，紧接上面那段 Router 装配；`:459-460` 是一条跨两行的 `dispatch`）：

```python
        resp = router.dispatch(RpcRequest(id=mode, method="narration.produce",
                                          params={"project_id": project_id, "modes": [mode]}))
        if resp.error is not None:
            failures.append(f"{mode}: RPC 失败 {resp.error.message}")
            rows.append({"mode": mode, "status": "rpc-error", "error": resp.error.message})
            continue
        job = wait_job(ctx.job_store, str(resp.result["job_id"]), args.job_timeout)
```

替换为：

```python
        # 规划与渲染已拆开（P-2a）：先规划 K 条方案，再逐条提交渲染。
        # 门禁口径是"每个模式一条片"，故 --variants 默认 1；K>1 只用于 P-2a 自己的复验。
        resp = router.dispatch(RpcRequest(id=mode, method="narration.plan_variants",
                                          params={"project_id": project_id, "modes": [mode],
                                                  "k": args.variants}))
        if resp.error is not None:
            failures.append(f"{mode}: 规划 RPC 失败 {resp.error.message}")
            rows.append({"mode": mode, "status": "rpc-error", "error": resp.error.message})
            continue
        job = wait_job(ctx.job_store, str(resp.result["job_id"]), args.job_timeout)
        if job["status"] != "completed":
            rows.append({"mode": mode, "status": job["status"], "phase": "plan",
                         "elapsed_s": round(time.time() - started, 1),
                         "error": job.get("error")})
            failures.append(f"{mode}: 规划未完成（{job['status']} · {job.get('error')}）")
            continue
        # 一次查出本 batch 的方案 id 与 plan_data：id 用来提交渲染，plan_data 用来数
        # 每条方案时间轴上的集数（2.8 的跨集判据）。分两条查询就是把同一个 batch 读两遍。
        batch_rows = ctx.conn.execute(
            "select id, plan_data from narration_plans where batch_id=?"
            " order by narration_mode, variant_index",
            (str(resp.result["batch_id"]),)).fetchall()
        plan_ids = [str(r[0]) for r in batch_rows]
        # 集数按 (episode_id) 去重后数：一条方案的时间轴可以横跨多集（规格 §1），
        # 而 plan_data.timeline 的 episode_id 与渲染侧查 episode_paths 用的是同一个键。
        episodes_used = [
            len({str(seg.get("episode_id"))
                 for seg in json.loads(str(r[1])).get("timeline", [])})
            for r in batch_rows
        ]
        # 跨集判据（规格 §1，C12）：**至少一条**方案的取材集 ≥2。不是"每条都必须 ≥2"——
        # §1 要的是一条方案**可以**跨集取画面；ultra_short_hook 三个段压在同一个场景上，
        # 恒为一集（C13），故按模式豁免。豁免清单在 SINGLE_EPISODE_MODES，见 2.8。
        if args.require_cross_episode and mode not in SINGLE_EPISODE_MODES:
            if not episodes_used:
                failures.append(f"{mode}: --require-cross-episode 但本 batch 一条方案都没落库")
            elif max(episodes_used) < 2:
                failures.append(
                    f"{mode}: --require-cross-episode 但每条方案都只取一集（集数 {episodes_used}）"
                    "——规格 §1 的「跨集方案」没做到。先分辨是哪一种："
                    "① 看 logs/llm/llm_angles_*.json 里模型给的 episode_numbers，"
                    "若它每条都只点一集，那是选题 prompt 的问题（《开放问题》#1）；"
                    "② 若模型点了多集而时间轴上只剩一集，那是 casting/预算的问题"
                    "（Task 3c：_fit_duration 按播出序填充，预算可能在第二集之前就用完，"
                    "活库实测 intro_narration 一手点 4 集、时间轴上只出现 2 集）")
        if args.plan_only:
            # --plan-only 的判据是**查库**，不是"门禁报没有成品"：把失败当证据是假绿的一种。
            # 这个 batch 的方案一行 export_jobs 都没有，才叫"规划阶段一条片都没渲"。
            # 集数存两份：列里打 max（本行没有"那一条被渲出来的方案"，取最跨的一条），
            # 附注行打全部（2.6），于是"哪几条只取了一集"在终端上看得见，不用去翻 summary.json。
            rec = {"mode": mode, "status": job["status"], "phase": "plan-only",
                   "elapsed_s": round(time.time() - started, 1), "plans": len(plan_ids),
                   "episodes": max(episodes_used, default=0),
                   "episodes_per_plan": episodes_used}
            if not plan_ids:
                failures.append(f"{mode}: --plan-only 规划出 0 条方案")
            else:
                marks = ",".join("?" * len(plan_ids))
                rendered = ctx.conn.execute(
                    f"select count(*) from export_jobs where narration_plan_id in ({marks})",
                    plan_ids).fetchone()[0]
                rec["export_jobs"] = rendered
                if rendered:
                    failures.append(f"{mode}: --plan-only 却建了 {rendered} 行 export_jobs"
                                    "——规划阶段渲染了，拆分没生效")
            rows.append(rec)
            continue
        submit = router.dispatch(RpcRequest(id=mode, method="export.submit",
                                            params={"plan_ids": plan_ids}))
        if submit.error is not None:
            failures.append(f"{mode}: 提交渲染失败 {submit.error.message}")
            rows.append({"mode": mode, "status": "rpc-error", "error": submit.error.message})
            continue
        for item in submit.result["rejected"]:
            failures.append(f"{mode}: 方案 {item['plan_id'][:8]} 不可渲染 —— {item['reason']}")
        export_jobs = [str(item["job_id"]) for item in submit.result["exports"]]
        if not export_jobs:
            rows.append({"mode": mode, "status": "no-export", "phase": "submit"})
            continue
        job = max((wait_job(ctx.job_store, jid, args.job_timeout) for jid in export_jobs),
                  key=lambda item: 0 if item["status"] == "completed" else 1)
```

（`max(..., key=...)` 的口径是"有失败就报失败"：`completed` 排 0、其余排 1，取最大即优先暴露失败行。这比"取最后一条"诚实——`--variants > 1` 时最后一条恰好成功会掩盖前面的失败。取到的 `job` 直接喂给下面原有的 `rec: dict[str, Any] = {...}`（实测 `:466-468`），那一行与它之后的全部断言**一字不动**。）

**2.3 argparse 加三个旗标**

参数区在 `main()` 开头（实测 `:351-356`），变量名是 **`ap`**（`ap = argparse.ArgumentParser()`），**不是 `parser`**——原计划写的是 `parser.add_argument(...)`，照抄会 `NameError`。在 `ap.add_argument("--job-timeout", …)` 之后加：

```python
    ap.add_argument("--variants", type=int, default=1,
                    help="每模式规划几条方案（P-2a 的 K）。门禁默认 1，与九模式口径一致")
    ap.add_argument("--plan-only", action="store_true",
                    help="只规划、不提交渲染，并查库断言该 batch 的 export_jobs 为 0"
                         "（P-2a Task 11 Step 1 用它证明「规划阶段一条片都没渲」）")
    ap.add_argument("--require-cross-episode", action="store_true",
                    help="断言每个模式至少有一条方案的时间轴横跨 ≥2 集（规格 §1 的机器判据，"
                         "P-2a Task 11）。ultra_short_hook 豁免：它三个段压在同一个场景上，"
                         "恒为一集（见 SINGLE_EPISODE_MODES）")
```

**2.4 前置条件停机分支（B11，散文按裁决重写）**

`done` 计数的那句打印（实测 `:438-441`，`print(f"项目 {project_id[:8]} · 已分析 {done} 集 · …")`）**之后**插入：

```python
    # 前置条件（都属"环境未就绪"= 退出码 2，不是产品缺陷）。门禁自己不分析任何东西，
    # 它读的是复制来的 data/data.db 里现成的东西，所以这两条必须显式设卡：
    # ① --variants K：K 条方案的**取材集组合**必须互不相同，否则成稿前那道
    #    _reject_same_episode_sibling 会把第 2..K 条判成 100% 重叠、作业 failed。
    #    只有 1 集时任何角度的取材集都只能是 {1}，K>1 必然失败。
    #    严格说 K 条互异只需要 ≥2 集（{1}、{2}、{1,2} 就是三组），这里按 K 集设卡是
    #    **刻意保守**：取材集由选题模型给，2 集时它很可能三条都点同一组，那时看到的红
    #    分不清是「模型没给出互异角度」还是「素材不够」。宁可先要求 K 集，把两种红分开。
    # ② --require-cross-episode：规格 §1 的判据是"至少存在一条横跨 ≥2 集的方案"，
    #    1 集时它恒假，跑出来只会是一条与产品无关的红。
    if done < args.variants or (args.require_cross_episode and done < 2):
        need = max(args.variants, 2 if args.require_cross_episode else 0)
        print(f"环境未就绪：本次口径需要至少 {need} 集已分析，库里只有 {done} 集。",
              file=sys.stderr)
        print("裁决之后**九个模式都能在一条方案里跨集取画面**（Task 3c 的 casting 层），"
              "所以集数不足不再是「某个模式做不到跨集」，而是两件事：① 只有 1 集时任何两条"
              "角度的取材集都相同 → 成稿前闸门判 100% 重叠 → 第 2..K 条被拦 → 作业 failed；"
              "② --require-cross-episode 要的是「至少一条方案横跨 ≥2 集」，1 集时恒假。"
              "那时看到的红不是产品坏了，是门禁的前提没满足。", file=sys.stderr)
        print(f"要么先把集数分析到 ≥ {need}，要么去掉 --require-cross-episode 并把"
              " --variants 降到 1（九模式门禁的默认口径）。", file=sys.stderr)
        return 2
```

（退出码 **2** = "环境未就绪"，与本文件开头 docstring 里那两档的划分一致：0=通过、1=断言失败、2=环境未就绪。用 1 会把"库里没有足够的集"报成"产品有缺陷"。

**原文那句「解说类模式一条片只取一集（`dialogue_narration` 除外）」在裁决之后是假话**，而且是**有害的**假话：它会让运维照着"再去分析两集"之外的错误方向排查（以为解说类天生跨不了集、去找编排器的 bug）。《修订记录》C12 点名要重写它，重写后的版本把两条前置条件各自的**真理由**写在注释里，而不是复述一个已经作废的模式分类。）

**2.5 改 `EXPECT_PLANNER` 的推导散文与 `:382` 的注释（R5）**

`:75-85` 那段注释整块替换（它原先从 `_generate_one` 的行为推导出这张表，而 Task 6 删掉了 `_generate_one`；不改就会留下一段指向不存在函数的推导，Step 1 的第二条 grep 也会永久命中）：

```python
# 编排来源预期：文案真值化（P-1.5）之后，除零加工两模式外必须是 LLM 成稿。
# 这张表不是抄清单，是从代码事实推出来的（P-2a 拆分后按新函数名重述）：
#   · `api/narration.py::_NO_TTS_MODES` 恰好是 raw_clip / subtitle_flow。P-2a 之后这两个
#     模式走 `_rule_variants`（全剧 top-K 冲突窗，规格 §4.3 ④），**既不选题也不成稿**；
#     `_plan_one` 只在 `plan.narration_texts` 非空时才调 copywriter，
#     于是 `PlanData.planner` 停在默认值 "rule"（`engines/narration/models.py`）；
#   · dialogue_narration 走 `script_driver`，`build_from_script_episodes` 里直接写
#     `planner="llm_script"`；
#   · 其余五个模式由 `_angle_variants` 选题、`copywriter.write_plan_copy` 成稿并置
#     `planner="llm_script"`，而它已无模板兜底（P-1.5 Task 5），拿不到合格文案就抛，
#     不会悄悄退回 "rule"。
# 九模式清单与 `SUPPORTED_MODES` / `pipeline.MODE_LABELS` 逐名核对一致（main() 里还有一道
# 运行时核对，见那里的注释）。
```

`:382` 那一行注释替换为：

```python
    # 模型目录必须是 <data_dir>/models —— api/narration.py::_voice 就是这么拼路径的。
```

**2.6 表格打印：让 `--plan-only` 与集数的证据可见**

打印循环里 `if r.get("audio_roles"):` 那两行（实测 `:640-641`）**之后**插入：

```python
        if r.get("phase") == "plan-only":
            print(f"{'':<29}规划 {r.get('plans', 0)} 条 · 建了 "
                  f"{r.get('export_jobs', 0)} 行 export_jobs（必须为 0）")
        if r.get("episodes_per_plan"):
            # 列里只有 max（见 2.8），逐条的集数在这里打：哪几条只取了一集必须看得见，
            # 否则 --require-cross-episode 绿了也只知道"至少有一条跨了"，不知道其余几条。
            print(f"{'':<29}逐条取材集数：{r['episodes_per_plan']}")
```

（不加这两段，`--plan-only` 跑完只在 `summary.json` 里有数，终端表格里看不出来——而 Task 11 Step 1 的判据正是要**看见** `plans=3`、`export_jobs=0`。**那个 `{'':<29}` 是 18+11 两列的宽度（`模式`+`状态`），2.8 新增的 `集数` 列插在它们右边，故这个 29 不受影响、不要顺手改它**。）

**2.7 保持不动的部分（范围比原计划窄了两处，逐条说清楚）**

- `export_jobs` 的成品定位查询（实测 `:482-484`）**一字不动**：它取"最新一条已完成出片记录"并校验 `narration_mode` 对得上，两步派发之后这个语义不变（`--variants 1` 时一个模式恰好一条成品）。
- **响度窗口、真峰门限、planner 断言、冻结帧断言、插桩覆盖断言全部不动**——这是"渲染侧一行未改"的门禁证据，动它就等于把证据本身改了。2.8 末尾那张表逐条给出"为什么跨集之后它们仍然成立"的推导，**结论是阈值一个字都不改**，但推导必须写在计划里，否则下一个人只能重新猜一遍。
- **`_mode_table_drift()` 要动一处**（原计划写"全部不动"，那是 C12 之前的话）：2.8 新加的 `SINGLE_EPISODE_MODES` 是一份**手抄的模式子集**，而这个文件的既有纪律正是"手抄清单必须与 `SUPPORTED_MODES` 对账，否则新模式会按默认值悄悄判绿"（`:322-328` 的 docstring 逐字如此）。一个写错名字的豁免会让 `--require-cross-episode` 对那个模式**永远不判**——假绿，而且是"规格 §1 的判据"上的假绿，代价最高。故给它补一条子集核对。
- **`columns` / `values` 两张表要动**（同上，原计划的"不动"清单里列了它）：新增 `集数` 一列。两张表在 `:615-620` 与 `:624-635`，**必须同批改**——`:638` 是 `zip(values, columns, strict=True)`，长度不一致会当场抛 `ValueError`，这是本文件里少数几个"改错就响"的地方，别指望它静默。

**2.8 新增 `集数` 列、`SINGLE_EPISODE_MODES` 与跨集断言（C12/C13）**

门禁今天**没有任何一条断言能区分"跨集"与"单集"**：它量时长/响度/真峰/冻结/planner/插桩覆盖，全部与集数无关。不加这一条，《完成判据》里"覆盖规格 §1"就是一句自我声明——而这一句正是业主拒绝签字的那次收窄能悄悄活下来的原因。

1. 模块级常量，插在 `EXPECT_PLANNER` 那张表之后（实测 `:96` 之后）：

```python
# 跨集豁免（P-2a《修订记录》C13）：ultra_short_hook 的三个段全压在同一个场景上
# （modes_w5.build_ultra_short 的 best），是 10-20s 的单镜头悬念版，取材集恒为 1。
# 规格 §1 要的是一条方案**可以**跨集取画面，不是每条方案**必须** ≥2 集；
# 为跨集而把 15 秒的悬念版拆成两集，会毁掉这个模式全部的卖点。
# 活库实测：单集 ep1 planned 14.77s、跨集一手 planned 14.40s、集数恒为 1、段数恒为 3。
# **这份清单是手抄的，故 _mode_table_drift 里有它的子集核对**——写错一个名字，
# 那个模式的跨集断言就永远不判（假绿），而这正是本文件既有纪律要防的事。
SINGLE_EPISODE_MODES = frozenset({"ultra_short_hook"})
```

2. `_mode_table_drift()`（实测 `:322-347`）在 `return problems` 之前插入：

```python
    # 豁免清单只要求是子集（它天生比 SUPPORTED_MODES 小），故不能进上面那个双向对账循环：
    # 那里对"缺"与"多"一视同仁，而这里"缺"是正常的。要防的只有"多"——一个不在生产清单里
    # 的名字，意味着某个模式的跨集断言被一条永真的豁免吃掉了。
    unknown = SINGLE_EPISODE_MODES - authoritative
    if unknown:
        problems.append(
            f"SINGLE_EPISODE_MODES 里有不在 SUPPORTED_MODES 中的名字：{sorted(unknown)}"
            "（豁免清单写错会让 --require-cross-episode 对某个模式永远不判）"
        )
```

3. `columns`（实测 `:615-620`）在 `("段", 4, ">")` 之后插入一格；`values`（实测 `:624-635`）在 `f"{r.get('segments', 0)}"` 之后插入一格。**两边都改，`zip(..., strict=True)` 会替你数**：

```python
        ("段", 4, ">"), ("集数", 5, ">"), ("插桩", 5, ">"), ("TTS", 5, ">"), ("带旁白", 7, ">"),
```

```python
            f"{r.get('segments', 0)}", f"{r.get('episodes', 0)}",
            f"{r.get('segments_captured', 0)}",
```

4. 渲染路径的 `rec.update({...})`（实测 `:512-533`）里加一行（`timeline` 这个局部在 `:501` 已经有了，不要另查一次库）：

```python
            "episodes": len({str(seg.get("episode_id")) for seg in timeline}),
```

（**口径**：这一列是"本行量到的那条方案的取材集数"。渲染路径上就是被渲出来的那一条；`--plan-only` 路径上没有"被渲出来的那一条"，取本 batch 的 max，并把逐条的数打在 2.6 的附注行里，于是两种路径都不会把一个数藏起来。`plan-only` 的 `rec` 里那两键由 2.2 的替换块给出。）

**豁免这条分支的覆盖边界，如实写下来**：Task 11 **不跑** `--modes ultra_short_hook --require-cross-episode`，所以"豁免生效"在真机上没有被走过一次。别为此加一跑——它会带来一个**合法但看着像失败**的读数：`build_ultra_short` 只取"点名集里全剧最高分的那一个场景"，两条角度只要都点到那个场景所在的集，两条方案的时间轴就**逐字节相同** ⇒ Jaccard = 1.0 ⇒ 第二条被成稿后的重叠闸门拦下 ⇒ `plans < K`。那是闸门在正确工作（两部一样的 15 秒悬念版不该都出），不是缺陷，但门禁表格上会显示成"少出了方案"。豁免的**效果**由 Task 3c 的 `test_ultra_short_is_a_single_scene_film_and_says_which_episode`（集数恒为 1、且那一集是全剧最高分那集）与 `test_cross_episode_arrangement.py` 的 `continue` 分支守着；豁免**清单写错名字**由上面第 2 点的 `_mode_table_drift` 子集核对守着，它在开跑之前就红、连临时目录都不建。**唯一没被守的是"豁免条件被写反"**（`not in` 写成 `in`），那种情况只在真跑 `ultra_short_hook` 时可见——如果哪天有人跑了并看到 `REAL_EXIT=1` 且失败串是"每条方案都只取一集"，先查这一行，别去改编排器。

**门禁阈值逐条重新推导（C6 与《定案二》第 ③ 行都把数字指到了这里）。结论：一个字都不改；下面是"为什么不用改"的逐条依据，以及一条**必须改代码而不是改阈值**的实测发现。**

| 断言（`verify_modes.py` 实测行号） | 跨集之后 | 依据 |
|---|---|---|
| `EXPECT_PLANNER`（`:544-547`） | **不用改** | 它量的是"文案谁写的"，与集数无关。九个模式的取值由**模式族**决定：规则类两模式走 `_rule_variants`（零 LLM，`PlanData.planner` 停在默认 `"rule"`），`dialogue_narration` 由 `build_from_script_episodes` 直接写 `planner="llm_script"`（`pipeline.py:173`），其余五个由 `copywriter.write_plan_copy` 置 `llm_script`（`copywriter.py:147`）。三处都不读集数 |
| `EXPECT_NARRATION`（`:587-606`） | **不用改** | 它数的是**角色为 narration/ducked 的段数下限**（`one`→1、`many`→2）。跨集只增加段数、不减少：六个编排器都是逐场景产段（`build_full` 一场景一槽、`build_cross` 场景与旁白交替），段数随取材集增加而增加。下限断言在段数变多时只会更容易过 |
| 时长 `duration_s > strategy.max_duration_s`（`:579-582`） | **阈值不改，但代码要改一处**（见下） | 阈值读设置（活库实测 `strategy.max_duration_s` = **300**，与 `infra/config.py` 的 DEFAULTS 同值），`_fit_duration` 也按同一个键截断，两侧同源。C6 已经处理了两种顶穿：末场景预算豁免（活库最长单场景 **7.94s**，跨集两集 405.8 场景秒时豁免会把成片推到 **307.9s**）与引子槽位余量（预留 `_INTRO_MAX_S`=30 之后，四集一手 planned **269.06s** → 成片 ≈ **286.4s**）。**剩下第三种，C6 没算到**，见下面那段 |
| 响度窗口 `abs(integrated − target) > 2.5 LU`（`:551-559`） | **不用改** | Phase C 归一的是**整片**（`loudness.normalize_in_place`，两遍 `loudnorm`），它不知道也不关心片段来自几集；输入变长只改变测量样本量，不改变目标。实测余量极大：P-1.5 九部真成片全部落在 −14.0/−14.1 LUFS，**最大偏差 0.1 LU** 对容差 2.5 LU。且 `dialogue_narration` 早就出多集成片并过门（56.10s / −14.1 LUFS） |
| 真峰门限 `true_peak > target + margin`（`:565-574`） | **不用改** | 两级都是**逐段**作用：段级天花板 `_peak_ceiling_filter()` 挂在每段的 `atempo` 之后（`encoder.py:263`），混音限幅器挂在 `amix` 之后；Phase C 的真峰有界重试量的也是最终成片。段来自哪一集不进这条链。实测余量：九部真成片 −2.20…−5.20 dBTP 对门限 −1.00，**最小余量 1.20 dB** |
| 冻结帧 `max_freeze_s >= 2.0`（`:585-586`） | **不用改** | 冻结是**成片上相邻帧相同**，跨集拼接只增加硬切点（两集之间必然不相似），不会制造静止画面。实测九部全 **0.0s** 对门限 2.0s |
| 插桩覆盖 `segments_captured != segments`（`:537-539`） | **不用改，但它是本轮最重要的一条** | 它逐段核对"每段都真的走了 `cut_segment_args`"，而 `cut_segment_args` 正是按 `segment.episode_id` 取源的那一层。**跨集之后它是"段号与集号对得上"的唯一机器证据**：若某个编排器盖错了集号（Task 3c Step 9 #14 那条最贵的变异），段数仍然对得上、这条断言不红——所以它**不是**跨集正确性的守卫，只是"本行实测可信"的守卫。跨集正确性由 2.8 的 `集数` 列 + `--require-cross-episode` + Task 3c 的十条用例负责，别把这条当成前者 |

⚠️ **必须改代码（不是改阈值）的第三种顶穿：`raw_clip` 在 `--variants 1` 下会吃满预算，成片越过 300s。** 这是本轮审计**新查出**的，C6 只算了末场景豁免与引子余量两种：

- **机制**：`deal_windows(windows, hands=1)` 把**全部**集发进同一手（`min(1, len(windows))` = 1 手，逐窗 `dealt[rank % 1]`），于是 `--variants 1`（门禁的默认口径、也是 Task 11 Step 3b 的口径）下 `raw_clip` 的取材集是**全剧**。`build_raw_clip` 的候选是"分数 ≥ `RAW_CLIP_MIN_SCORE`=70 且时长 3-25s"的全部场景，再由 `_fit_duration` 按 300s 预算截断。
- **活库实测（只读 `data/data.db`，用真编排器的选取规则重算，不渲染）**：十集共 **333** 个场景，其中 **59** 个合格、合计 **346.5** 场景秒 > 300 的预算 ⇒ `_fit_duration` **吃满**，planned **296.21s / 51 段 / 覆盖 9 集**（ep10 一帧都拿不到）。对照：同一套算法在四集一手 `[2,5,6,9]` 上给出 **117.89s / 21 段**、在 ep1 单集上给出 **15.13s / 3 段**——与 Task 3c Step 8 那张实测表**逐位对上**，故这套重算是可信的。
- **成片会超**：`raw_clip` 没有旁白槽位，成片长度 = planned × 编码漂移。P-1.5 的实测比值是 **15.48 / 15.13 = 1.0231**（`subtitle_flow` 同类无旁白，比值 **32.43 / 30.57 = 1.0609**）。⇒ 296.21 × 1.0231 ≈ **303.0s** > 300 ⇒ `:581` 的时长断言**红**，`REAL_EXIT=1`。按更保守的 1.0609 算是 **314.3s**。
- **单集时代不可能发生**：ep1 单集的合格场景只有 15.1s（3 段），离 300 的预算差 20 倍。**这是跨集裁决直接产生的新失败形态**，而它同时也是一条**产品**缺陷：用户设的 `strategy.max_duration_s` 没生效（规格 §9.5「参数未生效」那一类），不只是门禁红。
- **修法在 `_fit_duration`（Task 3c），不在门禁**：C6 已经定了"阈值一个字都不改"，而阈值确实不该改——它量的是用户的设置。要给预算留一档**编码漂移余量**（与它已经给引子槽位预留 `_INTRO_MAX_S` 同一个手法），余量由上面两个实测比值定（≥6.1%，即 300s 的预算收到 ≤282s）。**这一档常数取多少是设计决定，本审计不替业主拍**：已记进《开放问题》#5，并把 Task 11 Step 3b 的 `raw_clip` 那一跑改成不撞这条的口径（`--variants 3`，一手四集 → planned 117.89s → 成片 ≈120.6s），同时保留一条**只算不渲**的测量步骤把 296.21 这个数交给业主。

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe -c "import ast,pathlib; ast.parse(pathlib.Path('scripts/verify_modes.py').read_text(encoding='utf-8')); print('ast OK')"`

Expected: `ast OK`。（`scripts/` 不在 `service/` 的 ruff/mypy 覆盖范围内，所以**没有自动门禁会拦语法错**——这一条 `ast.parse` 是本步骤唯一的机器校验，别跳过。）

- [ ] **Step 3: 迁 `protocol/schemas/jobs.json` 的 job 类型词表**

`JobInfo.properties.type.description` 改为：

```json
          "description": "prescreen|analysis|semantic|narration|export|model_download"
```

（去掉 `produce`：那个 job 类型随 `narration.produce` 一起消失，`plan_variants` 复用既有的 `narration` 类型。补上 `semantic`：`api/analysis.py:223` 一直在写它，词表却从没登记——这是本批次顺手修掉的既有文档缺陷。）

- [ ] **Step 4: 迁前端唯一的生产调用点**

**4.1 `desktop/src/services/client.ts` 的 `narrationApi`（B12：按锚点定位，不按行号）**

从 `export const narrationApi = {` 那一行起，到它自己的 `} as const;` 那一行止，整块替换。**上一块是 `listWorks` 函数（实测 `:105-108`，它的收尾 `}` 在 `:108`），下一块是 `exportApi`（实测 `:127` 起，已在 Task 8 Step 6 改过）**。原计划写的范围是 `:108-125`——**`:108` 是 `listWorks` 的右花括号，不是 `narrationApi` 的第一行**（那是 `:110`），照那个范围逐字替换会吃掉一个 `}`，文件当场语法错。整块实测是 `:110-125`：

```ts
export const narrationApi = {
  /** 阶段③：为选中模式各产出 K 条卖点互异的方案，只规划不渲染。 */
  planVariants: (
    projectId: string,
    modes: NarrationMode[],
    k?: number,
    excludePlanIds?: string[],
  ): Promise<PlanVariantsResult> =>
    rpc<PlanVariantsResult>('narration.plan_variants', {
      project_id: projectId,
      modes,
      ...(k === undefined ? {} : { k }),
      ...(excludePlanIds === undefined ? {} : { exclude_plan_ids: excludePlanIds }),
    }),
  listStyles: (): Promise<StyleInfo[]> => rpc<StyleInfo[]>('narration.list_styles', {}),
  listPlans: (projectId: string, batchId?: string): Promise<NarrationPlan[]> =>
    rpc<NarrationPlan[]>('narration.list_plans', {
      project_id: projectId,
      ...(batchId === undefined ? {} : { batch_id: batchId }),
    }),
  getPlan: (planId: string): Promise<PlanDetail> =>
    rpc<PlanDetail>('narration.get_plan', { plan_id: planId }),
} as const;
```

文件顶部那段 `import type { … } from '@dramaclip/protocol';`（实测 `:2-20`）按字母序插入 `PlanDetail` 与 `PlanVariantsResult`（落在 `PingResult` 与 `Project` 之间）。**`NarrationMode` 保留**——`planVariants` 的第二个形参仍在用它（原计划写"去掉不再使用的 `NarrationMode`"，那是错的：被删的 `generatePlans` 确实用过它，但新加的 `planVariants` 也用）。

**4.2 `desktop/src/features/narration/useProduceJob.ts` 整文件替换**

下面这份是**在 `D:/tmp` 的 scratch 工程里用本仓 `node_modules/typescript` 与 `desktop/tsconfig.app.json` 的全部编译选项逐字跑过 `tsc --noEmit` 的**（退出码 0），并按 `desktop/eslint.config.mjs` 的 `max-lines-per-function`（60，`skipBlankLines`/`skipComments`）实测过每个函数的行数：`useProduceJob` **46**、`produceAll` **42**、`deps` 的 `useMemo` **16**、`submitAndWait` **15**、`start` 回调 **10**、`waitJob` **6**；全文件 **173** 行（`max-lines` 上限 300）；无一行超 100 字符。

```ts
/** 出片任务：规划 K 条方案 → 提交渲染 → 轮询全部导出作业（页面离开不影响后端执行）。
 *
 * P-2a 把后端的 narration.produce 拆成了 plan_variants + export.submit，本 hook 因此
 * 从"轮询一个作业"变成"轮询一串作业"。**这不是新 UI**：进度条、文案、成功/失败提示
 * 的观感沿用原样，变的只有数据源与进度的分段口径（规划 0-30%、渲染 30-100%）。
 * 剧空间④ 与队列页的正式改写在 P-3 / P-2.5。
 *
 * 进度**必须**在规划段也动：原实现每 1.5 s 读一次 status.progress，而三模式 × K=3 的
 * 规划期是数分钟量级，冻在 0 的进度条正是规格 §3.3 要消灭的那类静默。
 *
 * 流程本体抽成模块级 `produceAll`（不是风格偏好）：desktop/eslint.config.mjs 的
 * `max-lines-per-function` 上限是 60 行且**嵌套箭头函数计入外层**，把流程留在 hook 里
 * 外层实测 66 行、当场红。拆出来之后外层 26 行、`produceAll` 37 行。
 */
import { App as AntdApp } from 'antd';
import { useCallback, useMemo, useState } from 'react';
import type {
  AnalysisJobStatus,
  ExportRejection,
  NarrationMode,
} from '@dramaclip/protocol';
import { analysisApi, exportApi, narrationApi } from '../../services/client';

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

const POLL_MS = 1500;
const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
/** 规划段占总进度的前三成：渲染才是耗时大头，但规划期进度条不许冻在 0。 */
const PLAN_SHARE = 30;

type Report = (percent: number, stageText: string) => void;
type Tick = (status: AnalysisJobStatus) => void;

interface Deps {
  readonly warn: (text: string) => void;
  readonly error: (text: string) => void;
  readonly success: (text: string) => void;
  readonly report: Report;
}

interface SubmitOutcome {
  readonly statuses: readonly AnalysisJobStatus[];
  readonly rejected: readonly ExportRejection[];
}

async function waitJob(jobId: string, onTick?: Tick): Promise<AnalysisJobStatus> {
  for (;;) {
    const status: AnalysisJobStatus = await analysisApi.status(jobId);
    onTick?.(status);
    if (TERMINAL.has(status.status)) return status;
    await sleep(POLL_MS);
  }
}

/** 提交渲染并逐条等到终态；进度按条数均分到 PLAN_SHARE..100 这一段。 */
async function submitAndWait(planIds: string[], report: Report): Promise<SubmitOutcome> {
  const submitted = await exportApi.submit(planIds);
  const total = submitted.exports.length;
  if (total === 0) return { statuses: [], rejected: submitted.rejected };
  const slice = (100 - PLAN_SHARE) / total;
  const statuses: AnalysisJobStatus[] = [];
  for (const [index, entry] of submitted.exports.entries()) {
    const status = await waitJob(entry.job_id, (tick) => {
      report(
        Math.round(PLAN_SHARE + slice * index + (tick.progress / 100) * slice),
        `渲染中 ${index + 1}/${total}：${tick.message ?? ''}`,
      );
    });
    statuses.push(status);
  }
  return { statuses, rejected: submitted.rejected };
}

/** 规划 → 取本 batch 的方案 → 提交渲染 → 逐条等完；每一处不出片都当场说清楚为什么。 */
async function produceAll(
  projectId: string,
  modes: NarrationMode[],
  deps: Deps,
  onFinished: () => Promise<void>,
): Promise<void> {
  const { report } = deps;
  report(0, '规划取材角度');
  const planned = await narrationApi.planVariants(projectId, modes);
  const planJob = await waitJob(planned.job_id, (status) => {
    report(
      Math.round((status.progress / 100) * PLAN_SHARE),
      status.message ?? '规划取材角度',
    );
  });
  if (planJob.status !== 'completed') {
    // 规划作业 failed 时 error 里已逐条点名到「模式·角度」，原样给出即可
    deps.error(planJob.error ?? '规划失败');
    return;
  }
  const plans = await narrationApi.listPlans(projectId, planned.batch_id);
  if (plans.length === 0) {
    deps.error(`规划没有产出任何方案（batch ${planned.batch_id.slice(0, 8)}）`);
    return;
  }
  const outcome = await submitAndWait(
    plans.map((plan) => plan.id),
    report,
  );
  for (const item of outcome.rejected) {
    deps.warn(`方案 ${item.plan_id.slice(0, 8)} 未提交：${item.reason}`);
  }
  if (outcome.statuses.length === 0) {
    deps.error('没有方案可渲染');
    return;
  }
  const failed = outcome.statuses.filter((status) => status.status === 'failed');
  // tsconfig.app.json 开了 noUncheckedIndexedAccess：failed[0] 的类型是
  // AnalysisJobStatus | undefined，直接写 failed[0].error 会 TS2532。
  const firstFailure = failed[0];
  if (firstFailure !== undefined) {
    deps.error(`${failed.length} 条出片失败：${firstFailure.error ?? ''}`);
  } else {
    deps.success('出片完成，成品已入作品库');
  }
  await onFinished();
}

export function useProduceJob(
  projectId: string,
  onFinished: () => Promise<void>,
): {
  producing: boolean;
  percent: number;
  stageText: string;
  start: (modes: NarrationMode[]) => Promise<void>;
} {
  const { message } = AntdApp.useApp();
  const [producing, setProducing] = useState(false);
  const [percent, setPercent] = useState(0);
  const [stageText, setStageText] = useState('');
  const deps = useMemo<Deps>(() => {
    const report: Report = (next, text) => {
      setPercent(next);
      setStageText(text);
    };
    return {
      warn: (text) => {
        message.warning(text);
      },
      error: (text) => {
        message.error(text);
      },
      success: (text) => {
        message.success(text);
      },
      report,
    };
  }, [message]);

  const start = useCallback(
    async (modes: NarrationMode[]): Promise<void> => {
      if (modes.length === 0 || producing) return;
      setProducing(true);
      try {
        await produceAll(projectId, modes, deps, onFinished);
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      } finally {
        setProducing(false);
        setStageText('');
      }
    },
    [deps, message, onFinished, producing, projectId],
  );

  return { producing, percent, stageText, start };
}
```

**三处不是风格偏好、而是门禁逼出来的形状**（原计划的草稿三条都撞了）：

1. **流程本体抽成模块级 `produceAll`**：`max-lines-per-function` 把**嵌套箭头函数计入外层**。把规划+提交+等待都写在 `start` 回调里时，外层 `useProduceJob` 实测 **66 行 > 60**，`npm run lint` 当场红。拆出 `produceAll` 之后外层 46 行。**不要用 `eslint-disable` 绕过**（docs/04 §1），也**不要靠删注释凑行数**（`skipComments: true` 意味着注释本来就不计数）。
2. **`failed[0]` 不能直接点属性**：`desktop/tsconfig.app.json` 开了 `noUncheckedIndexedAccess: true`，`failed[0]` 的类型是 `AnalysisJobStatus | undefined`，写 `failed[0].error` 会报 **TS2532**（scratch 里实测到了这一条，改法就是先绑局部再判 `!== undefined`）。原计划的草稿正是这么写的。
3. **进度必须在规划段也动**：原实现每 1.5 s 读一次 `status.progress` 并 `setPercent`；改写后若只在渲染段更新，三模式 × K=3 的规划期（数分钟量级）进度条会**冻在 0**，而那正是规格 §3.3 要消灭的静默。故 `waitJob` 带一个 `onTick`，两阶段都驱动 percent/stageText，分段口径是规划 0-30%、渲染 30-100%（按条数均分）。

`ExportRejection` 由 Task 8 Step 5 加进 `protocol/ts/index.ts`；若那一步漏了，这里会报"找不到名称"——回去补，**不要就地改成 `any`**（`@typescript-eslint/no-explicit-any` 是 error）。

- [ ] **Step 4b: 跑前端门禁**

Run: `cd /d/PersonProjects/DramaClip && npm run typecheck && npm run lint`

Expected: `tsc --noEmit` 两个 project 都无错；`eslint src main` 无错。这两条现在能过是因为上面那份代码是实测过的；若仍红，先看是不是 `protocol/ts/index.ts` 少了 Task 6/8 该加的类型。

- [ ] **Step 5: 迁 `tests/api/test_data_paths.py`**

`:18-23` 的三步替换为四步（该文件 `:8` 的 import 已在 Task 6 改过）：

```python
    planned = harness.rpc(
        "narration.plan_variants", {"project_id": project_id, "modes": ["raw_clip"], "k": 1}
    )
    status = harness.wait_job(str(planned["job_id"]))
    assert status["status"] == "completed", status.get("error")
    plans = harness.rpc(
        "narration.list_plans", {"project_id": project_id, "batch_id": planned["batch_id"]}
    )
    submitted = harness.rpc("export.submit", {"plan_ids": [str(plans[0]["id"])]})
    assert submitted["rejected"] == [], submitted
    status = harness.wait_job(str(submitted["exports"][0]["job_id"]))
    assert status["status"] == "completed", status.get("error")

    exported = harness.rpc("export.list", {"project_id": project_id})
    out = Path(str(exported[0]["output_path"]))
```

（该用例的后续断言——成品落在 `data_dir/outputs/<project>/` 下——一字不动，它验的正是"渲染侧没被拆分改动"。）

**这条用例能过，靠的是《定案四》的模式族分流（B2 附带项之一）**：它走 `modes: ["raw_clip"]`，而 `Harness` 的 settings 只有 `{"asr.language": "zh"}`（`tests/api/test_produce.py:40`），**没有任何 `llm.*` 键**。若 `_run_plan_variants` 对每个模式都调 `angles.select_angles`，这里会抛 `LlmUnavailable`、作业 failed，`assert status["status"] == "completed"` 当场红。所以迁移完这条用例若红在"completed"上，先回去查 Task 6 Step 7 第 11 点的分流有没有做，**不要给这个文件加 LLM 设置**——那会把一个真实的回归盖掉，而且这个用例的整个意义就是"数据根目录锚点在纯剪辑路径上成立"。

- [ ] **Step 6: 迁 `tests/api/test_plan_variants.py` 里的原 produce 用例**

原 `test_produce.py` 里那些打 `narration.produce` / `narration.generate_plans` 的用例，按下面对照表逐条处置。**不许整块删除**：它们各自钉着一条真实不变量，只是入口换了。

**两个贯穿全表的机械变化**，先记住再看表：

- `_generate_one(context, mode, episodes, episode_inputs, settings)` → `_plan_one(context, mode, episodes, episode_inputs, settings, variant)`，**返回二元组** `(PlanData, list[str])` 而不是 `None`，且第六个实参是 `narration_api._Variant`（**不是** `angles.AngleBrief`——见 Task 6 Step 7 第 10 点：两族在 `_Variant` 上会合）。
- `_plan_one` **不落库**（`plans_repo.create` 只在 `_run_plan_variants` 里），且**不配音**（配音在 `_voice`）。凡是原来断言"库里那一行"或依赖 TTS 打桩的，都要按这两条改。

| 原用例 | 处置 |
|---|---|
| `test_produce_renders_work_end_to_end` | 改成两步（`plan_variants` → `list_plans(batch_id)` → `export.submit` → 等 export job），断言原样保留（`export.list` 有 completed 行、`output_path` 是文件、`list_works` 含该项目）。重命名为 `test_plan_then_submit_renders_work_end_to_end`。**它打 `modes:["raw_clip"]` 且 `Harness` 无 `llm.*` 设置，故只有《定案四》的分流落地后才会绿**（B2 附带项）；若红在"completed"上，去查 Task 6 Step 7 第 11 点，不要给这个文件加 LLM 设置 |
| `test_produce_invalid_mode` | 方法名换成 `narration.plan_variants`，错误码仍是 `-32302`。重命名为 `test_plan_variants_invalid_mode` |
| `test_style_selection_runs_once_per_job` | 方法名换成 `narration.plan_variants`。`monkeypatch.setattr(narration_api, "_generate_one", …)` 这一行**整行删掉**，不要换成 `_plan_one` 的桩：本用例的 settings 只有 `narration.style_id="auto"`、**没有 `llm.*`**，所以 `_angle_variants` 会在 `select_angles` 的未配置守卫上抛 `LlmUnavailable`（**在构造客户端之前**，不会发网络请求），三个模式全进 except 分支、`_plan_one` 一次都不会被调到——桩是死的。断言 `len(calls) == 1` 不变：`resolve_run_style` 发生在 `_inject_run_settings` 里，**排在模式循环之前**，与作业最终成败无关。作业终态是 `failed`，而 `harness.wait_job` 对 failed 也返回（它只在超时时抛），故不必改断言 |
| `test_style_selection_only_paid_for_modes_that_narrate` | 方法名换成 `narration.plan_variants`。**必须同时打桩 `angles.LlmClient`**：本用例的 settings **设了** `llm.base_url`（`:211-218`），而它原先只桩了 `script_driver.LlmClient`（`:219`）。不补这一桩，`full_narration` 那一臂会走真 `LlmClient` 朝 `http://llm.test/v1` 发**真出站请求**，`ANGLE_LLM_TIMEOUT_S = 240.0` × `_ATTEMPTS = 2` ≈ **8 分钟挂死**——在单元测试里。具体四步：① 加 `monkeypatch.setattr(angles, "LlmClient", _FakeLlm)`；② 给 `_FakeLlm.chat_json` 加一个角度分支（放在 `"风格库"` 判断之前）：`if "选题操盘手" in system: return {"angles": [{"name": f"角度{i}", "reason": f"理由{i}", "hook": f"钩子{i}", "episode_numbers": [1]} for i in (1, 2, 3)]}`（本用例的种子只有一集，故一律给 `[1]`）；③ 把 `monkeypatch.setattr(narration_api, "_generate_one", lambda *_a, **_k: None)` **换成** `monkeypatch.setattr(narration_api, "_voice", lambda _ctx, plan, _settings: plan)`——**不能直接删**：`full_narration` 那一臂有了 LLM 就会真跑到配音，而本用例没桩 `pipeline.create_tts`，`settings` 里也没有 `tts.engine`，于是 `create_tts` 会用默认的 `edge` 去连真云端（第二次真出站请求）；④ 断言 `selections == expected_selections` 一字不动——它只数 `"风格库" in system` 的请求。`full_narration` 那一臂的作业终态会是 `failed`（三条角度同集，Task 6 的成稿前闸门拦掉后两条，`failures` 非空），这**正是本用例既有 docstring 写的**「终态由 `_wait_terminal` 兜住（不许卡在非终态报零次）」，不要为了让它 completed 而改种子 |
| `test_only_sound_only_modes_skip_tts_group` | **整条删除**：`_NO_TTS_MODES` 的"分组并行"用途随 `_run_generation_parallel` 一起消失。`_NO_TTS_MODES` 本身保留（`_NARRATION_MODES` 仍由它派生，而《定案四》的模式族分流正是按 `_NARRATION_MODES` 判的），另补一条钉住派生关系的用例：`assert narration_api._NARRATION_MODES == frozenset(narration_api.SUPPORTED_MODES) - narration_api._NO_TTS_MODES`，并加一句 `assert narration_api._NARRATION_MODES == frozenset({"intro_narration", "cross_narration", "ultra_short_hook", "dialogue_narration", "full_narration", "dual_host_chat", "inner_monologue"})`——**这七个名字就是规格 §4.2 那句"七个解说模式"的机器可核对形态** |
| `test_every_supported_mode_has_a_chinese_label` | 原样保留（两面镜子都还在） |
| `test_style_directives_reach_the_copy_prompt` | 入口从 `_inject_run_settings` + `_generate_one` 换成 `_inject_run_settings` + `_plan_one`，多传一个 `variant`：`narration_api._Variant(name="复仇线", reason="第 1 集最狠", episode_numbers=[1], angle_block=angles.prompt_block(angles.AngleBrief(name="复仇线", reason="第 1 集最狠", hook="他跪着进了门", episode_numbers=[1])))`；调用改成 `plan, _used_ids = narration_api._plan_one(context, mode, episodes, episode_inputs, settings, variant)`。prompt 侧断言全部保留，并**新增一条** `assert "复仇线" in prompt`（角度与风格是两个独立注入，各钉一条）。**落库断言整段删掉（B3）**：原计划说换成 `plans_repo.list_by_project(...)[0]`，但 `_plan_one` 不落库、列表是空的，那样写会 `IndexError`。改为直接断言返回的 `plan`：`assert plan.planner == "llm_script"`、`slot_ids = [t.id for t in plan.narration_texts]`、`assert slot_ids`、`assert [t.text for t in plan.narration_texts] == [f"{s} 的解说" for s in slot_ids]`。原先钉「落库文案与槽位 id 对应」的那条不变量改由 Task 6 的 `test_plan_variants_writes_k_plans_without_rendering` 承担（它读的是 `list_by_batch` 的真行）。`pipeline.create_tts` / `audio_duration_s` 两处打桩**删掉**：`_plan_one` 不配音，留着会让下一个读者以为它配 |
| `test_dialogue_without_transcript_fails_loudly` | `_generate_one` → `_plan_one`，`episode_inputs` 传 `[]`，第六个实参传 `narration_api._Variant(name="复仇线", reason="第 1 集最狠", episode_numbers=[1], angle_block="")`。断言 `pytest.raises(ValueError, match="都没有转写")`（`_plan_one` 的 dialogue 分支对空 `scoped` 抛的是「角度「复仇线」的取材集都没有转写」，与原先 `_generate_one` 的「没有带转写的已完成集」不同——**按新代码的实际文案断言，不要沿用旧串**） |
| `test_pinned_style_survives_a_project_without_transcripts` | 原样保留（它只打 `_inject_run_settings`，与拆分无关） |
| `test_dialogue_unconfigured_llm_fails_the_plan` | `_generate_one` → `_plan_one`，多传 `variant`（同上，`episode_numbers=[1]`）。`pytest.raises(LlmUnavailable, match="引擎")` 保留——这条守的是 `script_driver.script_dialogue_plan` 的未配置守卫，与选题层无关 |
| `test_assembly_failure_lands_in_jobs_table` | `@pytest.mark.parametrize("method", [...])` 的两个方法名换成 `["narration.plan_variants"]`（`generate_plans` 已不存在，参数化只剩一项——**保留 parametrize 结构**，P-2b/P-3 若再加规划入口可直接扩列表） |
| `test_produce_runner_raise_still_settles_the_job` | 方法名换 `narration.plan_variants`；注入点仍是 `harness.context.notifier.progress`——但 `_run_plan_variants` 不调 `notifier.progress`（它只调 `job_store.set_progress`），故改注入 `harness.context.job_store.set_progress` 抛 `RuntimeError("进度写不进去")`，断言 error 含该串、作业 failed、`cancel_events` 已释放。重命名为 `test_plan_variants_runner_raise_still_settles_the_job`。**注意 `set_progress` 在成功路径上也被调**（每条变体一次、以及 `mark_completed` 之前的 `set_progress(job_id, 100.0)`），所以注入之后第一个模式的第一条变体就会炸，被外层兜底 handler 接住——这正是本用例要验的形状 |
| `test_generation_runner_raise_still_releases_cancel_event` | 方法名换 `narration.plan_variants`，注入点换 `job_store.mark_completed`（原样）。**`_generate_one` 的桩整行删掉**：本用例打 `modes:["raw_clip"]`，走的是规则路径、根本不经过 `_plan_one`，桩是死的（B2 附带项）。删掉之后作业走真的 `_rule_variants` → 单集种子出 1 条方案 → 无失败 → `mark_completed` 被调 → 注入的 `boom` 触发，断言全部照旧成立。重命名为 `test_plan_variants_bookkeeping_raise_releases_cancel_event` |
| `test_bookkeeping_error_never_replaces_the_original` | 方法名换 `narration.plan_variants`。**`monkeypatch.setattr(narration_api, "_generate_one", ...)` 那一行整行删掉**，理由同上（`raw_clip` 走规则路径，`_plan_one` 不会被调到；换成 `_plan_one` 的桩是死的，B2 附带项）。`mark_completed` 的注入原样保留，`status["status"] == "completed"` 与"原始原因留痕"两条断言原样保留 |
| `test_tts_failure_fails_one_mode_not_the_batch` | **由 Task 6 的 `test_one_variant_failure_does_not_kill_its_siblings` 与 `test_one_mode_failure_does_not_kill_other_modes` 两条取代，整条删除**。它验的"失败粒度=单条方案"在变体级比在模式级更细，旧断言（`rendered == ["intro_narration"]`）依赖已删除的渲染耦合（`narration_api.render_export` 那个 monkeypatch 目标随 Task 6 Step 7 第 12 点的 import 一起消失） |

**改完跑一遍文件级全量**，确认没有漏网的旧入口：

Run: `cd service && grep -n "narration.produce\|generate_plans\|_generate_one\|_newest_ready_plan\|render_export" tests/api/test_plan_variants.py tests/api/test_data_paths.py`

Expected: 无输出。

- [ ] **Step 7: 跑测试**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest -q`

Expected: PASS（`tests/api/test_analysis.py` 的既有隔离 flake 除外）。

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/transport/test_contract_sync.py -q`

Expected: PASS —— 契约两侧至此对齐（Python 少两个方法、schema 少两个方法；Python 多两个、schema 多两个）。

Run: `cd /d/PersonProjects/DramaClip && npm run typecheck && npm run test`

Expected: `tsc --noEmit` 两个 project 都无错；`vitest run` 全绿，含 `desktop/src/__tests__/contract.test.ts` 的「METHOD_NAMES 与 protocol/schemas 的 x-methods 一致」。

Run: `cd /d/PersonProjects/DramaClip && npm run lint`

Expected: 无错。`useProduceJob.ts` 的 `max-lines-per-function`（单函数 ≤ 60 行，`desktop/eslint.config.mjs`）已在 Step 4 的结构里满足并实测过（外层 46、`produceAll` 42、`submitAndWait` 15）；**若这里仍红，先数行数确认是哪个函数超了，不要靠删注释凑**（该规则 `skipComments: true`，注释本来就不计数），也**不要用 `eslint-disable` 绕过**（docs/04 §1）。

- [ ] **Step 8: 提交（Task 6 + 7 + 8 + 9 合成一个提交）**

Task 6 的 Step 10、Task 7 的 Step 4、Task 8 的 Step 9 都只暂存不提交，就是为了这里。契约同步本身在 Task 6 结束时已经两侧对齐，**真正让这个提交不能拆开的是三处调用点**（Task 6 Step 9 已列）：`desktop/src/services/client.ts` 的 `MethodName` 类型会让 `npm run typecheck` 红、`scripts/verify_modes.py` 会在运行时拿到 `-32601`、以及 `test_plan_variants.py` / `test_data_paths.py` 里尚未迁移的旧用例会让 `pytest` 红。三者都在本任务里收口，故四个任务合成一个可独立构建的提交（docs/04 §4）。

Run: `git status --short`

Expected: 暂存区含 Task 6/7/8 的全部路径，加上本任务改的 6 个文件；**不含**另一位工程师的 `scripts/verify_e2e.mjs`、`scratch/`、`tests/api/test_analysis.py`、`docs/07-*`。若含，`git restore --staged <路径>` 逐个撤出。**特别核一眼 `scripts/verify_e2e.mjs`**：它在开工前就已经是 `M`（另一位工程师的在途改动），本计划从头到尾都不该 add 它。

```bash
git add scripts/verify_modes.py desktop/src/features/narration/useProduceJob.ts desktop/src/services/client.ts protocol/schemas/jobs.json service/tests/api/test_data_paths.py service/tests/api/test_plan_variants.py
git commit -m "feat(api)!: produce 拆成 plan_variants + export.submit，规划与渲染就此分开

BREAKING CHANGE: 删除 narration.produce / narration.generate_plans / export.start，
新增 narration.plan_variants / narration.get_plan / export.submit。
调用点（scripts/verify_modes.py、desktop useProduceJob）同批迁移，不留并存灰度。

条数按模式族分别算（规格 §4.3 ④）：解说类 K 条来自 angles 选题，
规则类 raw_clip / subtitle_flow 来自全剧 top-K 冲突窗，两个纯剪辑模式仍零 LLM（§4.2）。

移交：scripts/verify_e2e.mjs:152 派发 narration.generate_plans、:168 派发 export.start，
本提交之后两处都会拿到 -32601。该文件属另一位工程师（OCR 通道），P-2a 未编辑它，
按 Task 9 Step 1b 书面移交属主。

api/narration.py 自此不再 import api/export.py 的任何东西——规划侧不碰渲染，
这是拆分干净的一条静态证据。

规格 §6 的单点解锁：阶段③ 只看方案不渲染，队列可按方案粒度取消重试。"
```

---

## Task 10: 文档收口 + 全量门禁

三份文档都写着"方法合计数"与"迁移清单"，它们由测试与人工双向对账（`docs/03` §6 明说"上面的 46 因此不是手工统计"）。数字错了不只是难看：下一个人会照着错的数字判断自己有没有漏登记。

**Files:**
- Modify: `docs/03-IPC协议规范.md`
- Modify: `docs/service/01-传输与API层设计.md`
- Modify: `docs/service/04-数据模型.md`
- Modify: `docs/service/02-引擎设计.md`（**本轮新加**：`:59` 的 `copywriter.py` 行仍写着「编排器只产出槽位（`slot` 职责 + `window` 素材区间）」，而这两个字段名在 P-1.5 的《实现定案修正》里就已经改成 `brief` / 无 `window`；Task 4 又把槽位台词改成按集取用，这一行因此同时是**过期的**与**不完整的**）
- Modify: `docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md`（**本轮新加，只改一行**：§3.3.1 降级裁决表 `:126` 的「位置」列点名 `api/narration._generate_one`，Task 6 删掉那个函数。那张表是裁决的**权威登记处**、规格 §11 要求"每次新增降级点必须在本表加一行"，留一个指向已删函数的位置列会让下一个人以为回落路径还在）

- [ ] **Step 1: 数出新的方法合计**

Run: `cd service && ../.venv/Scripts/python.exe -c "from types import SimpleNamespace; from dramaclip.api import build_router; r=build_router(SimpleNamespace(), shutdown=lambda: None); names=sorted(r.method_names); print(len(names)); import collections; print(collections.Counter(n.split('.')[0] for n in names))"`

Expected: 总数 `46`（删 `narration.generate_plans`/`narration.produce`/`export.start` 三个、加 `narration.plan_variants`/`narration.get_plan`/`export.submit` 三个，净 0），命名空间分布 `narration` 4、`export` 4 不变。**以这条命令的实际输出为准填下面两份文档，不要照抄本行的数字。**

- [ ] **Step 2: 改 `docs/03-IPC协议规范.md`**

1. §5.2 的已用错误码表，在 `-32301 / -32302 | narration | 无分析结果 / 模式不支持` 那一行之后加两行：

```markdown
| -32303 / -32304 | narration | 方案数 K 越界 / 编排方案不存在 |
| -32406 / -32407 | export | `plan_ids` 非法 / **方案不可渲染**（状态非 ready、时间轴为空、旁白段无配音音频或音频文件已丢失） |
```

2. §6「已落地全集」的 `narration.*` 与 `export.*` 两行替换为：

```markdown
- `narration.*`（4）：**plan_variants**（P-2a 新增：阶段③ 为选中模式各产出 K 条卖点互异的方案，只规划不渲染）/ **get_plan**（P-2a 新增：单条详情 + 成本账）/ list_plans（可按 batch_id 取一组）/ list_styles
- `export.*`（4）：**submit**（P-2a 新增：按 plan_ids 排队渲染，一条方案一个 export job，坏的逐条给理由）/ retry（复用原 export_id 覆盖写，仅 failed 可重试）/ list / list_works（跨项目作品库）
```

3. §6 末尾「原案里规划但从未实现的方法」那一段里，删掉 `narration.get_plan` 这一项（本批次实现它了），并把 `narration.synthesize_tts` 的说明改为：

```markdown
`narration.synthesize_tts`（配音是 `plan_variants` 的一环，不单独开方法——见 P-2a 计划《定案一》：
方案行必须在落库时就已配音，否则 `export.submit`/`export.retry` 会渲出哑片）
```

4. §6 标题行的「46 个方法 / 10 个命名空间」按 Step 1 的实测数字改写（若仍为 46 则不动，但**必须跑过 Step 1 才这么说**）。

5. **改 §5.2 已用错误码表里的 `-32401` 那一行**（实测 `docs/03-IPC协议规范.md:86`，逐字是 `| -32401 | export | 编排方案不存在 / 编排时间轴为空 |`）。Task 8 之后"编排时间轴为空"不再走 `-32401`：它由 `_assert_renderable` 判、抛 `-32407`，而 `export.submit` 把它转成 `rejected` 里的一条理由（只有 `export.retry` 会把它作为错误码抛出来）。**只加新行、不改这一行，就会留下一句描述已不存在行为的文档**——规格 §9.5 的假文案类，和第 3 点要删的那句「`narration.get_plan` 从未实现」是同一件事。替换为：

```markdown
| -32401 | export | 编排方案不存在（`export.retry`；**"编排时间轴为空"已迁至 -32407**，见下） |
```

（`-32407` 那一行已由第 1 点加上，描述里含"时间轴为空"，两处不重复：`-32401` 行只负责说明"这个概念搬走了、搬到哪"，避免有人照着旧行写客户端。）

- [ ] **Step 3: 改 `docs/service/01-传输与API层设计.md`**

1. §4 的方法清单里两行替换：

```markdown
api/narration.py    plan_variants / list_plans / get_plan / list_styles     （4）
api/export.py       submit / retry / list / list_works                      （4）
```

2. §4 的「实测合计 46 个方法」那一句与其后的命名空间分布，按 Step 1 的实测数字改写。

3. §6 的第二条已知限制整块替换（`projects.settings` 从此有消费端了）：

```markdown
- **`projects.settings` 已有第一个消费端（P-2a）**：`api/narration._effective_settings` 把项目级
  覆盖叠加到全局 `Settings` 之上，`narration.plan_variants` 经它读 `narration.variants_per_mode`
  与 `narration.style_id`。**其余覆盖键仍未接线**——字幕预设、输出四键、响度目标都还是
  `render_export` 直接读 `context.settings`，项目级覆盖写了不生效。接线归 P-3（包装区）。
  实际使用的覆盖键名已登记进 `04-数据模型` §3。
```

4. §4 的「尚无 api 文件的既定命名空间」段落不动。

- [ ] **Step 4: 改 `docs/service/04-数据模型.md`**

1. `### narration_plans —— 跨集编排方案` 的 DDL 块整块替换：

```sql
CREATE TABLE narration_plans (
  id              TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  narration_mode  TEXT NOT NULL,        -- 九种模式枚举值
  episode_ids     TEXT NOT NULL,        -- JSON: string[]
  plan_data       TEXT NOT NULL,        -- JSON: 编排方案（片段/时间轴/文案/字幕指令）
  tts_segments    TEXT,                 -- JSON: TTS 分段与音频路径（**死列**，见下）
  status          TEXT NOT NULL DEFAULT 'pending',
                  -- pending | generating | ready | failed
  created_at      INTEGER NOT NULL,
  angle           TEXT NOT NULL DEFAULT '',  -- 卖点角度名（010 迁移新增）
  angle_reason    TEXT NOT NULL DEFAULT '',  -- 模型自选这条角度的理由（010）
  variant_index   INTEGER NOT NULL DEFAULT 1,-- 1..K 的槽位号（010）
  overlap_max     REAL,                      -- 与同 batch 同模式兄弟方案的最大取材重叠；NULL=首条无兄弟（010）
  batch_id        TEXT                       -- 一次 plan_variants 调用产出全组的标识（= 该作业 job_id）（010）
);
CREATE INDEX idx_plans_batch ON narration_plans(project_id, batch_id);
```

并在该块之后加一段（**这段是本轮读代码读出来的既有缺陷，必须写下来，否则下一个人会以为 `tts_segments` 有用途**）：

```markdown
**`tts_segments` 是死列**：建表就有，`repos/plans.py` 的 `_COLUMNS` 从未收录它，
全仓无任何读写。配音分段与音频路径的实际落点是 `plan_data.narration_texts[*].audio_path`
（由 `pipeline.synthesize_narration_texts` 回填）。P-2a 未删它（`ALTER TABLE DROP COLUMN`
在旧版 SQLite 上不可用，且删列要动 001 之外的迁移语义），只在此登记为死列；
真要清掉时连 `001_init.sql` 的这段 DDL 一起改，并在此处销账。
```

2. §3 的项目级覆盖键名登记处，加两行（该节现有「届时按『项目覆盖 dict 叠加到全局 Settings 之上』实现，并在本节登记实际使用的覆盖键名」的约定，P-2a 就是那个"届时"）：

```markdown
| `narration.variants_per_mode` | 每模式方案数 K（1~8） | `api/narration.plan_variants`（P-2a 接线） |
| `narration.style_id` | 解说风格；`auto` 则任务级选题一次 | `api/narration._inject_run_settings`（P-2a 起经 `_effective_settings` 读项目覆盖） |
```

3. §4 的「已应用迁移清单」表：把标题里的「实测 8 个文件」改成实测数（Run: `ls service/dramaclip/infra/storage/migrations/*.sql | wc -l`），补上漏登记的 `009` 行与本批次的 `010` 行：

```markdown
| `009_ocr_segments.sql` | `episode_analysis.ocr_segments`（OCR 字幕通道） |
| `010_plan_angles.sql` | **`narration_plans` 角度五列** + `idx_plans_batch`（P-2a：方案行承载卖点角度、可按 batch 取组） |
```

（`009` 是另一位工程师的迁移，他只加了文件没登记表——本批次顺手补上，**不改他的迁移文件本身**。）

4. **`jobs` 表那段「type 取值以代码为准」的注记（实测 `:247-250`）整块替换**——它被本批次**同时**过期了两次：`produce` 这个 job 类型不再有人创建（`plan_variants` 复用既有的 `narration` 类型，见 Task 9 Step 3），而它末尾那句「已知偏差：`protocol/schemas/jobs.json` 的 `JobInfo.type` 描述同样漏了 `semantic`」也由 Task 9 Step 3 修掉了：

```markdown
- **type 取值以代码为准**：上表是 `job_store.create()` 实际创建过的全集。`001_init.sql` 的行内注释
  写了 `tts` 但从未有代码产出该类型，也漏了 `semantic`（`analysis.resync_semantic`）；迁移文件
  不可回改，故此处为准。**`produce` 曾是 `narration.produce` 创建的类型，P-2a 把该方法拆成
  `narration.plan_variants` + `export.submit` 之后不再有新行**（规划复用 `narration`、渲染复用
  `export`）；库里既有的 `produce` 行是历史数据，查询与界面都要容得下它，故此处保留登记。
  `protocol/schemas/jobs.json` 的 `JobInfo.type` 描述已随 P-2a 补上 `semantic`、去掉 `produce`。
```

5. **`narration_plans` 那节要写明"跨集不加列"**（《修订记录》C3）：集身份是**规划期注入**的（`casting.stamp` 把 `episode_analysis.conflict_scores` 那一行的主键盖到场景上），所以本批次的迁移**只有 `010` 的五列角度**，`episode_ids` 是既有列、`ConflictScore` 一个字段都没加。不写这一句，下一个人看到"跨集"会去找那一列在哪：

```markdown
**跨集取材不需要新列**（P-2a）：一条方案的取材集就是既有 `episode_ids`（JSON string[]）与
`plan_data.timeline[*].episode_id`，两者都由规划期从时间轴反推写入；场景的集身份来自
`episode_analysis.conflict_scores` **那一行的主键**（`engines/narration/casting.py::stamp`
在解析时盖章），故 `engines/semantic/models.py::ConflictScore` 不含集字段、也不需要迁移。
```

- [ ] **Step 4b: 改 `docs/service/02-引擎设计.md` 的 `copywriter.py` 行（本轮新增）**

`:59` 那一行逐字是：

```markdown
| `copywriter.py` | 逐槽文案编剧（P-1.5） | 编排器只产出槽位（`slot` 职责 + `window` 素材区间），一次 LLM 调用填满全部槽位置 `planner=llm_script`；漏槽/超长/空文即抛，**无模板兜底**（UI 重规划规格 §3.3.1；承接原 `hook_generator.py` 职责） |
```

替换为：

```markdown
| `copywriter.py` | 逐槽文案编剧（P-1.5；P-2a 起槽位台词按集取用） | 编排器只产出槽位（`NarrationText.brief` 是职责，**没有 `window` 字段**：槽位压在成片哪一段由它 `narration_id` 指到的那条 `TimelineSegment` 的 start/end 给出），一次 LLM 调用填满全部槽位置 `planner=llm_script`；漏槽/超长/空文即抛，**无模板兜底**（UI 重规划规格 §3.3.1；承接原 `hook_generator.py` 职责）。P-2a 之后第二参是按集分开的取材原料表（`casting.MaterialByEpisode`），`_slot_block` 按 `segment.episode_id` 取台词——跨集时间轴上集与集的集内相对秒互相覆盖，摊平一张表会把别集的对白喂给编剧 |
```

**为什么这一行必须改**：`slot` 与 `window` 两个字段名**都不存在**（P-1.5《实现定案修正》：`NarrationText` 只有 `brief`，`window` 已删）。而 pydantic **静默忽略未知 kwargs**，所以照着这行文档写 `NarrationText(slot=…, window=…)` 不会报错、只会丢数据——正是本仓付过两次账的那类"编造出来的规格"。同一张表的 `:40` 已经声明「本表为**原案模块清单**，非实现清单 …未建条目一律以现码为准」，但**已建条目写成错的字段名不在那句免责里**。

顺带核一眼：P-2a 新建的三个模块（`angles.py` / `casting.py` / `overlap.py`）**不必**逐个补进那张表——`:40` 的免责句管的正是"未建/新建条目以现码为准"，而补进去就要连带维护"原案 vs 实现"两栏的对应关系。**只有 `copywriter.py` 这种"已登记且写错了"的行必须改。**

- [ ] **Step 4c: 改规格 §3.3.1 降级裁决表的位置列（本轮新增，只改一行）**

`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md:126` 的「位置」列里 `api/narration._generate_one` 回落 `build_plan` 那一项替换为 `api/narration._plan_one`（Task 6 之后规划的唯一入口）。**裁决列（「禁止 → 抛错」）与理由列一个字不动**——本批次没有改变这条降级的裁决，只是那个函数换了名字。

Run: `cd /d/PersonProjects/DramaClip && grep -rn "_generate_one\|_run_produce\|_newest_ready_plan\|_run_generation_parallel" docs/ --include=*.md | grep -v superpowers/plans`

Expected: **无输出**。（`docs/superpowers/plans/` 下的历史记述**不改**——它们是当时的真相，本计划自己的两节《修订记录》里就大量点名这些函数；这条 grep 已用 `grep -v superpowers/plans` 把它们滤掉。实测除计划目录外全 `docs/` 只有规格 `:126` 一处命中，即本步要改的那一行。）

- [ ] **Step 5: 全量门禁**

Run: `cd service && ../.venv/Scripts/ruff.exe check .`
Expected: 无输出、退出码 0

Run: `cd service && ../.venv/Scripts/mypy.exe dramaclip`
Expected: 无输出、退出码 0

Run: `cd service && ../.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -5`
Expected: 全绿（`tests/api/test_analysis.py` 的既有隔离 flake 除外；若它红了，单独跑 `pytest tests/api/test_analysis.py -q` 判断是否与本改动相关，无关则记录后继续，**不要修它、不要给它加 sleep、不要扩大它**）

Run: `cd /d/PersonProjects/DramaClip && npm run lint && npm run typecheck && npm run test`
Expected: 三条全绿

- [ ] **Step 6: 死码对账（三条 grep，各钉一件不同的事）**

原计划这里只有两条，且都写着"Expected: 无输出"——那两条在 `9b42f24` 之后**都是假门禁**（B9），而其中一条还漏了 `.mjs`（R6）。拆成三条，各自的 Expected 如实写：

**6a 定义清零**（旧入口的函数本体一个不剩）：

Run: `cd service && grep -rnE "^def (generate_plans|produce|_run_generation_parallel|_generate_one|_newest_ready_plan)\(" dramaclip/api/narration.py`

Expected: 无输出（`grep` 退出码 1，那是"没有命中"的正常形态，不是命令失败）。

Run: `cd service && grep -rnE "^def start\(" dramaclip/api/export.py`

Expected: 无输出。

**6b 死名清零**（连注释与 docstring 里都不许再点这些名字）：

Run: `cd service && grep -rn "generate_plans\|_run_generation_parallel\|_generate_one\|_newest_ready_plan\|_run_produce" dramaclip --include=*.py`

Expected: 无输出。**这条只有在两处 docstring 都改过之后才成立**：`engines/narration/pipeline.py:236-237` 的 `_synthesize_into`（Task 5 Step 5，原文点名 `_run_generation_parallel` / `produce` / `generate_plans`）与 `api/export.py` 的 `ExportRun`/`_submit_export`（Task 8 Step 3 第 6 点，原文写着 `start/retry/produce` 三处调用点）。**若命中在散文里，去改那段文字，不要放宽这条 grep**——放宽就等于把 B9 重新装回去：一条永远红的门禁比没有门禁更坏，它教会执行者"这条不用看"。

**6c 调用点清零（含 `.mjs`，且预期恰好两条命中）**：

Run: `cd /d/PersonProjects/DramaClip && grep -rn "narration.produce\|narration\.generate_plans\|export\.start\|narrationApi\.produce\|narrationApi\.generatePlans\|exportApi\.start" service/dramaclip desktop/src protocol scripts --include=*.py --include=*.ts --include=*.tsx --include=*.json --include=*.mjs`

Expected: **恰好两条**，都在另一位工程师的文件里：

```
scripts/verify_e2e.mjs:152:  const { job_id: genJob } = await rpc('narration.generate_plans', {
scripts/verify_e2e.mjs:168:    const { job_id: exportJobId } = await rpc('export.start', { plan_id: plan.id });
```

这两条**P-2a 不修**（《开工前置》的提交纪律、《文件结构》的"不动"清单都点着这个文件），已由 **Task 9 Step 1b** 书面移交属主、并写进 Task 9 Step 8 的提交信息。除这两条外必须无输出——`service/dramaclip`、`desktop/src`、`protocol` 三处任何一条命中都是本批次没做完。**`--include=*.mjs` 是本轮补上的（R6）**：原计划的两条 grep 都没有它，于是那句「逐条对账，一条都不许漏」正好漏掉了唯一一个 `.mjs` 调用方，`verify_e2e.mjs` 会在合入当天开始返回 `-32601`。

Run: `cd service && grep -rn "降级\|兜底\|回退" dramaclip/engines/narration/angles.py dramaclip/engines/narration/overlap.py`

Expected: 无输出——**本批次新增的两个模块里不许出现任何降级语义**。规格 §3.3.1 的禁止级已经全是抛错，选题与度量两层不得重新引入模板或规则兜底。（`pipeline.top_conflict_windows` 不在这条 grep 里：它落在 `pipeline.py`，那个文件另有合法的"允许级降级"记述；它的无语义降级由 Task 3b 的用例与《定案四》第 5 点 `planner == "rule"` 共同守着。）

- [ ] **Step 7: 提交**

```bash
git add docs/03-IPC协议规范.md docs/service/01-传输与API层设计.md docs/service/02-引擎设计.md docs/service/04-数据模型.md docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md docs/superpowers/plans/2026-09-12-p2-plan-render-split.md
git commit -m "docs: 方法清单/错误码/迁移登记随 produce 拆分收口，并清掉三处过期字段与函数名

- docs/03：错误码表补 -32303/-32304/-32406/-32407，-32401 那行不再覆盖「时间轴为空」
- docs/service/01：方法清单与合计数按 build_router 实测重写，projects.settings 已有消费端
- docs/service/04：narration_plans 五列 + 010 登记 + 补漏登记的 009 + tts_segments 死列
  + jobs.type 的 produce 退役注记 + 跨集不加列（集身份是规划期注入）
- docs/service/02：copywriter 行的 slot/window 两个字段名早已不存在，改成 brief + 配对段
- 规格 §3.3.1：降级裁决表的位置列 _generate_one → _plan_one（裁决与理由一字未改）"
```

---

## Task 11: 真机复验（P-2a 出口）

不产新代码，只产证据。**先决条件：P-1.5 Task 10 的九模式门禁已闭环、机器上没有别的门禁在跑**（本任务要真跑 LLM 与 ffmpeg，CPU 争用会让两边的时序断言都不可信）。

- [ ] **Step 1: 只跑规划，确认"不渲染"是真的，且方案真的跨集**

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe scripts/verify_modes.py --modes full_narration --variants 3 --plan-only --require-cross-episode --out D:/tmp/dc-p2a-plan > /tmp/p2a-plan.log 2>&1; echo REAL_EXIT=$?`

Expected: **`REAL_EXIT=0`**，日志末尾的表格里 `状态=completed`、**`集数` 列 ≥2**，紧跟两行附注：`规划 3 条 · 建了 0 行 export_jobs（必须为 0）` 与 `逐条取材集数：[3, 2, 3]` 这类（**逐条的数比列里那个 max 重要**：max 只说明"至少有一条跨了"，逐条才说明"三条各自取了几集"）。

**为什么这两个旗标一起跑**：`--plan-only` 一条片都不渲，所以 `--require-cross-episode` 在这一跑上**零成本**——规格 §1 的机器判据因此不必等 Step 3 那次真渲染。这也让本步成为整份 Task 11 里唯一"既能证明拆分生效、又能证明跨集生效"的一步。

**原计划这一步的 Expected 是虚构的（B10）**：它期望门禁"因为只规划不渲染而报没有成品"，可 Task 9 Step 2 的改写让门禁**总是**提交渲染，于是 `--variants 3` 跑完会真渲三部片、`REAL_EXIT=0`，什么都证不了。修法不是改期望文字，是给门禁加 `--plan-only`（Task 9 Step 2.2/2.3）：规划完就 `continue`，并**查库断言该 batch 的方案一行 `export_jobs` 都没有**。把失败当证据是假绿的一种；查库得到的 0 才是证据。

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe -c "import json,pathlib;rows=json.loads(pathlib.Path('D:/tmp/dc-p2a-plan/summary.json').read_text(encoding='utf-8'));print([{k:r.get(k) for k in ('mode','status','phase','plans','export_jobs','episodes','episodes_per_plan')} for r in rows])"`

Expected: `[{'mode': 'full_narration', 'status': 'completed', 'phase': 'plan-only', 'plans': 3, 'export_jobs': 0, 'episodes': 3, 'episodes_per_plan': [3, 2, 3]}]`（**`episodes_per_plan` 的具体数字由选题模型给，逐次会不同**；要断的是三件事：`plans == 3`、`export_jobs == 0`、`max(episodes_per_plan) >= 2`）。

- `plans < 3`：说明有角度被重叠闸门拦了（回去看 Step 2 的集数前提与 `llm_angles_*.json` 里的 `episode_numbers`）。
- `export_jobs > 0`：说明 `--plan-only` 没接住提交，两者都是真缺陷。
- `max(episodes_per_plan) < 2`（此时 `REAL_EXIT` 已经是 1，门禁自己报了）：**先分辨是哪一种**，别直接改代码——① `llm_angles_*.json` 里模型给的 `episode_numbers` 每条都只有一个集号 ⇒ 选题 prompt 的问题，属《开放问题》#1，交业主；② 模型点了多集而落库的时间轴上只剩一集 ⇒ casting/预算的问题（Task 3c：`_fit_duration` 按播出序填充，预算可能在第二集之前就用完；活库实测 `intro_narration` 一手点 4 集、时间轴上只出现 2 集），那是**本批次的缺陷**，就地查 `_casting_for` 与编排器的盖章处。

**不要用 `| tail` 判退出码**（管道退出码是 `tail` 的，P-1.5 真踩过）。

- [ ] **Step 2: 人工核三条角度真的互异、且真的跨集**

**先确认前提**：本步骤期望"三条角度的**取材集组合**互不相同、重叠近 0，且至少一条横跨 ≥2 集"，那要求隔离副本库里**至少有 3 集 `status='done'`**（K=3 的口径；跨集判据本身只要 2 集）。门禁自己不分析任何东西，它读的是复制来的 `data/data.db` 里现成的东西。Task 9 Step 2.4 已为此加了停机分支（`done < --variants`，或 `--require-cross-episode` 而 `done < 2` → 打印原因 → `return 2`），所以：

Run: `grep -E "已分析|环境未就绪" /tmp/p2a-plan.log | head -3`

Expected: 一行 `项目 xxxxxxxx · 已分析 N 集 · …` 且 **N ≥ 3**（审查时实测活库是 **10 集**，故正常情况满足）。若看到 `环境未就绪：本次口径需要至少 3 集已分析`、`REAL_EXIT=2`，那不是产品坏了——先把集数分析够，或退而用 `--variants 1` 只验 Step 3。**不要为了让 Step 1 过而把 `--variants` 悄悄降到 1**：那样 `plans=3` 与 `集数 ≥2` 两条判据就都自动失效了，本步骤要验的正是"K 条真的互异、且真的跨集"。

集数够，才继续下面两条。

Run: `ls -dt tmp_dc-verify-data_*/logs/llm/llm_angles_*.json 2>/dev/null | head -1`

Expected: 打印出一个路径，形如 `tmp_dc-verify-data_xxxxxxxx/logs/llm/llm_angles_full_narration_0912_183041.json`。**若为空就是选题层没被调用**，停下排查，不要继续本步骤后面的断言。

（拿到路径后）Run: `.venv/Scripts/python.exe -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));print(d['user'][:1500]);print('---');print(json.dumps(d['attempts'][-1],ensure_ascii=False)[:1200])" <上一步的路径>`

Expected: prompt 里有「需要 3 条卖点互异的取材角度」、「**每条角度的 episode_numbers 给出这条片要用到的全部集号（至少一个，可多个）**」、跨集转写摘录（每集一个「【第N集】」分组）；`attempts` 末项里有 3 条 `name` 互不相同、`episode_numbers` **组合**互不相同的角度。

**⚠️ 这里原先期望的是「恰好一个集号」——那句措辞随 C8 一起删掉了**（`angles._episode_rule` 与 `_sanitize` 里那条 `len(numbers) != 1` 的 raise 都不存在了）。照旧文案核对会误判成"选题层没按新前提改"，或者更糟：为了让它对上而把 `cross_episode` 形参加回去，那就是把已经作废的收窄又装回代码里。**现在的正确形态是：prompt 明确要求每条角度给出全部取材集，且至少有一条给出 ≥2 个集号。**

**若一个 `llm_angles_*` 都没有，说明选题层根本没被调用，别往下走**——那比任何后续数字都严重（与 P-1.5 Task 10 Step 2 对 `llm_copy_*` 的判据同理）。

再从隔离副本库里读落库的角度、重叠与**集数**（**副本，不是 `data/data.db`**）：

Run: `.venv/Scripts/python.exe -c "import json,sqlite3,glob;p=(sorted(glob.glob('tmp_dc-verify-data_*/data.db'))+sorted(glob.glob('tmp_dc-verify-data_*/*.db')))[0];print(p);c=sqlite3.connect(p);rows=c.execute('select variant_index,angle,overlap_max,episode_ids,plan_data from narration_plans order by narration_mode,variant_index').fetchall();print([(v,a,o,len(json.loads(e)),len({s['episode_id'] for s in json.loads(d)['timeline']})) for v,a,o,e,d in rows])"`

Expected: **3 行**，每行是 `(variant_index, angle, overlap_max, episode_ids 的集数, 时间轴上的集数)`：

- `angle` 三个不同名字；首行 `overlap_max` 为 `None`，其余两行为接近 0 的小数（三条角度的取材集互不相交）。**若三行 `overlap_max` 都是 0.0，说明首条被误当成"比过且不重叠"，回去查 `_worst_overlap` 的 `None` 分支。**
- **每行最后两个数必须相等**（`episode_ids` 的长度 == 时间轴上不同 `episode_id` 的个数）。不等就是卡片的「取材集区间」会说谎（规格 §9.5），而这条不变量在真数据上只有这一步能验——单元测试里它由 `test_episode_ids_come_from_the_timeline_not_the_brief` 与 `test_get_plan_exposes_the_episodes_a_plan_spans` 守着，但那两条的夹具都是手搓的。
- **至少一行的集数 ≥2**：那就是规格 §1 的「跨集方案」在真素材上的样子。若三行都是 1，Step 1 的 `--require-cross-episode` 已经红了，按那里的两分支法排查（选题 prompt vs casting/预算）。

- [ ] **Step 3: 规划 + 提交两步都跑通，出一条真片**

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe scripts/verify_modes.py --modes full_narration --variants 1 --out D:/tmp/dc-p2a > /tmp/p2a-gate.log 2>&1; echo REAL_EXIT=$?`

Expected: `REAL_EXIT=0`，表格里 `planner=llm_script`、`LUFS` 落在目标 ±2.5、`峰dB` 在门限内、`max_freeze_s < 2`、**`集数` ≥1（这条口径不强制跨集，理由见下）**。**这一步同时证明渲染侧一行未改**：P-1.5 的响度与 planner 判据在拆分之后仍然成立。

**两个与 P-1.5 实测表的预期差异，先说清楚免得被当成回归**：

1. **时长会比 P-1.5 的 49.83s 长**。`full_narration` 的 `_MAX_SCENES`=8 与 `_FULL_SCENE_S`=10 都没变，但取材池从"ep1 一集"变成"角度点名的那几集"，8 个场景现在可能来自 2-3 集。活库实测（只读重算，见 Step 3d 的方法）：四集一手 planned **42.04s / 8 段 / 3 集**，按 P-1.5 的成片比值 1.44 推 ≈ **60.5s**。上限 300s，余量极大。
2. **本步刻意不加 `--require-cross-episode`**：K=1 时取材集由选题模型给的一条角度决定，它可能只点一集——那是合法形状（§1 要的是一条方案**可以**跨集），拿它当硬判据会造出一条与产品无关的红。规格 §1 的机器判据在 **Step 1**（K=3、零渲染成本）。本步只看 `集数` 列的**读数**并记进 Step 5。

耗时提示：LLM 选题 1 次 + 成稿 1 次 + TTS 若干 + 渲染，跨集素材约 5-10 分钟；用 `run_in_background`，不要中途判死。

- [ ] **Step 3b: 加跑一次剧本驱动模式（补 Task 6 Step 10 #14 的覆盖缺口）**

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe scripts/verify_modes.py --modes dialogue_narration --variants 1 --out D:/tmp/dc-p2a-cross > /tmp/p2a-cross.log 2>&1; echo REAL_EXIT=$?`

Expected: `REAL_EXIT=0`，`来源=llm_script`、响度落在窗口内、**`集数` ≥2**（剧本驱动的跨集是 P-1.5 之前就有的行为：`build_from_script_episodes` 逐 `script.segments` 按集号取素材、`cursors` 按集各持一个游标；P-1.5 实测那条片 56.10s / 7 段 / 7 插桩，本次的取材集会由角度收窄，故段数可能变少，但集数不该掉到 1——掉到 1 说明 `_plan_one` 的 `scoped` 过滤把角度点名的集全滤掉了，回去查 `episode_inputs` 的集号类型）。

**这是"剧本驱动豁免成稿前闸门"唯一的端到端证据**：Task 6 Step 10 的变异 #14（删掉 `_reject_same_episode_sibling` 对 `_SCRIPT_DRIVEN_MODES` 的豁免）在单元测试里红不了，因为本批次没有 `dialogue_narration` 的端到端用例（要真 LLM 写剧本，或造一个能产出可控跨集时间轴的替身——后者会钉住替身的形状而不是产品的行为）。**这一跑就是它的替代证据**，别省。

耗时提示：编剧链比规则成稿慢（跨集转写摘录 + 一次剧本往返），加渲染约 10-20 分钟；整条命令用 `run_in_background`。

**若 `dialogue_narration` 因"取材集都没有转写"或剧本不合格而 failed**：那是 P-1.5 已知的编剧链行为（禁止降级，拿不到合格剧本就抛），不是 P-2a 引入的回归。判据是看 `/tmp/p2a-cross.log` 里的失败原因串——含「选题」/「剧本」字样属上游，含 `-32601` / `不可渲染` / `没有配音音频` 才是本批次的问题。

- [ ] **Step 3c: 加跑规则类两模式，`--variants 3`（本轮新增：真数据上的轮转发窗）**

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe scripts/verify_modes.py --modes raw_clip,subtitle_flow --variants 3 --out D:/tmp/dc-p2a-rule > /tmp/p2a-rule.log 2>&1; echo REAL_EXIT=$?`

Expected: `REAL_EXIT=0`，两行都 `状态=completed`、`来源=rule`、`TTS=0`、`带旁白=0`、**`集数` ≥3**，且日志里能看到 `_rule_variants` 的逐条留痕（`纯原片剪辑·第 1 条：取第 2、5、6、9 集（全剧冲突窗轮转发窗，不经选题模型）` 这类）。

这一步一次验四件事，且**都是活库实测过、可以照抄核对的数字**（只读重算的方法见 Step 3d；活库十集的窗排名实测 `[6,7,8,2,3,4,9,10,1,5]`，K=3 发成三手 `[2,5,6,9]` / `[3,7,10]` / `[1,4,8]`，三手互不相交 ⇒ 取材重叠恒为 0 ⇒ `overlap_max` 首条 `None`、其余 `0.0`）：

| 模式 | 第 1 条 | 第 2 条 | 第 3 条 |
|---|---|---|---|
| `raw_clip` | 21 段 / planned 117.89s / **4 集** → 成片 ≈120.6s | 20 段 / 120.89s / **3 集** → ≈123.7s | 18 段 / 107.72s / **3 集** → ≈110.2s |
| `subtitle_flow` | 7 段 / planned 36.24s / **3 集** → 成片 ≈38.4s | 7 段 / 38.84s / **3 集** → ≈41.2s | 7 段 / 35.28s / **3 集** → ≈37.4s |

（成片预估用的比值取自 P-1.5 的九模式实测：两个无旁白模式的 成片/planned 是 `raw_clip` **1.0231**、`subtitle_flow` **1.0609**。真机数字会因素材与消重抖动而差几秒，**差 5% 以内都算对上**；差得多就先查 `集数` 与 `段数`，那两个数不该漂。）

四件事：① **规则类没被拖进 LLM**（`来源=rule`、`TTS=0`，即《定案四》第 5 点与 `EXPECT_PLANNER` 的真机证据）；② **`top_conflict_windows` → `deal_windows` → `_casting_for` → 编排器**这条新链在真数据上跑得通；③ **手间不共集 ⇒ 零重叠**在真数据上成立（不是只在手搓夹具上成立）；④ **规则类的方案真的跨集**（每条 3-4 集），这是规格 §1 在**零 LLM** 那一族上的证据——Step 1 只覆盖了解说类。

耗时提示：两个模式都不配音，P-1.5 实测单条渲染 6.1s / 13.1s，六条片合计约 2 分钟，是本任务最便宜的一步。

- [ ] **Step 3d: 量一次 `--variants 1` 的预算饱和（只算不渲，本轮新增）**

**这一步不渲染、不写库、不跑 LLM**，只用真编排器在活库的只读副本上算 planned 源秒。它存在的全部理由是 Task 9 Step 2.8 末尾那条发现：`--variants 1` 时 `deal_windows(windows, 1)` 把**全部**集发进同一手，`raw_clip` 的候选场景因此吃满 `_fit_duration` 的预算，成片会越过 `strategy.max_duration_s`。这个数必须交给业主（《开放问题》#5），但**不该靠跑一次注定红的渲染去拿**——那是把 3 分钟的门禁时间花在一个已经算出来的结论上。

把下面这份存成 `D:/tmp/p2a_measure_k1.py`（**它只以 `mode=ro` 打开活库，不写任何东西，也不打印集 id 或任何标识符**）：

```python
"""只读活库 + 真编排器算 planned 源秒：不渲染、不写库、不打印标识符。"""

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(r"D:/PersonProjects/DramaClip")
sys.path.insert(0, str(REPO / "service"))

from dramaclip.engines.narration import casting, pipeline
from dramaclip.engines.narration.modes import build_raw_clip
from dramaclip.engines.narration.modes_w9 import build_subtitle_flow
from dramaclip.engines.narration.models import StrategySpec
from dramaclip.engines.semantic.models import ConflictScore

# 成片/planned 的比值取自 P-1.5 Task 10 的九模式实测（两个无旁白模式各一个）
DRIFT = {"raw_clip": 15.48 / 15.13, "subtitle_flow": 32.43 / 30.57}

conn = sqlite3.connect(f"file:{REPO / 'data' / 'data.db'}?mode=ro", uri=True)
budget = float(
    conn.execute("select value from settings where key='strategy.max_duration_s'").fetchone()[0]
)
rows = conn.execute(
    "select e.episode_number, a.conflict_scores, a.asr_segments from episodes e"
    " join episode_analysis a on a.episode_id = e.id where e.status='done'"
    " order by cast(e.episode_number as integer)"
).fetchall()
scored = [
    (int(number), [ConflictScore.model_validate(item) for item in json.loads(raw or "[]")])
    for number, raw, _asr in rows
]
# 集 id 用占位串：本脚本只量时长与集数，真 id 不进输出（活库纪律）
material = {
    f"ep{number}": casting.EpisodeMaterial(number=number, asr=[])
    for number, _scenes in scored
}
windows = pipeline.top_conflict_windows(scored, len(scored))
by_number = dict(scored)
print(f"窗排名={[n for n, _ in windows]} · 预算={budget:.0f}s")
for hands in (1, 3):
    print(f"=== --variants {hands} ===")
    for rank, hand in enumerate(pipeline.deal_windows(windows, hands), start=1):
        scenes = casting.stamp([(n, f"ep{n}", by_number[n]) for n in hand])
        for mode, plan in (
            ("raw_clip", build_raw_clip(scenes, [], StrategySpec(max_duration_s=budget))),
            ("subtitle_flow", build_subtitle_flow(scenes, material, StrategySpec())),
        ):
            planned = sum(seg.end - seg.start for seg in plan.timeline)
            film = planned * DRIFT[mode]
            flag = " ← 顶穿预算" if film > budget else ""
            print(
                f"  第{rank}条 手={hand} {mode}: {len(plan.timeline)}段 / "
                f"{len({s.episode_id for s in plan.timeline})}集 / planned {planned:.2f}s"
                f" → 成片≈{film:.2f}s{flag}"
            )
```

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe D:/tmp/p2a_measure_k1.py`

Expected（**审计时用一个与真编排器同规则的重算得到，并与 Task 3c Step 8 那张实测表在五个点上逐位对上**：ep1 单集 `raw_clip` 15.13s/3 段、四集一手 117.89s/21 段/4 集、`subtitle_flow` 36.24s/7 段/3 集、窗排名 `[6,7,8,2,3,4,9,10,1,5]`、`intro_narration` 269.06s——故下面这组数可信；跑完请拿真脚本的输出替换它）：

```
窗排名=[6, 7, 8, 2, 3, 4, 9, 10, 1, 5] · 预算=300s
=== --variants 1 ===
  第1条 手=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10] raw_clip: 51段 / 9集 / planned 296.21s → 成片≈303.06s ← 顶穿预算
  第1条 手=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10] subtitle_flow: 7段 / 6集 / planned 37.77s → 成片≈40.07s
=== --variants 3 ===
  第1条 手=[2, 5, 6, 9] raw_clip: 21段 / 4集 / planned 117.89s → 成片≈120.61s
  …（其余两手与 Step 3c 的表一致）
```

**读到 `← 顶穿预算` 那一行要做的三件事**（不要就地改门禁阈值——C6 已经裁定阈值不动，而阈值确实不该动，它量的是用户的设置）：

1. 把这一行的三个数（手覆盖的集数、`planned`、预估成片）抄进 Step 5 的实测记录；
2. 确认 `subtitle_flow` **没有**顶穿（它被 `_MAX_SCENES`=6 × `_FLOW_SCENE_S`=8 卡住，与预算无关）——所以这不是"规则类整体超时长"，是 `raw_clip` 一个模式的问题，因为它没有场景条数上限；
3. 交《开放问题》#5：修法是给 `_fit_duration` 的预算留一档**编码漂移余量**（与它已经给引子槽位预留 `_INTRO_MAX_S` 同一个手法），余量 ≥6.1%（两个无旁白模式的实测漂移比值里较大的那个）。**这一档常数取多少是设计决定，本审计不替业主拍**，故它落在 Task 3c 而不是这里。

- [ ] **Step 4: 用耳朵验收一条（不可省略）**

至少人工听 Step 3 出的那条 `full_narration`，确认：① 旁白没有被原声盖住；② 没有因 `normalize=0` 带来的爆音；③ **解说内容与角度名对得上**（这是本批次唯一能靠耳朵验的东西——重叠率是数字，"这条片是不是在讲它宣称的那个卖点"只能听）。

**跨集裁决给这一步加了两条只有耳朵能验的**（都对应一个"数字全绿而片子是坏的"的真实坏法）：

④ **集与集硬切的那一处，解说讲的还是画面上这件事吗？** 这是 C7 那个缺陷的验收面：`_slot_block` 若仍按摊平的 ASR 表取台词，编剧会拿到**别的集**的对白，写出一段通顺、可信、说的却不是这段画面的解说——`overlap_max`、`planner`、响度、插桩覆盖**全都正常**，`episode_ids` 也全对，唯一的破绽在耳朵里。听的时候盯住切换点前后各一句：前一句收尾的东西与后一句开场的画面，得是同一条线。
⑤ **整条片读起来是一条故事线，还是十集交错？** 叙事顺序是播出序（`casting.episode_order` = 集号 → 集内起点 → scene_index）。若哪个编排器还在按 `start` 排，成片会 ep1@0s、ep7@0s、ep1@12s 这么来回跳——**这条同样没有任何数字能抓到**（段数、集数、时长全对），只有看着像"剪得很碎"。

把结论写进 Step 5 的记录里——**写"已听，结论 X"，不接受"断言全绿所以应该没问题"**。④⑤ 两条若听不出来（例如那条片恰好只取了一集），也要如实写"本条未跨集，④⑤ 无从验"，并在 Step 3c 的六条规则类片里挑一条跨集的补听——**不许跳过、也不许写"应该没问题"**。

- [ ] **Step 5: 把实测写回本计划并清理临时目录**

在本文档末尾追加 `## Task N 落地后的实测修正` 小节（与 P-1.5 同一体例），记录：

- 三条角度的实测名字、各自的 `episode_numbers` 与 `overlap_max`（Step 2）；
- 选题 prompt 的实际形态（尤其"每条角度给出全部取材集（至少一个，可多个）"那句是否被模型遵守）；
- Step 1 的 `plans` / `export_jobs` / `episodes` / `episodes_per_plan` 四个实测值；
- Step 3 的 `集数` 与 `时长s` 实测值（与预估的 ≈60.5s 对一下）；
- Step 3b 里 `dialogue_narration` 的 `来源`/`集数`/`TTS`/`带旁白` 四列实测值；
- Step 3c 那张表的**六格实测**（两模式 × 三条），逐格与预估对齐或写明偏差；
- **Step 3d 的 `← 顶穿预算` 那一行三个数**（手覆盖集数 / planned / 预估成片），并在《开放问题》#5 下面追加一行"真机实测已确认/未确认"；
- Step 4 的耳朵结论，逐条 ①–⑤；
- 与预期不符之处、以及计划里被证伪的假设（如有）。

**Task 9 Step 1b 要求移交的 `scripts/verify_e2e.mjs` 两处失效派发也记在这里**（文件、`:152`/`:168` 两个行号、旧方法名、新调用形态 `narration.plan_variants` → 等作业 → `narration.list_plans(batch_id)` → `export.submit(plan_ids)` → 等全部 export job、以及 `git log -1 --format=%an` 取到的属主名字）——那是给下一个人看的，不是给本批次验收用的。

清理。临时目录由 `_same_drive_temp` 创建，**首选 `dir=REPO`，所以它们落在仓库根**。其中 `tmp_dc-verify-data_*` 里有一个名为 `models` 的目录联接指向真实的 `data/models`——**顺序不可颠倒**：先 `rmdir` 摘掉联接，再 `rm -rf` 目录；反过来会顺着联接删掉开发者的模型。

```bash
cd /d/PersonProjects/DramaClip
for d in tmp_dc-verify-data_*; do cmd //c "rmdir $(cygpath -w "$PWD/$d/models")" 2>/dev/null || true; done
rm -rf tmp_dc-verify-data_* tmp_dc-verify_* D:/tmp/dc-p2a D:/tmp/dc-p2a-plan D:/tmp/dc-p2a-cross D:/tmp/dc-p2a-rule D:/tmp/p2a_measure_k1.py
ls data/models/tts/kokoro/*/ | head -3   # 必须仍在：联接被删过一次就再也没有了
```

若最后一条 `ls` 为空，立刻停下并报出来——那说明联接连同模型被误删，需要从备份或重新下载恢复，不要继续提交。

- [ ] **Step 6: 提交**

```bash
git add docs/superpowers/plans/2026-09-12-p2-plan-render-split.md
git commit -m "docs(plan): 记录 P-2a 真机复验结果与实测修正"
```

---

## P-2b 交接规格 / P-2c 取消记录

本计划只交付规格 §6 的 P-2 五项里的前三项。后两项按下面的边界另成计划。**这里给的是边界与已知陷阱，不是任务步骤**——步骤由各自的 writing-plans 轮次产出。（本节原先还含一份《P-2c 交接规格》，已被下面那段《取消记录》整节替换。）

### P-2b：剧库（规格 §6 的 P-2 第 ④⑤ 项）

**出口**：批量建项目与阶段定位可用。

**内容**：

1. `project.batch_create`（规格 §5 #4）：一次多个目录 → 一部剧一个项目，剧名默认取文件夹名。已知陷阱：`projects.source_path` 是 `TEXT NOT NULL UNIQUE`（`migrations/001_init.sql:7`），同一目录选两次会撞唯一约束——必须逐目录给结果（成功/已存在/目录不存在/目录里没有视频），不许一整批炸掉，形态与 `export.submit` 的 `{exports, rejected}` 同构。建项目之后是否顺带 `scan_episodes` 要定案：`scan_episodes` 逐文件跑 ffprobe，35 部剧 × 80 集会让这个 RPC 阻塞几分钟，故应做成 job 而不是同步返回。
2. `project.list` 阶段聚合（规格 §5 #3/#5）：每部剧回四阶段状态（§3.1 的四态：未开始/进行中/完成/已过期）+ 卡点文案 + `current`（卡片点击直跳）。已知陷阱：**`jobs.ref_id` 的语义按 job 类型而变**——`prescreen`/`analysis`/`narration` 是 project_id，`semantic` 是 episode_id（`api/analysis.py:223`），`export` 是 **export_id**（`api/export.py:79`），`model_download` 是 model_id。所以"这部剧有没有在跑的出片作业"必须经 `export_jobs` 联查，不能直接按 ref_id 过滤 jobs。规模：§9 验收 7 要求 50 部剧下不卡，故聚合必须是 SQL 而不是 N+1 的 Python 循环（`projects_repo.list_all` 现在的 `episode_count` 已经是 JOIN + GROUP BY，照那个形态扩）。
3. 「已过期」判据（§3.1）：`episode_analysis.analyzed_at` 的最大值 vs `narration_plans.created_at` 的最大值。P-2a 之后还要多判一层：**同 batch 内最新的方案**才算数，否则一次重掷会让整阶段显示过期。

**冲突面（必须等 P-2a 合入再开工）**：`protocol/ts/index.ts`（`METHOD_NAMES` 与 `Project` 类型）、`protocol/schemas/project.json`、`docs/03-IPC协议规范.md` §5.2/§6、`docs/service/01-传输与API层设计.md` §4/§6、`docs/service/04-数据模型.md` §4 迁移清单、`desktop/src/services/client.ts` 的 `projectApi`。**迁移号用 `011`**（P-2a 占了 `010`）；若 P-2b 其实不需要新列（阶段聚合是纯查询），就不要建迁移。

### P-2c 取消记录（2026-09-12 业主裁决）

**这一节原来是《P-2c：单条方案内的跨集拼接》的交接规格，现在是一份取消记录。**

**裁决**：业主**拒绝**给《定案二》那次收窄签字。规格 §1 的原话是「一次提交（剧 × 模式）→ 每模式产出 1..K 条**卖点角度互异**的**跨集**方案」——"跨集"是**方案**的定语，不是批次之间比较的定语。**P-2a 就做真跨集：一条方案可以从多集取画面拼在同一条时间轴上。P-2c 不存在。**

**原交接规格里列的每一件待办，都落进了本批次，逐条对账**：

| 原 P-2c 的内容 | 落在哪 | 状态 |
|---|---|---|
| 「得让 `ConflictScore` 带上集身份、或让编排器接受『每集一组场景』」 | **两条都没选**，选的是第三条：`casting.EpisodeScene` 子类在**规划期**盖章（`casting.stamp`），`ConflictScore` 一个字段不加、`episode_analysis` 一行不改、不需要迁移 | Task 3c Step 1/3，理由与"加字段会往落库 JSON 里写 `episode_number: 0` 这种假值"的实测见《修订记录》C3/C4 |
| 六个编排器「签名是 `(episode_id, scenes, strategy)`，一条片只吃一集」 | 六个编排器首参换成 `scenes: list[EpisodeScene]`，段的 `episode_id` 由**每个场景自己**带；排序键换成播出序（`casting.episode_order`）与确定性分数序（`casting.score_order`）；12 处盖章逐个改 | Task 3c Step 4，跨集性质由 `test_cross_episode_arrangement.py` 十条 + 14 条变异检查守着 |
| 「重新分配时长预算（`_fit_duration` 现在按 `strategy.max_duration_s` 截断单集场景，多集直接叠加会超预算数倍）」 | `_fit_duration` 的**末场景预算豁免删掉**（单集时代它是死的：活库最大单集 204.2 场景秒 < 300）、`intro_first` 时从预算里**预留** `_INTRO_MAX_S`=30s | Task 3c Step 4 + 《修订记录》C6；门禁阈值一个字不改，逐条推导在 Task 9 Step 2.8 |
| 「同一个前置也卡着《定案四》的后半句：规则类做不到"每条方案的内容就是它那一窗"」 | 前置**已拆掉**（集身份与预算都有了）。剩下的理由从技术变成**产品**：一个窗只有 3-25s，"内容 = 一窗"会把 `raw_clip` 压成 3-25 秒的片，而活库实测它今天是 15.13s（跨集一手 117.89s）。本批次交付的是"用全剧冲突榜决定**条数与每条的取材集组合**"，再让编排器在这些集的全部场景上照常选 | Task 3b 的 `top_conflict_windows` + `deal_windows`（轮转发成 K 手，手间不共集）；**这一半仍待业主回答，见《开放问题》#1** |
| 「P-2c 必须在 P-1.5 出口闭环之后、且自己带一轮九模式门禁」 | 不再是"另一轮门禁"：跨集判据（`集数` 列 + `--require-cross-episode`）直接进了**既有的**九模式门禁，与响度/时长/planner 同一次跑 | Task 9 Step 2.8 + Task 11 Step 1/3c/3d |
| 槽位台词按集取用（原交接规格**没有**这一条，是裁决逼出来的真缺陷） | `copywriter.write_plan_copy` 第二参换成 `casting.MaterialByEpisode`，`_slot_block` 按 `segment.episode_id` 取台词并把集名写进 prompt；缺键**抛**，不退回"该区间无台词"。`modes_w9.strongest_line` 同病同修 | Task 4 Step 3b + 《修订记录》C7；这是本裁决最贵的一条：不改就是编剧对着别集的画面、拿别集的台词写出一段通顺可信的假解说 |

**为什么保留这份记录而不是把整节删掉**：本文件里还有三处正文点名"P-2c"（《计划修订记录》R2、《修订记录》C1/C4/C6、《定案二》末段），它们是**当时的真相**——R2 记的是"这次收窄不是计划自己能定的"，C1 记的是"业主拒绝签字"。删掉这一节会让那三处引用悬空，而悬空引用正是"下一个人以为还有 P-2c 可以做"的入口。**取消要留痕，取消的痕迹不能自己变成一个新的悬空指针。**

**真的还开着的两条**（都不是 P-2c，都在《开放问题》里）：#1 规则类的"内容 = 一窗"与 `raw_clip` 的形态变化；#5 `raw_clip` 在 `--variants 1` 下吃满时长预算（Task 9 Step 2.8 的实测发现，修法在 `_fit_duration`）。

### P-3：回收站 / 本地数据（**这一条是 P-2a 新产生的义务，不是原有的**）

`9b42f24` 把配音文件名改成了**内容寻址**：`{slot_id}-{sha1(text|voice|engine)[:12]}.mp3`。它带来一个必须写下来的后果——

1. **两条方案可以共用同一个音频文件**。文案、音色、引擎三者相同的槽位，无论来自哪一次规划、哪一个作业，都落在同一个路径上（这是有意的：缓存优先、不二次付费，`test_identical_copy_is_synthesised_once` 钉着它）。
2. **而《定案一》把 `work_dir` 提升为承重存储**：一条 `ready` 方案可能在几小时后、几次重启后才被 `export.submit` 渲染，届时读的就是 `plan_data.narration_texts[*].audio_path`。

**所以 P-3 的回收站不能按"创建时间"或"创建它的作业"删音频文件**——那会静默作废另一条老方案的 `audio_path`。正确的模型是**引用计数**：一个音频文件可删，当且仅当没有任何 `narration_plans` 行的 `plan_data` 指向它。实现上最省事的形态是一条全表扫描 + JSON 提取（`narration_plans` 规模是"剧 × 模式 × K"，几百到几千行，不是性能问题），把 `audio_path` 收成集合，再对 `work_dir/tts` 做差集。**不要建"每个作业一个目录"来让按作业删除变安全**：那会把跨作业的缓存复用一起废掉（Task 5 已论证并有用例守着）。

好消息是这个坑不会静默产出坏片：Task 8 的 `_assert_renderable` 会对每个旁白段 `Path(audio_path).is_file()` 一次，文件没了就当场 `rejected` 并给出「配音音频已丢失：… （重新规划这条方案即可）」。坏消息是**用户会看到一批方案突然不可渲染**，而那批方案本来没坏——所以 GC 的设计必须先行。

**另一条残余（修复代理点出，本计划原样登记）**：内容摘要覆盖 `text + voice + engine` **名**，不覆盖**模型权重**。所以本地 Kokoro 升级之后，旧文件仍然会被当成缓存命中，用户听到的是旧模型的声音，直到有人手动删掉那些文件。可选的修法是把模型版本/权重摘要也进哈希（`tts.factory` 知道模型目录，能给出 mtime 或版本串）；本批次不做，因为它要动 `9b42f24` 刚落地的那层，而 P-2a 的纪律是"渲染与合成逻辑一行不动"。**P-3 若做「本地数据」页，请把这个残余一并摆到台面上**（规格 §3.3 的"参数未生效/静默"同一类）。

---

## 完成判据（全部满足才算 P-2a 收口）

1. `cd service && ../.venv/Scripts/python.exe -m pytest -q` 全绿（`test_analysis.py` 的既有隔离 flake 除外，且本批次未碰它）。
2. `cd service && ../.venv/Scripts/ruff.exe check .` 与 `../.venv/Scripts/mypy.exe dramaclip` 均无输出。
3. `cd /d/PersonProjects/DramaClip && npm run lint && npm run typecheck && npm run test` 全绿（含两侧契约同步测试）。
4. Task 11 **Step 3 / 3b / 3c** 三次真机门禁全部 `REAL_EXIT=0`，且 `planner` 逐模式对上 `EXPECT_PLANNER`、响度落在窗口内、`集数` 列有读数——**前三项是"渲染侧一行未改"的证据，最后一项是"跨集真的发生了"的证据**。
5. Task 11 Step 2 的实测记录已写回本文件：三条角度名互异、`overlap_max` 首条为 `None`、其余接近 0，**且每行 `episode_ids` 的集数 == 该方案时间轴上不同 `episode_id` 的个数**（不等就是卡片的「取材集区间」会说谎，规格 §9.5）。
6. `grep -rn "generate_plans\|_run_generation_parallel\|_generate_one\|_newest_ready_plan\|_run_produce\|narration.produce\|export.start" service/dramaclip desktop/src protocol scripts --include=*.py --include=*.ts --include=*.tsx --include=*.json --include=*.mjs` —— **`service/dramaclip` / `desktop/src` / `protocol` 三处零命中**，`scripts` 下**恰好两条**且都在另一位工程师的 `scripts/verify_e2e.mjs`（`:152` 与 `:168`，已按 Task 9 Step 1b 书面移交、并写进 Task 9 Step 8 的提交信息）。**`--include=*.mjs` 不可省**：R6 那次漏了它，于是"逐条对账，一条都不许漏"正好漏掉唯一一个 `.mjs` 调用方，而 Expected 写"无输出"会让执行者以为门禁坏了、或者去改别人的文件。
7. `export.submit` 对一个已规划好的 batch 提交后，`export_jobs` 行数等于该 batch 的方案行数（一条方案一行），且每行都有对应的 `jobs` 行（`type='export'`、`ref_id=export_id`）。
8. 本计划里每一张变异检查表都逐条跑过并逐条按字节还原。
9. **规格 §1 的机器判据过了**：Task 11 Step 1 带 `--require-cross-episode` 跑完 `REAL_EXIT=0`，即 `full_narration` 的三条方案里**至少一条**的时间轴横跨 ≥2 集；Step 3c 的规则类三手各 3-4 集（**零 LLM 那一族的跨集证据**，与 Step 1 各覆盖一半）。`ultra_short_hook` 按 C13 豁免，其 `集数` 期望值是 **1**。
10. **《开放问题》#5 有明确处置**：`raw_clip` 在 `--variants 1`（门禁默认口径）下会把 `_fit_duration` 的预算吃满、成片越过用户设的 `strategy.max_duration_s`（活库实测 planned **296.21s / 51 段 / 9 集** → 预估成片 **≈303s** > 300）。收口前必须二选一并写进实测记录：**要么**在 `_fit_duration` 里给编码漂移留出余量（≥6.1%，两个无旁白模式的实测比值）并重跑 Step 3d 确认不再顶穿，**要么**业主明确接受"K=1 的 `raw_clip` 会略超时长上限"并把它记进《已知不做》。**不许既不改也不记就签收**——那是规格 §9.5「参数未生效」那一类，而它同时会让九模式门禁在默认口径下红一条。

## 已知不做 / 不在本批

- **队列页、K 条角度出片、成本预估卡**：规格 §6 的 P-2.5。本批次只把数据准备好（`batch_id`/`variant_index`/`overlap_max`/`plan_cost`），不建页面。
- **成品自检四项、`export.set_cover`**：P-3。
- **`tools.*` 工具箱**：规格 §6 建议的独立小批次，与本批次无交集。
- **画面通道 / `subtitle_probe` / `vision` 域**：规格 §10，批次 2。
- **`serial_per_episode`（连载模式开关，规格 §5 #21）**：**规格自己已经裁决过了，本批次不实现。** `4228bef` 把 §5 #21 改成 `export.submit(plan_ids, serial_per_episode=true)`——**提交时参数**，与 §4.3 ④ 那句"提交时参数，不写入 `project.settings`"一致，原先那处"§5 挂在 `plan_variants` 上、§4.3 ④ 说它是提交时参数"的自相矛盾**已不存在**；§6 的 P-2 行也明写「**不含 `serial_per_episode`**」，P-2.5 行把它列为该批次的唯一附带项。理由与量级不变：一条方案/集会把计划数推成 集数 × 模式数（80 集 × 9 模式 = **720 条**），没有队列页根本不可用，故它天然属 P-2.5。**P-2a 的 `export.submit` schema 因此只有 `plan_ids` 一个属性**（`additionalProperties: false`），P-2.5 接手时要补的两句话见 Task 8 Step 4 末尾。
- **渲染侧的项目级覆盖**（字幕预设、输出四键、响度目标）：`render_export` 仍直接读 `context.settings`。P-2a 只把 K 与风格接上了项目覆盖（那是 `plan_variants` 自己的入参）。接线归 P-3 的包装区。
- **阶段③ 如何把"重掷的单条"并回 K 条一组显示**：P-2a 保证方案行只追加、`batch_id` 齐全，任何并法都可行；具体并法是 P-3 的展示决策。
- **规则类「重掷此条」的留痕没有用例**：`_rule_variants` 里 `if rerolled:` 那段 `notifier.log`（如实说明"窗口榜是确定性的、重掷会得到同一条方案"）**在自动化上红不了**——那条路径要 P-2.5 的阶段③ 才有入口，本批次没有任何用例会走到它。代码保留是因为 §3.3 禁止静默，不是因为测到了；等阶段③ 落地时补用例（Task 6 Step 10 #15 登记的是同一件事）。
- **`narration_plans.tts_segments` 死列**：已在 `docs/service/04` 登记为死列，不在本批删除（理由见 Task 10 Step 4）。
- **配音音频的磁盘回收**：《定案一》把 `work_dir/tts/` 变成承重存储（**内容寻址之后没有"按作业分目录"这一层了**，Task 5 已论证并删掉），它只增不减。回收归 P-3 的「关于 → 本地数据」与回收站，且**不能按作业或按时间删**——见《P-3 交接规格》第 1 条。

---

## 开放问题（正文点名到这里，逐条都要业主回答；未答的不许当成"已默认同意"）

本节原先**不存在**，而正文有五处点名到它（R2/R3 与《定案四》末段、《定案二》、Task 9 Step 2.8、Task 11 Step 3d）——那是上一轮修订留下的悬空引用，本轮补上。每条都给"问题、依据的数字、需要谁决定什么"，不给结论。

**#1 规则类两模式的"内容 = 一窗"，以及 `raw_clip` 的形态变化（原 R2 的那一问，裁决后换了内容）**

- **原来问的是**："§1 的跨集是不是只要求 K 条合起来覆盖全剧？" —— **已被业主回答：不是，每条方案自己就要跨集。** 这一问关闭，P-2c 取消（见《P-2c 取消记录》）。
- **现在问的是**：规格 §4.3 ④ 定「规则类 = 全剧 top-K 冲突窗」，本批次交付的是"用冲突窗**排名**决定条数与每条的取材集组合，再让编排器在这些集的全部场景上照常选"，**不是**"每条方案的内容就是它那一窗"。差别是量级上的：一个窗只有 3-25s（`_RAW_CLIP_MIN_S`/`_RAW_CLIP_MAX_S`），而活库实测 `raw_clip` 今天是 **15.13s / 3 段 / 1 集**，跨集一手（K=3）是 **117.89s / 21 段 / 4 集**——**7.8 倍**，从"三镜头爽点剪辑"变成"两分钟多集混剪"。
- **要不要改成"内容 = 一窗"**：改了 `raw_clip` 每条只有 3-25s，而 `subtitle_flow` 的 CTA 卡片段（`_CTA_FALLBACK_S` = 3.0s）会比正片还长。**需要业主定**：规则类的每条方案应该是"一窗"还是"一手集里的全部合格场景"。本批次按后者实现，并在 `top_conflict_windows` 的 docstring 里如实写了这个差别。

**#2 `serial_per_episode` 归哪一侧 —— 已关闭（`4228bef`）**

规格 §5 #21 与 §6 已把它定为 `export.submit` 的提交时参数、归 P-2.5，P-2 行明写「不含 `serial_per_episode`」。原先那处"§5 与 §4.3 ④ 自相矛盾"的开放问题**不复存在**，本计划不实现它（详见《已知不做》对应条目与 Task 8 Step 4 末尾留给 P-2.5 的两句话）。**保留编号是为了让正文里"《开放问题》#2"这个引用不悬空**，不是还开着。

**#3 规则类的方案卡上，「模型自选理由」那一格显示什么**

- 规格 §4.3 ③ 把四要素写成**每卡**的结构，但规则类两模式没有模型、也就没有"模型自选理由"。本批次留空串（与 `protocol/schemas/narration.json` 里 `NarrationPlan.angle` 的描述「无解说的模式为空串」逐字对应）+ `notifier` 逐条留痕。
- **需要业主定**：空串可接受，还是要显示一句**确定性推导**文案（例如「全剧冲突榜第 N 窗（第 X 集 a-bs，冲突分 S）」）？后者不是假文案（逐字可核对），但它不是"模型自选理由"，规格得给它一个名字。**界面留白 vs 规格加一个字段名，二选一。**

**#4 规则类的「重掷此条」今天是个空操作**

- `exclude_plan_ids` 只贡献角度名（`_excluded_angle_names` 跳过空 `angle`），而窗口榜是确定性的 ⇒ 重掷得到**同一条方案**。本批次如实留痕（`_rule_variants` 的 `if rerolled:` 那一行），但按钮按下去什么也不会变。
- **需要业主定**：要不要把规则类的「重掷此条」换成「改方案数/改素材」——那是 P-2.5 队列页与阶段③ 的展示决策，本批次不做界面。

**#5 `raw_clip` 在 `--variants 1` 下吃满时长预算，成片越过用户设的上限（本轮审计新查出）**

- **数字**（活库只读重算，方法见 Task 11 Step 3d；同一套重算在 Task 3c Step 8 那张表的五个点上逐位对上）：`--variants 1` ⇒ `deal_windows(windows, 1)` 把**全部 10 集**发进同一手 ⇒ 合格场景（分数 ≥70、时长 3-25s）共 **59** 个、**346.5** 场景秒 > 预算 **300** ⇒ `_fit_duration` 吃满，planned **296.21s / 51 段 / 覆盖 9 集**（ep10 一帧都拿不到）。`raw_clip` 无旁白槽位，成片 = planned × 编码漂移，P-1.5 实测漂移 **1.0231**（`subtitle_flow` 同类 **1.0609**）⇒ 成片 **≈303.0s**（保守 **314.3s**）> 门禁的 `strategy.max_duration_s` = **300** ⇒ 时长断言红、`REAL_EXIT=1`。
- **为什么单集时代不出这件事**：ep1 单集的合格场景只有 **15.1s / 3 段**，离 300 差 20 倍。这是**跨集裁决直接产生的新失败形态**。
- **它不只是门禁红**：用户设的"最长时长"没生效，属规格 §9.5「参数未生效」那一类。
- **修法在 `_fit_duration`（Task 3c），不在门禁阈值**（C6 已裁定阈值不动，且阈值确实不该动——它量的是用户的设置）：给预算留一档**编码漂移余量**，与它已经给引子槽位预留 `_INTRO_MAX_S` 同一个手法。**余量取多少需要业主/执行者拍**：实测依据是 ≥6.1%（两个无旁白模式的漂移比值里较大的那个），即 300s 的预算收到 ≤282s；取整到 `_JITTER_HEADROOM_RATIO = 0.07` 或固定 20s 都能覆盖，两者对 `intro_narration`（已预留 30s、成片 ≈286s）都还有余量。**本审计不替业主拍这个数**，故《完成判据》#10 要求收口前二选一：改，或明确接受并记进《已知不做》。
- **顺带一条同源的产品问题**：K=1 时 `raw_clip` 的取材集是**全剧 10 集**、成片 ≈5 分钟。规格 §1 说「1..K 条」，K=1 是合法输入，而"一部 5 分钟的纯原片混剪"是不是操盘手要的`raw_clip`，与 #1 是同一个问题的两面。

---

## 自查（对照规格与"无占位符"纪律）

**1. 规格覆盖**

| 规格出处 | 要求 | 本计划落点 |
|---|---|---|
| **§1 核心处理单元** | **「每模式产出 1..K 条卖点角度互异的**跨集**方案」——"跨集"是**方案**的定语** | **Task 3c（`casting.py` + 六个编排器逐段盖自己场景的集号）+ Task 4 Step 3b（槽位台词按集取用，跨集的前置条件）+ Task 3b Step 3b（`deal_windows` 轮转发窗，让零 LLM 那一族也跨集）+ Task 6（`_casting_for` 按角度点名的集装配、`used_ids` 从时间轴反推）。机器判据：Task 9 Step 2.8 的 `集数` 列与 `--require-cross-episode`，Task 11 Step 1/3c 真机跑；豁免只有 `ultra_short_hook`（C13）。`ultra_short_hook` 之外任何模式的 `集数` 恒为 1，就是不达标** |
| §6 P-2 第 ① 项 | 拆 `produce` → `plan_variants` + `export.submit` | Task 6（规划侧）+ Task 8（渲染侧）+ Task 9（删旧入口与迁调用点） |
| §6 P-2 第 ② 项 | `narration.get_plan` | Task 6 Step 7 实现 + Task 7 用例（含跨集的 `episode_ids`/区间暴露，Task 7 Step 1 的 `test_get_plan_exposes_the_episodes_a_plan_spans`） |
| §6 P-2 第 ③ 项 | 角度重叠度量 | Task 2（度量，**按 `(episode_id, start, end)` 三元组分组**：`source_spans` 逐集合并、`_intersect` 逐集双指针，故第 3 集的 0-10s 与第 7 集的 0-10s 是两段不同画面）+ Task 6 Step 7 第 10/11 点（成稿前按取材集组合、成稿后按实测 Jaccard 两道闸门）+ Task 11 Step 2（真机核对） |
| §5 #16 | `plan_variants(project, modes, k)` | Task 6 |
| §5 #17 | `plan_variants(exclude_plan_ids=[…])` | Task 6（`_excluded_angle_names` + `test_exclude_plan_ids_reaches_the_selection_prompt`） |
| §5 #18/#33 | `narration.get_plan` 用于详情与成品追溯 | Task 6/7；方案行只追加、永不覆写（《定案三》）保证 #33 的追溯不漂 |
| §5 #19 | 重叠率显示 | `overlap_max` 列（Task 1）+ 度量（Task 2） |
| §5 #20 | 模式多选作为 `plan_variants` 入参 | Task 6 |
| §5 #21 | `serial_per_episode` | **不在本批**——规格 `4228bef` 已定为 `export.submit` 的提交时参数、归 P-2.5（《已知不做》+《开放问题》#2 + Task 8 Step 4 末尾给 P-2.5 的两句话） |
| §5 #22 | `export.submit(plan_ids)` | Task 8 |
| **§4.2 空态第 ② 步** | **「**仅「纯原片剪辑」「字幕金句流」不依赖 LLM**」（用户定案，本计划不得推翻）** | **《定案四》+ Task 3b（规则类的条数另有来源，零 LLM）+ Task 6 Step 7 第 11 点的 `if mode in _NARRATION_MODES` 分流 + `test_rule_modes_never_construct_an_llm_client`（替身在 `__init__` 里就炸，钉的是"不构造客户端"而不是"构造了但失败"）+ 变异 #11 + Task 11 Step 3c 的真机 `来源=rule`/`TTS=0`。B2/R1 就是这一条：原计划让每个模式都先调 `angles.select_angles`，等于把"不依赖 LLM"改成"依赖 LLM"** |
| **§4.3 ④** | **「条数按模式族分别算：**解说类 = K，规则类 = 全剧 top-K 冲突窗**（两者不同源，已由用户定案）」** | **《定案四》+ Task 3（解说类的 K 条来自 `angles.select_angles`）+ Task 3b（规则类来自 `top_conflict_windows` → `deal_windows`，**不经任何模型**）+ Task 6 的 `_angle_variants`/`_rule_variants` 在 `_Variant` 上会合（五件事只写一遍）。两族**不同源**是用户定案，故本计划没有第四份手抄模式清单：规则类就是 `frozenset(SUPPORTED_MODES) - _NARRATION_MODES`** |
| §4.3 卡片四要素 | 角度名 / 取材集区间 / 钩子首句 / 模型自选理由 | `angle`（列）/ `episode_ids`+`plan_data.timeline[*].episode_id,start,end`（既有；**跨集之后"区间"必须逐集给**，Task 7 开头第 1 点交代了为什么集号不另立字段）/ `narration_texts[0].text`（既有，见《定案三》为何不另立列）/ `angle_reason`（列，规则类为空串 →《开放问题》#3） |
| §4.3 重叠率阈值 60% | 超阈值直接不出该角度 | `overlap.OVERLAP_LIMIT = 0.60` + Task 6 的 raise |
| §3.3.1 禁止级 | 不得重新引入模板或规则兜底、不得吞掉编剧链的 raise | Task 10 Step 6 的第三条 grep（新模块里不许出现降级语义词）；`angles._sanitize` 少答即抛（Task 3）；`_plan_one` 原样透传 `copywriter`/`script_driver` 的异常（Task 6）；**跨集新增的三条拒绝分支一律抛而不是降级**——缺号（`_casting_for` 的 `missing`）、缺分析行（`record is None`）、槽位的集不在台词表里（`casting.dialogue_of`/`label_of`），三条各有用例与变异检查（Task 6 Step 10 #10/#10b、Task 4 Step 7 #4/#5） |
| §3.3 静默禁止（允许级降级必须留痕） | 少出方案、某集取不到画面、某手只取一集、规则类重掷无效 | Task 6 的 `_rule_variants` 四处 `notifier.log` + `_casting_for` 的"第 N 集没有冲突场景"；前三处有用例（`test_rule_mode_yields_fewer_than_k_and_leaves_a_trace`、`test_episode_ids_come_from_the_timeline_not_the_brief`），第四处如实登记为"没有用例"（Step 10 #15 +《已知不做》） |
| 失败粒度=单条方案 | K 条独立失败 | Task 6 的 `test_one_variant_failure_does_not_kill_its_siblings` + `test_one_mode_failure_does_not_kill_other_modes`；try/except 位置下沉到变体循环内（变异检查 #1 钉住） |
| `narration_id` 是唯一配对键 | 不得按位置推断 | 本批次未新增任何位置推断：`_assert_renderable` 按 `narration_id` 查音频表（Task 8），`tts_audio_by_segment` 逐字就是按 id 取（`api/export.py:172-179`），`angles` 不碰配对。**`plan_data` 无 `window` 字段这一事实继续成立，但 C7 改了它的一半**：区间仍从配对段读（`_slot_block` 的 `segment.start/end`），而**台词**在 Task 4 Step 3b 之后按 `segment.episode_id` 逐集读——原表这里写的"Task 4 未改"已作废 |
| 成本可观测 | 每变体 1 次成稿 + N 次配音，可观测而非事后重算 | `plan_cost()` 单一口径（Task 6 Step 7 第 8 点），**两个数都与集数无关**（Task 7 开头第 2 点给了代码依据，`test_get_plan_exposes_the_episodes_a_plan_spans` + 变异 #2b 钉住）+ 选题次数由 `batch_id` + `DISTINCT narration_mode` 数出（《定案二》） |
| §6 P-2 出口 | 阶段③ 能只看方案不渲染 | `test_plan_variants_writes_k_plans_without_rendering` 断言 `export.list == []`；Task 11 Step 1 真机复核（`--plan-only` 查库得 `export_jobs=0`） |
| §6 P-2 出口 | 批量建项目与阶段定位可用 | **不在本计划**，见《P-2b 交接规格》——本计划开头《范围裁决》已说明拆分理由 |

**2. 占位符扫描**：全文无 "TBD"、无"添加适当的错误处理"、无"同 Task N"式的转指（Task 9 Step 6 的对照表逐条写了处置方式与断言口径，不是"参照上文"）、代码块内无 `...（其余不变）...` 省略。每一处 `Expected:` 都给了具体的失败形态或退出码。

**3. 类型与命名一致性**（逐个核对过；**本轮按裁决后的签名重核了一遍**，原表里 `_pick_episode`、`cross_episode`、`_voice(…, job_id, mode, index)`、`_plan_one(…, brief)` 四处都已作废）：

- `casting.EpisodeScene`（`ConflictScore` 的子类，多 `number: int` 与 `episode_id: str` 两个字段）—— Task 3c 定义；六个编排器的首参类型、`pipeline.build_plan` 的第二参、`top_conflict_windows` 之外的全部取材入口都用它。`casting.EpisodeMaterial(number, asr)` 与别名 `MaterialByEpisode = dict[str, EpisodeMaterial]` —— Task 3c 定义，`build_subtitle_flow` / `write_plan_copy` 的第二参、`_casting_for` 的返回值之一，三处同名同形。
- `casting.stamp(list[tuple[int, str, list[ConflictScore]]]) -> list[EpisodeScene]`、`episode_order` / `score_order`（排序键函数，不是方法）、`dialogue_of(material, episode_id)` / `label_of(material, episode_id)`（**缺键即抛**）—— Task 3c 定义；Task 4 Step 3b 的 `_slot_block`、Task 3c Step 4 的 `strongest_line`、Task 6 的 `_casting_for` 三处调用一致。
- `pipeline.build_plan(mode, scenes, highlights, material, settings)` —— Task 3c Step 5 换的签名（**原 `episode_id` 与 `audio: AudioFeatures` 两个入参都消失**，C11），Task 6 的 `_plan_one` 是唯一生产调用点，`tests/engines/narration/test_modes.py` 的调用点同批迁移。
- `pipeline.top_conflict_windows(list[tuple[int, list[ConflictScore]]], limit) -> list[tuple[int, ConflictScore]]` 与 `pipeline.deal_windows(windows, hands) -> list[list[int]]` —— Task 3b 定义，Task 6 的 `_rule_variants` 是唯一调用点；`deal_windows` 回的是**集号列表的列表**（一手一个升序集号表），直接进 `_Variant.episode_numbers`。
- `overlap.source_spans(plan) -> dict[str, list[tuple[float, float]]]` / `overlap.overlap(left, right) -> float` / `overlap.OVERLAP_LIMIT` —— Task 2 定义，Task 6 的 `_worst_overlap` 是唯一生产调用点。**键是 `episode_id`**：`source_spans` 按 `segment.episode_id` 分组后**逐集**合并区间，`_intersect` 逐集双指针，故"第 3 集的 0-10s"与"第 7 集的 0-10s"是两段不同画面（`test_same_seconds_in_different_episodes_do_not_overlap` 钉住）。这是重叠度量在跨集时间轴上仍然正确的**全部**理由。
- `angles.AngleBrief(name, reason, hook, episode_numbers)` —— Task 3 定义，Task 4（`prompt_block`）、Task 6（`_angle_variants` 把它转成 `_Variant`）、Task 6/9 的测试夹具使用，字段名一致。**规则类也复用这个类型**（`name`/`reason`/`hook` 一律空串，只填 `episode_numbers`），故读它时不要假设它一定出自 LLM（`AngleBrief` 的 docstring 明写）。
- `angles.select_angles(mode, *, mode_label, k, episode_inputs, settings, excluded, trace_dir)` —— Task 3 定义，**六个关键字**（`cross_episode` 随 C8 删除，别顺手加回来），Task 6 的 `_angle_variants` 六个全给（`mode` 为位置参数），Task 6/9 的测试替身按 `kwargs.get("mode_label")` 取用，一致。
- `angles.prompt_block(brief)` —— Task 3 定义，**措辞独家持有**：Task 6 的 `_angle_variants` 调它一次、结果存进 `_Variant.angle_block`，再由 `_plan_one` 分别交给 `copywriter.write_plan_copy(angle_block=…)` 与 `script_driver.script_dialogue_plan(angle_block=…)`。两条成稿链共用同一段字，不许各写一份。
- `narration_api._Variant(name, reason, episode_numbers, angle_block)` 与 `_OverlapHit(name, ratio)` —— Task 6 Step 7 第 10 点定义的两个 frozen dataclass；`_Variant` 是**两族的会合点**（解说类填四个字段、规则类只填 `episode_numbers`），`accepted: list[tuple[_Variant, PlanData]]`、`_worst_overlap`、`_reject_same_episode_sibling`、`_slot_label` 四处按同一形状使用。
- `narration_api._voice(context, plan, settings) -> PlanData` —— Task 5 定义（**只有三个位置参数，没有 `job_id`/`mode`/`index`**：内容寻址已在 `9b42f24` 落地，路径不需要它们），Task 6 的 `_run_plan_variants` 与 Task 5/6 的四个测试替身（`voice_except_second` / `voice_then_cancel` / Step 6 的两处 `lambda _ctx, plan, _settings: plan`）签名一致。
- `narration_api._plan_one(context, mode, episodes, episode_inputs, settings, variant) -> tuple[PlanData, list[str]]` —— Task 6 定义（**第六参是 `_Variant`，不是 `AngleBrief`**；返回二元组，第二个是**从时间轴反推**的集 id），Task 9 Step 6 的迁移用例按同一位置参数序使用。
- `narration_api._casting_for(context, episodes, variant) -> tuple[list[EpisodeScene], list[HighlightSegment], MaterialByEpisode]` —— Task 6 定义，取代了原来的 `_pick_episode`（那个函数名在本计划里**已不存在**，见到它就是残留）。
- `copywriter.write_plan_copy(plan, material, settings, *, mode_label, angle_block, trace_dir)` —— Task 4 定义（第二参从摊平的 `list[AsrSegment]` 换成 `MaterialByEpisode`，`angle_block` 必填），Task 6 的 `_plan_one` 是唯一生产调用点。
- `export_api._assert_renderable(plan_row, plan_data)` —— Task 8 定义，`submit` 与 `retry` 两处调用一致（守卫排在 `reset_for_retry` 的 CAS 之前）。
- `plans_repo.create(..., angle=, angle_reason=, variant_index=, overlap_max=, batch_id=)` —— Task 1 定义，Task 6 `_run_plan_variants` 五个关键字全给，一致。
- `plans_repo.list_by_batch(conn, project_id, batch_id)` —— Task 1 定义，Task 6/7/9 的测试与 Task 9 Step 2 的门禁 SQL（直接查库，不走仓储，因为 `verify_modes.py` 持有的是裸连接）语义一致；**门禁那条 SQL 现在一次取 `id, plan_data` 两列**（2.2），排序键与仓储同为 `narration_mode, variant_index`。
- `narration_api.plan_cost(row)` → `{"copy_llm_calls", "tts_calls"}` —— Task 6 定义，Task 7 断言与 `protocol/schemas/narration.json` 的 `PlanCost` 字段名逐字一致；**两个数都与集数无关**（Task 7 开头第 2 点）。
- `scripts/verify_modes.py` 的新名字：`SINGLE_EPISODE_MODES`（豁免清单，`_mode_table_drift` 有它的子集核对）、`args.variants` / `args.plan_only` / `args.require_cross_episode`（argparse 用连字符、属性用下划线）、`rec["episodes"]` 与 `rec["episodes_per_plan"]`（两条路径都写，前者进 `集数` 列、后者进附注行）。**`columns` 与 `values` 两张表必须同长**（`:638` 是 `zip(..., strict=True)`，改错当场 `ValueError`）。
- 错误码：`-32303`（K 越界）、`-32304`（方案不存在，narration 域）、`-32406`（`plan_ids` 非法）、`-32407`（不可渲染，export 域）——Task 6/8 的常量、Task 6/7/8 的测试断言、Task 10 Step 2 的文档表三处一致。注意 `narration.get_plan` 用的是 **narration 域的 `-32304`**，而 `export.submit`/`retry` 对"方案不存在"用的是 **export 域的 `-32401`**：同一个概念两个码，是因为两个命名空间各有自己的分段（docs/03 §5），**不是笔误**，与既有的"任务不存在有两个码"（`-32501` vs `-32201`）同一处境。

**4. 本计划自身发现并修正的规格/文档问题**（详见交付报告，此处只列计划内的处置）：

- §5 #21 `serial_per_episode` 原先与 §4.3 ④ 自相矛盾 → **规格自己已在 `4228bef` 修掉**（定为 `export.submit` 的提交时参数、归 P-2.5，§6 的 P-2 行明写"不含"）。本计划随之从"等裁决"改成"已裁决、不实现"：《已知不做》+《开放问题》#2（保留编号只为不悬空）+ Task 8 Step 4 末尾留给 P-2.5 的两句话。
- `docs/03` §6 声称 `narration.get_plan` "从未实现、等同 `list_plans`" → 本批次实现它并在 Task 10 Step 2 删掉那句话，理由（K×模式条数下 `list_plans` 不再是"看一条"的合理入口）写进 `get_plan` 的 docstring。
- `docs/03:86` 的 `-32401` 行仍写着"编排时间轴为空" → Task 8 之后那件事改判 `-32407`，Task 10 Step 2 第 5 点改这一行（R4）。
- `docs/service/04` §4 的迁移清单漏登记 `009`、且"实测 8 个文件"已过期（实为 9） → Task 10 Step 4 第 3 点补上。
- `docs/service/04` §4 的 `jobs.type` 注记会被本批次**同时**过期两次（`produce` 类型退役、`jobs.json` 缺 `semantic` 那条偏差被 Task 9 Step 3 修掉） → Task 10 Step 4 第 4 点整块替换。
- `docs/service/02:59` 的 `copywriter.py` 行写着 `slot` / `window` 两个**早已不存在**的字段名（P-1.5《实现定案修正》改成 `brief`、删掉 `window`），而 pydantic 静默忽略未知 kwargs ⇒ 照它写代码不报错、只丢数据 → Task 10 Step 4b 改这一行。
- 规格 §3.3.1 降级裁决表 `:126` 的「位置」列点名 `api/narration._generate_one`，Task 6 删掉那个函数 → Task 10 Step 4c 改成 `_plan_one`（裁决列与理由列一字不动）。
- `protocol/schemas/jobs.json` 的 `JobInfo.type` 词表缺 `semantic`、含即将消失的 `produce` → Task 9 Step 3 一并修正。
- `narration_plans.tts_segments` 是死列 → Task 10 Step 4 登记，不在本批删。
- **《开放问题》这一节原先不存在，而正文有五处点名到它** → 本轮补上（#1–#5，其中 #2 已关闭、#5 是本轮新查出的实测缺陷）。悬空引用与悬空指针是同一类缺陷：读的人会以为"另有一节写着答案"。
