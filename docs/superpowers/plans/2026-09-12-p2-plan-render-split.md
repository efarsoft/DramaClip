# P-2a 规划/渲染解耦 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `narration.produce` 拆成 `narration.plan_variants`（只规划）与 `export.submit`（只渲染），让阶段③ 能"只看方案、反复重掷、不付渲染成本"，并让一个模式的 K 条方案真的是 K 个互异的卖点角度。

**Architecture:** 三层切分——**选题层**（新增 `engines/narration/angles.py`：一个模式一次 LLM 调用产出 K 条卖点互异的取材角度，每条带角度名/理由/钩子首句/取材集）、**成稿层**（既有 `copywriter` / `scriptwriter`，本批次只多接一个"卖点角度"输入，不改其降级禁令）、**度量层**（新增 `engines/narration/overlap.py`：按源素材秒算 Jaccard 取材重叠，超 60% 的角度当场不出）。配音留在规划侧，故一条 `ready` 的方案行就是可渲染的成品输入，`export.submit` / `export.retry` 只读库、不做任何规划。

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

**本批次不做的事（明确记下来，别当遗漏）**：一条方案内跨集拼画面。今天只有 `dialogue_narration` 具备（`pipeline.build_from_script_episodes` 按集号取素材，`engines/narration/pipeline.py` 函数体实测 `:88-174`），其余六个模式的编排器签名是 `(episode_id, scenes, strategy)`，一条片只吃一集。所以本批次让**角度之间**跨集（不同角度取不同集，于是 K 条合起来覆盖全剧），而**单条方案内**仍限于一集。

> ⚠️ **这一条是对规格的收窄，不是计划自己能定的事，须业主签字（R2）。**
>
> 规格 §1 的原话是「一次提交（剧 × 模式）→ 每模式产出 1..K 条**卖点角度互异**的**跨集**方案」——**跨集写在方案的定义里**，不是写在批次之间的比较里。本计划把它读成"角度之间跨集"，是一次**收窄**，签字之前不得当作已决。
>
> 收窄的技术理由（站得住，但不等于业主同意）：改六个编排器的取材结构会改**成片形态**，而九模式真机门禁的出口判据（时长窗、响度窗、冻结帧）正压在这个形态上；P-1.5 Task 10 尚未闭环时动它，两批的验收证据会混在一起、出问题无法归因。
>
> **要业主回答的问题**（见《开放问题》#1）：§1 的"跨集"是指 ① K 条合起来覆盖全剧（本计划的做法，P-2a 可交付），还是 ② 每条方案自己就跨集取画面（需要 P-2c 先给 `ConflictScore` 加集身份、再重分时长预算）？若是 ②，P-2a 的出口判据要重写，且必须排在 P-1.5 出口闭环之后。
>
> 真正的跨集拼接归 P-2c（见末尾《P-2c 交接规格》）。P-1.5 的《已知不做》把跨集化记成了 P-2 的事，这里如实收窄并说明理由。

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

1. **榜单必须跨集**。今天两个编排器吃的都是**单集**的 `ConflictScore` 列表（`build_raw_clip(episode_id, scenes, highlights, strategy)`、`build_subtitle_flow(episode_id, scenes, asr_segments, strategy)`），而 `ConflictScore`（`engines/semantic/models.py`）只有 `scene_index/start/end/score/reason`，**不带集身份**。所以跨集排序只能在编排器**之外**做，并且必须把 `(集号, 场景)` 成对喂进、成对取出——否则排完就不知道那一窗属于谁。
2. **按集去重，一集一条**。`build_raw_clip` 与 `build_subtitle_flow` 都是 `(episode_id, 该集场景表)` 的**确定性纯函数**：同一集的两个不同窗口喂进去会得到**逐字节相同**的方案。那不是 K 条互异，是 1 条复制 K 份，而且会被重叠闸门判成 100% 重叠、把 K-1 条报成失败。故"窗"在这里的作用是把**集**排出名次。
3. **条数可以少于 K，但必须留痕**。去重后不足 K 时（极端例子：全剧只分析完 1 集）返回 1..K-1 条。规格 §1 的原话是「每模式产出 **1..K** 条」，所以少出是合法形状；但 §3.3 禁止静默，故 `_rule_variants` 在少出时打一行 `notifier.log`，说明"top-K 窗去重后只落在 N 集"。
4. **`angle` 与 `angle_reason` 一律留空串**。规则类没有模型自选的卖点角度，也没有旁白槽位去读钩子。这与 `protocol/schemas/narration.json` 里 `NarrationPlan.angle` 的描述「无解说的模式为空串」逐字对应，也与 Task 1 的 `test_angle_columns_default_to_the_migration_defaults` 一致。界面卡片靠**四要素里的「取材集区间」**（`episode_ids` + `plan_data.timeline`）加 `variant_index` 区分。
5. **`planner` 仍是 `"rule"`**。两个编排器都不写 `planner`，`PlanData.planner` 的默认值就是 `"rule"`（`engines/narration/models.py:60`），而成稿链一次都不跑——所以 `verify_modes.py` 的 `EXPECT_PLANNER` 无需改动。**这是"规则类没被拖进 LLM"最便宜的一道真机证据。**

**本批次做不到、且必须说清楚的那一半**：让**每条方案的内容真的等于它那一窗**。那需要 `ConflictScore` 带上集身份、或让编排器接受"每集一组场景"，并重分时长预算（`modes/__init__.py::_fit_duration` 现在按 `strategy.max_duration_s` 截断单集场景）——这既改**编排器签名**又改**成片形态**，正是《定案二》末段与《P-2c 交接规格》推迟的那件事。**所以 P-2a 交付的是"用全剧 top-K 冲突窗决定规则类的条数与取材集"，不是"每条规则类方案就是一窗"**。这个差别写进 Task 3b 的 docstring，不藏在代码里。

**两个待业主回答的问题**（见《开放问题》#3、#4）：

- 规则类的 K 条方案卡上，「模型自选理由」那一格显示什么？规格 §4.3 ③ 把四要素写成**每卡**的结构，但规则类没有模型理由。本批次留空串 + 日志留痕，是否可接受，还是要显示"全剧冲突榜第 N 窗（第 X 集 a-bs，冲突分 S）"这类**确定性**推导文案？后者不是假文案（它逐字可核对），但它不是"模型自选理由"，需要规格给个名字。
- 规则类的**重掷此条**今天是个空操作：`exclude_plan_ids` 只贡献角度名（`_excluded_angle_names` 跳过空 `angle`），而窗口榜是确定性的 → 重掷会得到**同一条方案**。本批次如实留痕（Task 6 Step 7 第 11 点在规则族分支打一行日志说明重掷无意义），要不要把规则类的「重掷此条」按钮换成「改方案数/改素材」是 P-2.5 队列页与阶段③ 的展示决策。

---

## 文件结构

**新建**

| 路径 | 职责 |
|---|---|
| `service/dramaclip/engines/narration/angles.py` | 选题层（**解说类七模式**）：一个模式一次 LLM 调用 → K 条卖点互异的 `AngleBrief`；逐条验收、不合格即抛 |
| `service/dramaclip/engines/narration/overlap.py` | 度量层：源素材秒的 Jaccard 取材重叠 + 60% 阈值常量。纯函数，不触 IO |
| `service/dramaclip/infra/storage/migrations/010_plan_angles.sql` | `narration_plans` 五列 + batch 索引 |
| `service/tests/engines/narration/test_angles.py` | 选题层的验收分支逐条钉住（**18 条变异检查**，对应 `_sanitize` 的 13 处 raise + `select_angles` 的 5 处） |
| `service/tests/engines/narration/test_overlap.py` | 合并、交集、Jaccard、阈值边界 |
| `service/tests/engines/narration/test_conflict_windows.py` | 规则类的"选题"：全剧 top-K 冲突窗排序、按集去重、同分确定性、`limit < 1` 即抛 |
| `service/tests/infra/storage/test_plans.py` | 五个新列的落库与读回、`list_by_batch`（两模式交错夹具）、`list_by_project` 的并列兜底 |
| `service/tests/api/test_plan_variants.py` | 由 `tests/api/test_produce.py` 改名而来（`git mv`）：`Harness` 与种子函数留在此文件，`test_data_paths.py:8` 的 import 随之改 |
| `service/tests/api/test_export_submit.py` | `export.submit` 的接受/拒绝两路、可渲染性守卫、与 `retry` 的同形 |

**修改**

| 路径 | 改什么 |
|---|---|
| `service/dramaclip/api/narration.py` | 删 `produce`/`_run_produce`/`generate_plans`/`_run_generation_parallel`/`_generate_one`/`_newest_ready_plan`；加 `plan_variants`/`_run_plan_variants`/`_angle_variants`/`_rule_variants`/`_plan_one`/`_pick_episode`/`_voice`/`get_plan`/`plan_cost`/`_effective_settings`/`_worst_overlap`/`_excluded_angle_names` + `_Variant`/`_OverlapHit` 两个内部 dataclass；删三个随之失去引用的 import（含 `exports as exports_repo`） |
| `service/dramaclip/api/export.py` | `start` → `submit(plan_ids)`；加 `_assert_renderable` 并被 `submit`/`retry` 共用；两个新错误码；**并修 `ExportRun`（`:49-63`）与 `_submit_export`（`:66-94`）的 docstring**——它们写着 `start/retry/produce` 三处调用点，Task 6/8 之后只剩 `submit`/`retry` 两处 |
| `service/dramaclip/engines/narration/pipeline.py` | 加纯函数 `top_conflict_windows`（Task 3b，规则类的条数来源）；改 `_synthesize_into` 的 docstring（Task 5 Step 5——它点名了 Task 6 要删的三个函数）。**渲染与合成逻辑一行不动** |
| `service/dramaclip/engines/narration/copywriter.py` | `write_plan_copy` 增必填关键字 `angle_block`，进 user prompt |
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
| `scripts/verify_modes.py` | ① `:39` 的 import 区加 `export as export_api`、`:456-457` 的 Router 装配加 `export_api.register(router, ctx)`（**B1：不加这两行，九个模式全拿 `-32601`，门禁 exit 1**）；② `:459` 的单次派发 → 规划 + 提交两步；③ argparse 加 `--variants`（默认 1）与 `--plan-only`；④ `done` 计数之后加前置条件停机分支；⑤ `:75-85` 的 `EXPECT_PLANNER` 推导散文与 `:382` 的注释改指新函数名 |
| `service/tests/api/test_data_paths.py` | `:8` 的 import 源改名；`:18-23` 的 `narration.produce` → 规划 + 提交两步 |
| `docs/03-IPC协议规范.md` | §5.2 错误码表加 `-32303/-32304/-32406/-32407`、**改 `:86` 那一行**（`-32401` 不再覆盖"编排时间轴为空"）；§6 的「46 个方法」重数、`narration.*`（`:118`）与 `export.*`（`:119`）条目改写、删掉「`narration.get_plan` 从未实现」那句（`:131`，本批次实现它） |
| `docs/service/01-传输与API层设计.md` | §4 的方法清单（`:66-67`）与合计数（`:75`）、§6 的「`projects.settings` 尚无消费端」（`:132`）改成已接线并登记覆盖键名 |
| `docs/service/04-数据模型.md` | `narration_plans` 的 DDL（`:108-` ）加五列、迁移清单（`:305`，"实测 8 个文件"已过期，实为 9）加 `010` 行并补上漏登记的 `009`、§3 登记实际使用的项目级覆盖键名 |

**不动**：`docs/05-开发路线图.md`（用户自维护）；另一位工程师的 `scripts/verify_e2e.mjs`（**它有两处会随本批次失效的派发，P-2a 不改它，改为书面移交属主，见 Task 9 Step 1b**）、`scratch/`、`tests/api/test_analysis.py`、`tests/engines/analysis/*`、`hotwords.py`、`docs/07-*`；`data/data.db`（只读，实测含 52 行方案）；六个模式编排器 `modes/__init__.py`、`modes_w5.py`、`modes_w8.py`、`modes_p2.py`、`modes_w9.py`（《定案四》：规则类的 K 条在编排器**之外**决定，不改它们的签名与成片形态）；`engines/exporter/*`（渲染侧一行不动，这是拆分干净的证明）；`engines/narration/pipeline.py` 的合成与编排逻辑（本批次只加一个纯函数、改一段 docstring）。

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
        "cross_episode": False,
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
    assert "恰好一个集号" in prompt, "单集模式的取材约束没交代给模型"


def test_cross_episode_mode_asks_for_a_set(llm: Any) -> None:
    llm.queue = [{"angles": [dict(_angle(1, 1), episode_numbers=[1, 3])]}]
    briefs = _select(
        mode="dialogue_narration", mode_label="剧情解说", k=1, cross_episode=True
    )
    assert briefs[0].episode_numbers == [1, 3]
    assert "至少一个" in FakeLlm.calls[0]
    assert "恰好一个集号" not in FakeLlm.calls[0]


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


def test_single_episode_mode_rejects_multi_episode_angle(llm: Any) -> None:
    payload = {
        "angles": [dict(_angle(1, 1), episode_numbers=[1, 2]), _angle(2, 2), _angle(3, 3)]
    }
    llm.queue = [payload, {"angles": []}]
    with pytest.raises(ValueError, match="本模式一条片只取一集"):
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


def _episode_rule(cross_episode: bool) -> str:
    if cross_episode:
        return (
            "本模式可跨集取材：每条角度的 episode_numbers 给出这条片要用到的全部集号"
            "（至少一个，可多个）。"
        )
    return "本模式一条片只取一集素材：每条角度的 episode_numbers 恰好一个集号。"


def _sanitize(
    raw: Any,
    *,
    k: int,
    known_numbers: set[int],
    cross_episode: bool,
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
        if not cross_episode and len(numbers) != 1:
            raise ValueError(
                f"角度「{name}」给了 {len(numbers)} 集，本模式一条片只取一集"
            )
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
    cross_episode: bool,
    excluded: list[str],
    trace_dir: Path | None = None,
) -> list[AngleBrief]:
    """为一个模式选出 K 条互异角度；答不出互异就抛，不凑数。"""
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
        f"{_episode_rule(cross_episode)}"
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
                cross_episode=cross_episode,
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

Expected: PASS（`test_angles.py` **24** 条 + 另两个文件既有用例全绿）

- [ ] **Step 6: 变异检查（本任务的重点，一条都不许省）**

**抛出点实数：`_sanitize` 13 条 + `select_angles` 5 条 = 18 条**（原计划写"十三条拒绝分支"，漏数了 `select_angles` 里的 `k < 1`、`LlmUnavailable` 未配置守卫、无已完成集、无转写、重试耗尽汇总，也漏了 `_MAX_REASON_CHARS` 那条**连用例都没有**的分支——R8）。上一批的实测修正是这么写的：「新增拒绝分支的用例必须当场做『删掉这行分支看它红不红』的验证，否则它只是把 happy path 又跑了一遍」。逐条破坏、逐条跑 Step 5 的命令、逐条按字节还原：

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
| 13 | `if not cross_episode and len(numbers) != 1` 改成 `if False`（`_sanitize`） | `test_single_episode_mode_rejects_multi_episode_angle` |
| 14 | `if k < 1: raise`（`select_angles`） | `test_k_below_one_raises` |
| 15 | `if not config.configured: raise LlmUnavailable(...)`（`select_angles`） | `test_unconfigured_llm_raises_before_prompt`（**含 `FakeLlm.calls == []` 那半条断言**：守卫删掉之后请求就发出去了） |
| 16 | `if not episode_inputs: raise`（`select_angles`） | `test_no_episodes_raises` |
| 17 | `if not transcript: raise`（`select_angles`） | `test_no_transcript_raises` |
| 18 | `if briefs is None: raise` 改成 `return []`（`select_angles` 末尾的汇总抛出） | `test_gateway_failure_retries_then_raises`（改成 `return []` 而不是整块删：删掉会让 mypy 报"缺少返回语句"，那是类型检查红，不是用例红，证不出这条分支被测着） |

**第 3 条的陷阱**（上一批踩过同类）：删掉 `isinstance(item, dict)` 之后 `AngleBrief.model_validate("一条字符串")` 会抛 `ValidationError`，被下一行转成 `ValueError("角度项字段不合法")`——用例仍然红，但红的已经不是这条分支（第 4 条顶着）。所以 `test_non_object_item_raises` 的 `match` 必须写死「非对象项」这个词：**变异后它要因为消息对不上而红，才算真的守着这一行**。同理第 4 条的 `match` 写死「字段不合法」。

**第 13 条的陷阱**：`numbers` 在该分支之前已经 `sorted(set(...))`，若把去重删掉，`[1, 1]` 会被判成"给了 2 集"而误红——去重与单集判定是一对，破坏其一时要看清红的是哪条断言。

**第 7 条为什么单列一行**：三个长度上限共用"超出长度上限"这个措辞，`match` 只写这一段时三条分支会互相顶包。原计划正是因此漏掉了 reason 那条——它没有用例，删掉 raise 全套照绿。

- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/engines/narration/angles.py service/dramaclip/engines/narration/scriptwriter.py service/tests/engines/narration/test_angles.py service/tests/engines/narration/test_script_input_budget.py
git commit -m "feat(narration): angles 选题层，一个模式一次调用产出 K 条互异卖点"
```

---

## Task 3b: 规则类的"选题"——`pipeline.top_conflict_windows`（全剧 top-K 冲突窗，纯函数）

规格 §4.3 ④：「条数按模式族分别算：**解说类 = K，规则类 = 全剧 top-K 冲突窗**（两者不同源，已由用户定案）」。Task 3 做的是解说类那一半；本任务做规则类那一半。设计依据全部在《定案四》，这里只落代码。

**为什么放在 `pipeline.py` 而不是新开一个模块**：`pipeline.py` 已经是"编排层"的入口（`build_plan` 的模式分派就在这里），而这个榜单的唯一用途就是决定"喂给哪个 `build_*` 的 `episode_id`"。为一个函数新开文件会让编排知识分两处。

**为什么不放进 `modes/__init__.py` 或 `modes_w9.py`**：那两个文件在《文件结构》的**不动**清单里——本批次不改任何编排器的签名与成片形态（《定案二》末段、《P-2c 交接规格》）。榜单在编排器**之外**算，正是为了不动它们。

**Files:**
- Modify: `service/dramaclip/engines/narration/pipeline.py`（在 `build_plan` 之后、`build_from_script_episodes` 之前插入一个纯函数）
- Create: `service/tests/engines/narration/test_conflict_windows.py`

- [ ] **Step 1: 写失败测试**

新建 `service/tests/engines/narration/test_conflict_windows.py`：

```python
"""规则类两模式的条数来源：全剧 top-K 冲突窗（规格 §4.3 ④）。

夹具手搓 ConflictScore，不跑分析层也不跑编排器：本函数是纯函数，把上游拉进来
只会让"榜单排错了"与"冲突分算错了"两种失败混在一起。

这里钉的四件事，每件都对应一个真实的坏法：
① 跨集排序（`ConflictScore` 不带集身份，排完不知道那一窗属于谁就没法用）；
② 按集去重（同一集的两窗喂进 `build_raw_clip` 会得到逐字节相同的方案，
   那不是 K 条互异，是 1 条复制 K 份，还会被重叠闸门判成 100% 重叠）；
③ 同分时的确定性（分析层给的是 0-100 的**整数**分，全剧尺度上同分很常见；
   不确定就意味着"整组重规划"两次取到不同的集）；
④ limit < 1 即抛（与 `angles.select_angles` 的 `k < 1` 同一口径）。
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_conflict_windows.py -q`

Expected: FAIL —— 七条全红，`AttributeError: module 'dramaclip.engines.narration.pipeline' has no attribute 'top_conflict_windows'`

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

    为什么按集去重：`build_raw_clip` 与 `build_subtitle_flow` 的签名都是
    `(episode_id, 该集的场景表, …)`，且都是**确定性纯函数**——同一集的两个不同窗口
    喂进去会得到逐字节相同的方案。那不是 K 条互异，是 1 条复制 K 份，而且会被
    `overlap` 判成 100% 重叠、把 K-1 条报成失败。所以"窗"在这里的作用是把**集**排出名次。

    **本批次做不到的那一半，写在这里而不是藏在代码里**：让每条方案的内容真的等于它那一窗。
    那需要 `ConflictScore` 带上集身份（`engines/semantic/models.py` 今天只有
    scene_index/start/end/score/reason）、或让编排器接受"每集一组场景"，并重分时长预算
    （`modes/__init__.py::_fit_duration` 现在按 `strategy.max_duration_s` 截断单集场景）。
    两者都改**成片形态**，而九模式真机门禁的时长窗与响度窗正压在这个形态上——归 P-2c。

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

- [ ] **Step 4: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_conflict_windows.py tests/engines/narration -q`

Expected: PASS（新增 7 条 + `tests/engines/narration` 既有用例全绿——本任务是**纯新增**，不该碰红任何既有用例；若有红的，说明插函数的位置切断了什么，就地修）

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

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_conflict_windows.py -q`

- [ ] **Step 6: 提交**

```bash
git add service/dramaclip/engines/narration/pipeline.py service/tests/engines/narration/test_conflict_windows.py
git commit -m "feat(narration): 全剧 top-K 冲突窗排序——规则类两模式的条数来源（规格 §4.3 ④）"
```

---

## Task 4: 卖点角度进成稿 prompt（两条链同形）

角度只影响选题是不够的：`copywriter` 若不知道这条片的卖点，K 条方案的**文案**会趋同，而重叠度量只看取材、拦不住"同一批画面配三段同义解说"。本任务把角度块接进两条成稿链。

**Files:**
- Modify: `service/dramaclip/engines/narration/copywriter.py:93-121`（`write_plan_copy` 的签名 + `user_prompt` 块）
- Modify: `service/dramaclip/engines/narration/scriptwriter.py:206-249`（`write_script_episodes` 的签名 + `user_prompt` 块）
- Modify: `service/dramaclip/engines/narration/script_driver.py:62-116`（`script_dialogue_plan` 整函数：签名 `:62-67`、docstring `:68-76`、`write_script_episodes(...)` 调用 `:94-102`）
- Modify: `service/dramaclip/api/narration.py:229-260`（临时补 `angle_block=""`，Task 6 整体重写）
- Modify: `service/tests/engines/narration/test_copywriter.py`、`test_scriptwriter.py`、`test_script_driver.py`、`test_script_episodes.py`

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

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_copywriter.py -q -k angle_block`

Expected: FAIL —— `TypeError: write_plan_copy() got an unexpected keyword argument 'angle_block'`

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_script_driver.py -q -k angle_block`

Expected: FAIL —— `TypeError: script_dialogue_plan() got an unexpected keyword argument 'angle_block'`

- [ ] **Step 3: `copywriter.write_plan_copy` 接角度块**

`service/dramaclip/engines/narration/copywriter.py`：

1. 签名整块替换（`angle_block` 与 `mode_label` 同为**必填**关键字，理由与 P-1.5 把 `mode_label` 定为必填一致：可省的卖点等于可省的差异化）：

```python
def write_plan_copy(
    plan: PlanData,
    asr_segments: list[AsrSegment],
    settings: dict[str, str],
    *,
    mode_label: str,
    angle_block: str,
    trace_dir: Path | None = None,
) -> PlanData:
    """填满 plan 的全部旁白槽位并置 planner=llm_script；任何不合格都抛异常。"""
```

2. `user_prompt` 整块替换（角度块紧跟模式行、在风格行之前——卖点是"写什么"，风格是"怎么写"，前者约束更强）：

```python
    user_prompt = (
        f"项目：{project_name}"
        + (f"（题材：{genre}）" if genre else "")
        + f"\n模式：{mode_label}"
        + angle_block
        + "\n文案槽位：\n"
        + _slot_block(plan.narration_texts, plan.timeline, asr_segments)
        + (f"\n\n解说风格要求：{directives}" if directives else "")
    )
```

3. 模块 docstring 末尾（`跨集剧本驱动（dialogue_narration）走 scriptwriter，两条链共享 FUNDAMENTALS。` 之后）补一行：

```python
卖点角度由 `angles.prompt_block` 措辞、经 `angle_block` 注入；单集链与跨集链共用那一段字。
```

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

`angle_block` 在三处都是必填，故所有调用点必须显式给值。先找齐：

Run: `cd service && grep -rn "write_plan_copy(\|write_script_episodes(\|script_dialogue_plan(" . --include=*.py`

Expected: 命中 `dramaclip/api/narration.py` 两处、`dramaclip/engines/narration/script_driver.py` 一处，以及 `tests/engines/narration/test_copywriter.py`、`test_scriptwriter.py`、`test_script_driver.py`、`test_script_episodes.py`。逐个补：

- `service/dramaclip/api/narration.py` 的 `copywriter.write_plan_copy(...)` 与 `script_driver.script_dialogue_plan(...)` 两处调用各加 `angle_block="",`，并在其上方加一行注释：

```python
        # Task 6 重写为按角度注入；此处的空串只在本任务与下一次提交之间存活。
```

- `service/tests/engines/narration/test_copywriter.py`：所有既有 `write_plan_copy(...)` 调用加 `angle_block=""`（Step 1 新增的两条传 `_ANGLE_BLOCK`）。
- `service/tests/engines/narration/test_scriptwriter.py`：`_run()` 助手加 `angle_block=""`。
- `service/tests/engines/narration/test_script_driver.py`、`test_script_episodes.py`：所有 `script_dialogue_plan(...)` 调用加 `angle_block=""`（Step 1 新增的那条除外）。
- `service/tests/api/test_produce.py`：`_FakeLlm.chat_json` 的槽位正则 `r"^\[([^\]]+)\] 要做的事："` 不受影响；若该文件有直接调 `write_plan_copy` 的用例，同法补 `angle_block=""`。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration tests/api -q`

Expected: PASS（`tests/api/test_analysis.py` 的既有隔离 flake 除外——它属另一位工程师，不修不碰）

- [ ] **Step 7: 变异检查**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `copywriter` 的 user_prompt 里删掉 `+ angle_block` | `test_angle_block_reaches_the_prompt` |
| 2 | `scriptwriter` 的 user_prompt 里删掉 `f"{angle_block}\n"` | `test_angle_block_is_forwarded_to_the_script_prompt` |
| 3 | `copywriter` 把 `angle_block` 挪到 `_slot_block(...)` 之后（塞进槽位块尾部） | **不红**——说明"角度块在 prompt 里的位置"不是被测行为。不必为此加用例：位置只影响模型注意力，不影响任何可观察输出，钉住它等于把测试写成实现的镜像 |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/engines/narration/test_copywriter.py tests/engines/narration/test_script_driver.py -q`

- [ ] **Step 8: 提交**

```bash
git add service/dramaclip/engines/narration/copywriter.py service/dramaclip/engines/narration/scriptwriter.py service/dramaclip/engines/narration/script_driver.py service/dramaclip/api/narration.py service/tests/engines/narration/test_copywriter.py service/tests/engines/narration/test_scriptwriter.py service/tests/engines/narration/test_script_driver.py service/tests/engines/narration/test_script_episodes.py service/tests/api/test_produce.py
git commit -m "feat(narration): 卖点角度注入两条成稿链，措辞由 angles.prompt_block 独家持有"
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

在 `service/tests/api/test_plan_variants.py` 里，`_seed_project_with_analysis` 之后新增多集种子（K 条角度需要多集才有互异取材可挑；单集种子上 K=3 会被重叠度量全拦掉——那是正确行为，但不是这些用例要验的）：

```python
def _seed_project_with_episodes(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    count: int,
) -> str:
    """建项目 + count 集，每集直种**时间区间互不相交**的分析数据，全部标 done。

    集与集的场景时间刻意错开（第 i 集从 100*i 秒起）：这样「两条角度取不同集」的
    取材重叠恒为 0，用例才不必去猜编排器会挑中哪几段。源文件是同一个 sample_video
    复制 count 份——本种子只服务规划路径，不渲染。
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
                single = "恰好一个集号" in user
                return {
                    "angles": [
                        {
                            "name": f"角度{i}",
                            "reason": f"第 {i} 集这条线最狠",
                            "hook": f"第 {i} 集的开场钩子",
                            "episode_numbers": [i] if single else [i, i + 1],
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    """全剧只分析完一集时，top-3 窗全落在第 1 集 → 按集去重后只剩 1 条。

    规格 §1 允许「每模式产出 **1..K** 条」，所以少出不是失败；但 §3.3 禁止静默：
    少出必须留痕，否则界面会把「这个模式只出了 1 条」显示成「这个模式本来就只能出 1 条」。
    本用例不需要任何 LLM/TTS 替身——规则类两个都不碰（上一条用例钉死了这一点）。
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
    assert len(plans) == 1, f"一集只能出一条规则类方案，实得 {len(plans)}"
    assert plans[0]["variant_index"] == 1
    assert plans[0]["overlap_max"] is None
    logged = [str(item) for item in harness.sent]
    assert any("top-3 冲突窗" in item and "1 集" in item for item in logged), (
        f"少出方案却没留痕（规格 §3.3）：{harness.sent}"
    )


def test_rejected_angle_does_not_pay_for_copy(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    sample_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7：同集角度的重叠闸门必须排在**成稿之前**，否则被拦的角度白付一次 LLM。

    可判定性是证明出来的、不是猜的：`_plan_one` 的非剧情解说分支里，角度只进
    `copywriter` 的 `angle_block`，**不进 `build_plan`**——
    `build_plan(mode, episode_id, conflicts, highlights, asr, audio, settings)`
    七个入参没有一个来自角度。故时间轴是 `(mode, episode_id)` 的纯函数，
    同集 ⇒ 同时间轴 ⇒ Jaccard = 1.0，成稿前就该判得出来。

    成稿调用数按 copywriter 的 system prompt 认（`_SYSTEM_PROMPT` 首句是
    「你是短剧推广解说编剧」），与选题（「选题操盘手」）、口味层（「风格库」）三者互不混淆。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    """`_pick_episode` 的兜底分支：点名集不在已完成集里就抛，绝不悄悄换一集顶上。

    这条用例是 Task 6 Step 10 变异 #10 的唯一守卫。没有它，把 `_pick_episode` 的
    raise 改成 `return episodes[0]` 全套照绿——而那正是「K 条其实是同一部片切 K 次」
    的根源之一（每条角度都被悄悄换成第 1 集）。
    """
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q -k "writes_k_plans or variant_failure or mode_failure or rule_mode or rejected_angle_does_not_pay or unknown_episode or post_copy or overlapping_angle or exclude_plan_ids or k_defaults or project_override or k_out_of_range or unknown_excluded or empty_modes"`

Expected: FAIL —— 16 条新用例（`k_out_of_range` 参数化 3 项，故实为 18 项）全红，两种形态：

- 走 `harness.rpc(...)` 的报 `AssertionError: narration.plan_variants RPC 错误: [-32601] 方法不存在`；
- 走 `harness.router.dispatch(...)` 的三条边界用例报 `assert -32601 == -32303`（或 `-32302`/`-32304`）——方法还没注册，拿到的自然是"方法不存在"。

**`-k` 里刻意不写 `plan_variants`**：Step 2 已把文件改名成 `test_plan_variants.py`，而 `-k` 是按**关键字子串**匹配的，模块名 `test_plan_variants` 含 `plan_variants` → 那样会**静默选中整个文件**，把 Task 9 Step 6 才迁移的旧 produce 用例一起拉进来，红的形态就分不清了。上面 14 个片段没有一个是 `test_plan_variants` 的子串。

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

2. import 区**整块替换**（不是"加两行"——那样 ruff 会报 I001，而 Step 9 的门禁写着"Expected: 无输出"）。实测：本仓 `.venv/Scripts/ruff.exe` 的 isort 要求 ① `from dataclasses import dataclass` 落在 stdlib 块里、`from typing import Any` **之前**（同块内 `import x` 先于 `from x import y`，且 dataclasses < typing）；② `angles`/`overlap` **合并进**既有的 `from dramaclip.engines.narration import …` 那一行（合并后 96 字符，未超 `line-length = 100`）；③ 带 `as` 别名的导入不合并，各自一行；④ `from dramaclip.infra import config` 排在 `from dramaclip.infra.storage.repos import …` 之前：

```python
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from dramaclip.api.context import AppContext
from dramaclip.engines.narration import angles, copywriter, overlap, script_driver, scriptwriter
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.narration import styles as styles_lib
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.semantic.models import ConflictScore, HighlightSegment
from dramaclip.infra import config
from dramaclip.infra.storage.repos import analysis as analysis_repo
from dramaclip.infra.storage.repos import episodes as episodes_repo
from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo
from dramaclip.transport.rpc import Router, RpcDomainError
```

（上面这块**不含第 1 点的 docstring**，从 `from __future__` 起接到 docstring 之后即可。与现状逐行对比，只动了三处：新增 `from dataclasses import dataclass`；`copywriter, script_driver, scriptwriter` 那行扩成 `angles, copywriter, overlap, script_driver, scriptwriter`；新增 `from dramaclip.infra import config`。**`from dramaclip.api.export import ExportRun, render_export` 与 `from dramaclip.infra.storage.repos import exports as exports_repo` 这两行在本点仍然保留**——`_run_produce` 还在用它们，第 12 点删函数时才一起删；提前删会让本步骤之后的树连 import 都过不去。）

3. 错误码常量区（`_ERR_MODE_UNSUPPORTED` 之后）加：

```python
_ERR_VARIANTS_OUT_OF_RANGE = -32303
_ERR_PLAN_NOT_FOUND = -32304
```

4. 模式集合区（`_NARRATION_MODES` 之后）加：

```python
# 只有剧情解说能在一条方案里跨集取画面（pipeline.build_from_script_episodes 按集号取素材）；
# 其余模式的编排器签名是 (episode_id, scenes, strategy)，一条片只吃一集。
# 于是本批次让**角度之间**跨集（不同角度取不同集，K 条合起来覆盖全剧），
# 单条方案内的跨集拼接归 P-2c（见计划《定案二》末段，那里同时记了它须业主签字）。
_CROSS_EPISODE_MODES = frozenset({"dialogue_narration"})

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
    """成稿**之前**的重叠闸门（R7）：同模式同集的两条角度，取材必然逐秒相同。

    这不是启发式，是可证的：`_plan_one` 的非剧情解说分支里，`variant` 只进
    `copywriter` 的 `angle_block`，**不进 `build_plan`**——
    `build_plan(mode, episode_id, conflicts, highlights, asr, audio, settings)` 的
    七个入参没有一个来自角度。故时间轴是 `(mode, episode_id)` 的纯函数：
    同集 ⇒ 同时间轴 ⇒ Jaccard = 1.0，必然超过 60% 阈值。

    既然成稿前就可判，就不该先付一次 LLM 成稿再拦：被拦的角度不落库，
    那笔钱在 narration_plans 里也无从重算（《定案二》的 R7 段）。

    `dialogue_narration` 走不到这里（它在 `_CROSS_EPISODE_MODES` 里，且剧本由模型
    按角度现写、成稿前无从判定），那条残余由成稿后的 `_worst_overlap` 兜住——
    `test_post_copy_overlap_gate_still_guards_cross_episode_modes` 钉住那道兜底没被拆掉。
    """
    if mode in _CROSS_EPISODE_MODES:
        return
    wanted = frozenset(variant.episode_numbers)
    for index, (sibling, _plan) in enumerate(accepted, start=1):
        if frozenset(sibling.episode_numbers) == wanted:
            raise ValueError(
                f"取材与「{_slot_label(sibling, index)}」重叠 100%，"
                f"超过 {overlap.OVERLAP_LIMIT:.0%}"
                "——同模式同集的两条角度取材逐秒相同，这条角度不出（规格 §4.3）"
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
    """
    briefs = angles.select_angles(
        mode,
        mode_label=label,
        k=k,
        episode_inputs=episode_inputs,
        settings=settings,
        cross_episode=mode in _CROSS_EPISODE_MODES,
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
    """规则类（raw_clip / subtitle_flow）：全剧 top-K 冲突窗 → 按集去重 → 一集一条。

    规格 §4.3 ④「规则类 = 全剧 top-K 冲突窗（两者不同源，已由用户定案）」、
    §4.2「仅「纯原片剪辑」「字幕金句流」不依赖 LLM」。
    **本函数不发任何网络请求**：把它们拖进 `angles.select_angles` 就等于把
    "不依赖 LLM"改成"依赖 LLM"，而 select_angles 对未配置抛 LlmUnavailable——
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
    windows = narration_pipeline.top_conflict_windows(scored, k)
    if not windows:
        raise ValueError(f"{label}：全剧没有任何带冲突分的场景，无从取窗")
    if len(windows) < k:
        # 规格 §1 允许「每模式产出 1..K 条」，但 §3.3 禁止静默：少出必须留痕，
        # 否则界面会把「这个模式只出了 N 条」显示成「这个模式本来就只能出 N 条」。
        context.notifier.log(
            "info",
            f"{label}：全剧 top-{k} 冲突窗按集去重后只落在 {len(windows)} 集，"
            f"本模式出 {len(windows)} 条（规格 §1 的 1..K 条）",
        )
    if rerolled:
        # 窗口榜是确定性的，且规则类的 angle 是空串（贡献不出排除项）：
        # 「重掷此条」对规则类必然原样再出同一条方案。如实说出来，别让用户以为生效了。
        context.notifier.log(
            "info",
            f"{label}：规则类方案由全剧冲突榜确定性推导，「重掷此条」不会改变结果；"
            "要换方案请改方案数或补素材（《定案四》）",
        )
    for rank, (number, scene) in enumerate(windows, start=1):
        context.notifier.log(
            "info",
            f"{label}·第 {rank} 条：第 {number} 集 {scene.start:.0f}-{scene.end:.0f}s、"
            f"冲突分 {scene.score}（全剧冲突榜，不经选题模型）",
        )
    return [
        _Variant(name="", reason="", episode_numbers=[number], angle_block="")
        for number, _scene in windows
    ]


def _plan_one(
    context: AppContext,
    mode: str,
    episodes: list[dict[str, Any]],
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    variant: _Variant,
) -> tuple[PlanData, list[str]]:
    """按取材意图产出一条方案（未配音、未落库）。

    取材集由意图决定，不再恒取 episodes[0]——那是「K 条其实是同一部片切 K 次」的
    根源之一。返回 (方案, 用到的集 id)。

    **不落库**：`plans_repo.create` 只在 runner 里发生一次，那里才有 batch_id /
    variant_index / overlap_max 三个只有 runner 知道的值。
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

    episode = _pick_episode(episodes, variant)
    record = analysis_repo.get(context.conn, str(episode["id"]))
    if record is None:
        raise ValueError(f"第 {episode['episode_number']} 集分析记录缺失")
    asr_segments = narration_pipeline.parse_asr_segments(record["asr_segments"])
    plan = narration_pipeline.build_plan(
        mode,
        str(episode["id"]),
        _parse_conflicts(record["conflict_scores"]),
        _parse_highlights(record["highlights"]),
        asr_segments,
        narration_pipeline.parse_audio_features(record["audio_features"]),
        settings,
    )
    if not plan.timeline:
        # 空时间轴的方案渲染出来是一部 0 秒的片；规划期就该说清楚，不留到导出
        raise ValueError(f"第 {episode['episode_number']} 集没有可用素材，这条角度出不了片")
    if plan.narration_texts:
        # 规则类两个模式走不到这里（它们的编排器不产槽位），故 angle_block 恒为空串
        # 也不会被任何人读到——这不是"悄悄留了个空值"，是两族的会合点本来就用不上它。
        plan = copywriter.write_plan_copy(
            plan,
            asr_segments,
            settings,
            mode_label=narration_pipeline.MODE_LABELS.get(mode, mode),
            angle_block=variant.angle_block,
            trace_dir=trace_dir,
        )
    return plan, [str(episode["id"])]


def _pick_episode(
    episodes: list[dict[str, Any]], variant: _Variant
) -> dict[str, Any]:
    """意图点名的那一集。点名集不在已完成集里就抛——绝不悄悄换一集顶上。"""
    wanted = set(variant.episode_numbers)
    for episode in episodes:
        if int(episode["episode_number"]) in wanted:
            return episode
    raise ValueError(f"取材集 {sorted(wanted)} 不在已完成分析的集里")
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

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q -k "writes_k_plans or variant_failure or mode_failure or rule_mode or rejected_angle_does_not_pay or unknown_episode or post_copy or overlapping_angle or exclude_plan_ids or k_defaults or project_override or k_out_of_range or unknown_excluded or empty_modes or cancel_releases"`

Expected: PASS（**16 条新增用例、18 个参数化项**：Step 3 原有的 11 条 + 本轮为 B2/R1 与 R7 新增的 5 条 `rule_modes_never_construct_an_llm_client` / `rule_mode_yields_fewer_than_k_and_leaves_a_trace` / `rejected_angle_does_not_pay_for_copy` / `unknown_episode_in_a_brief_fails_only_that_variant` / `post_copy_overlap_gate_still_guards_cross_episode_modes`）。`-k` 的片段选择理由见 Step 4。

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
| 10 | `_pick_episode` 的 `raise` 改成 `return episodes[0]` | `test_unknown_episode_in_a_brief_fails_only_that_variant`（Step 3 已给出完整代码；原计划这里写的是"补一条"，那是本计划自己禁止的占位符） |
| **11** | **`_run_plan_variants` 里的 `if mode in _NARRATION_MODES:` 分流删掉，改成无条件调 `_angle_variants`** | **`test_rule_modes_never_construct_an_llm_client`（替身在 `__init__` 里就炸，所以红得干脆）。这是 B2/R1 的主守卫：它红，说明"仅两个纯剪辑模式不依赖 LLM"这条用户定案被推翻了** |
| 12 | `_rule_variants` 的 `if len(windows) < k:` 那段 `notifier.log` 整块删掉 | `test_rule_mode_yields_fewer_than_k_and_leaves_a_trace`（留痕断言）。少出方案本身仍然合法（规格 §1 的 1..K），红的是**静默** |
| 13 | `_reject_same_episode_sibling` 的第一行改成 `if True: return`（即前置闸门失效） | `test_rejected_angle_does_not_pay_for_copy`（成稿次数 1 → 3）。**`test_overlapping_angle_is_dropped_not_stored` 不会红**——成稿后那道闸门会顶包，方案照样不落库；差别只在"有没有白付两次成稿"，而那正是 R7 要修的 |
| 14 | `_reject_same_episode_sibling` 的 `if mode in _CROSS_EPISODE_MODES: return` 整块删掉 | **本文件不红**——`dialogue_narration` 的端到端规划路径在本批次**没有自动化覆盖**（要真 LLM 写剧本，或给 `script_driver` 造一个能产出可控跨集时间轴的替身）。它由九模式真机门禁覆盖，而 Task 11 Step 3 原先只跑 `full_narration`，故本轮补了 **Step 3b：加跑一次 `dialogue_narration`**。**不要为了"让这条变异能红"而给跨集模式造一个假剧本替身**——那会钉住替身的形状而不是产品的行为 |
| 15 | `_rule_variants` 的 `if rerolled:` 那段 `notifier.log` 整块删掉 | **本文件不红**：没有用例断言这条留痕（它只在"重掷一条规则类方案"时出现，而那条路径要 P-2.5 的阶段③ 才有入口）。**记在《已知不做》**，等阶段③ 落地时补用例；此处保留代码是因为 §3.3 禁止静默，而不是因为测到了 |

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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
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

Expected: PASS（4 条）

- [ ] **Step 3: 变异检查**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `plan_cost` 的 `1 if voiced else 0` 改成 `1` | `test_get_plan_of_a_silent_mode_costs_no_llm_call`（`copy_llm_calls` 0 → 1） |
| 2 | `plan_cost` 的 `tts_calls` 改成 `len(plan.timeline)` | `test_get_plan_returns_row_and_cost`（`tts_calls` 1 → **3**，因为 `intro_narration` 是 3 段 1 槽）。**在原来的 `full_narration` 夹具上这条变异红不了**：`build_full` 每槽恰好一段 `ducked`，两个数恒等（B6） |
| 3 | `get_plan` 的 `if row is None: raise` 改成 `return {"plan": {}, "cost": {}}` | `test_get_plan_unknown_id_raises` |
| 4 | `list_plans` 的 `if batch_id is not None` 分支整块删掉 | `test_list_plans_can_filter_by_batch` |

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

本文件钉三件事：① 一条方案一个 export job（取消/重试的粒度必须是单条片）；
② 拒绝路径逐条给理由，而不是一整批一起炸；③ 可渲染性守卫——规划与渲染拆开后，
render_export 只读库里的 plan_data、自己不做任何配音，一版没配音的方案会被
静默渲成哑片（规格 §3.3.1 禁止级）。守卫由 submit 与 retry 共用，两处必须同形。
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
            memory_db, project_id, plan_data.mode, ["ep1"], plan_data.model_dump(),
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

Expected: FAIL —— 多数报 `AssertionError: export.submit RPC 错误: [-32601] 方法不存在`

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

Expected: PASS。`test_export_retry.py` 的既有夹具用的是 `raw_clip` + 无 `narration_texts`（`tests/api/test_export_retry.py:41-45`），守卫对它是空转，故不受影响。

- [ ] **Step 8: 变异检查**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `submit` 的 `list(dict.fromkeys(...))` 改成 `list(raw)` | `test_submit_dedupes_plan_ids_within_one_call` |
| 2 | `_assert_renderable` 的 `if not audio_path: raise` 整块删掉 | `test_submit_rejects_an_unvoiced_narration_plan` |
| 3 | `_assert_renderable` 的 `if not Path(audio_path).is_file(): raise` 整块删掉 | `test_submit_rejects_a_plan_whose_audio_file_is_gone` |
| 4 | `_assert_renderable` 的 `if plan_row["status"] != "ready"` 整块删掉 | `test_submit_rejects_a_plan_that_is_not_ready` |
| 5 | `_assert_renderable` 的 `if not plan_data.timeline` 整块删掉 | `test_submit_rejects_an_empty_timeline` |
| 6 | `_assert_renderable` 的 `if segment.audio not in ("narration", "ducked"): continue` 改成只认 `"narration"` | 本文件不红——**ducked 段无音频这条路径缺一条专属用例**。补一条：把 `_voiced_plan` 的 `audio="ducked"` 保留、`narration_texts` 清空、`timeline` 的 `narration_id` 保留，断言 `rejected[0]["reason"]` 含「没有配音音频」，再对本条变异重跑 |
| 7 | `retry` 里新插入的 `_assert_renderable(plan_row, plan_data)` 删掉 | `test_retry_shares_the_renderability_guard` |
| 8 | `retry` 里把 `_assert_renderable` 挪到 `reset_for_retry` **之后** | 同上用例的后半段断言（`status` 仍是 `failed`） |
| 9 | `if not isinstance(raw, list) or not raw: raise` 整块删掉 | `test_bad_plan_ids_are_rejected_at_the_rpc_boundary` |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_export_submit.py -q`

- [ ] **Step 9: 暂存（不提交，提交在 Task 9）**

```bash
git add service/dramaclip/api/export.py protocol/schemas/export.json protocol/ts/index.ts desktop/src/services/client.ts service/tests/api/test_export_submit.py
```

---

## Task 9: 删 `produce` / `generate_plans`，迁门禁与前端调用点

规格 §6 说的是「**拆** `produce`」，不是"在旁边加两个新方法"。留着的理由只有一个（既有页面还能跑），而那个理由由 Step 4 的一次最小改写满足，不需要留方法。规格 §2.2 定案「一次性切换，不做新旧并存灰度」，docs/04 §5.2 禁止同一概念双处定义。

**Files:**
- Modify: `scripts/verify_modes.py`（**五处**：`:39` 的 import 区、`:75-85` 的 `EXPECT_PLANNER` 推导散文、`:351-356` 的 argparse 参数区、`:382` 的 `_generate_one` 注释、`:438-441` 之后插前置条件停机分支、`:456-500` 的模式循环与派发段）
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

这一步有**五个**改动点，缺任何一个门禁都会假红或假绿。逐点做，做完再跑 Step 3。

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

原 8 行（实测 `:459-465`，紧接上面那段 Router 装配）：

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
        plan_ids = [str(r[0]) for r in ctx.conn.execute(
            "select id from narration_plans where batch_id=?"
            " order by narration_mode, variant_index",
            (str(resp.result["batch_id"]),)).fetchall()]
        if args.plan_only:
            # --plan-only 的判据是**查库**，不是"门禁报没有成品"：把失败当证据是假绿的一种。
            # 这个 batch 的方案一行 export_jobs 都没有，才叫"规划阶段一条片都没渲"。
            rec = {"mode": mode, "status": job["status"], "phase": "plan-only",
                   "elapsed_s": round(time.time() - started, 1), "plans": len(plan_ids)}
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

**2.3 argparse 加两个旗标**

参数区在 `main()` 开头（实测 `:351-356`），变量名是 **`ap`**（`ap = argparse.ArgumentParser()`），**不是 `parser`**——原计划写的是 `parser.add_argument(...)`，照抄会 `NameError`。在 `ap.add_argument("--job-timeout", …)` 之后加：

```python
    ap.add_argument("--variants", type=int, default=1,
                    help="每模式规划几条方案（P-2a 的 K）。门禁默认 1，与九模式口径一致")
    ap.add_argument("--plan-only", action="store_true",
                    help="只规划、不提交渲染，并查库断言该 batch 的 export_jobs 为 0"
                         "（P-2a Task 11 Step 1 用它证明「规划阶段一条片都没渲」）")
```

**2.4 前置条件停机分支（B11）**

`done` 计数的那句打印（实测 `:438-441`，`print(f"项目 {project_id[:8]} · 已分析 {done} 集 · …")`）**之后**插入：

```python
    # 前置条件：--variants K 需要至少 K 集已分析。门禁自己不分析任何东西，
    # 它读的是复制来的 data/data.db 里现成的东西，所以这一条必须显式设卡。
    if done < args.variants:
        print(f"环境未就绪：--variants {args.variants} 需要至少 {args.variants} 集已分析，"
              f"库里只有 {done} 集。", file=sys.stderr)
        print("解说类模式一条片只取一集（dialogue_narration 除外），集数不足时 K 条角度会"
              "全部指向同一集 → 取材重叠 100% → 第 2..K 条被重叠闸门拦下 → 作业 failed。"
              "那时看到的红不是产品坏了，是门禁的前提没满足。", file=sys.stderr)
        print(f"要么先把集数分析到 ≥ {args.variants}，要么把 --variants 降到 1"
              "（九模式门禁的默认口径）。", file=sys.stderr)
        return 2
```

（退出码 **2** = "环境未就绪"，与本文件开头 docstring 里那两档的划分一致：0=通过、1=断言失败、2=环境未就绪。用 1 会把"库里没有足够的集"报成"产品有缺陷"。）

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

**2.6 表格打印：让 `--plan-only` 的证据可见**

打印循环里 `if r.get("audio_roles"):` 那两行（实测 `:640-641`）**之后**插入：

```python
        if r.get("phase") == "plan-only":
            print(f"{'':<29}规划 {r.get('plans', 0)} 条 · 建了 "
                  f"{r.get('export_jobs', 0)} 行 export_jobs（必须为 0）")
```

（不加这一段，`--plan-only` 跑完只在 `summary.json` 里有数，终端表格里看不出来——而 Task 11 Step 1 的判据正是要**看见** `plans=3`、`export_jobs=0`。）

**2.7 保持不动的部分**

`export_jobs` 的成品定位查询（实测 `:482-484`）一字不动：它取"最新一条已完成出片记录"并校验 `narration_mode` 对得上，两步派发之后这个语义不变（`--variants 1` 时一个模式恰好一条成品）。`_mode_table_drift()`、响度窗口、planner 断言、冻结帧断言全部不动——**这是"渲染侧一行未改"的门禁证据，动它就等于把证据本身改了**。

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
git add docs/03-IPC协议规范.md docs/service/01-传输与API层设计.md docs/service/04-数据模型.md docs/superpowers/plans/2026-09-12-p2-plan-render-split.md
git commit -m "docs: 方法清单/错误码/迁移登记随 produce 拆分收口，并登记 tts_segments 死列"
```

---

## Task 11: 真机复验（P-2a 出口）

不产新代码，只产证据。**先决条件：P-1.5 Task 10 的九模式门禁已闭环、机器上没有别的门禁在跑**（本任务要真跑 LLM 与 ffmpeg，CPU 争用会让两边的时序断言都不可信）。

- [ ] **Step 1: 只跑规划，确认"不渲染"是真的**

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe scripts/verify_modes.py --modes full_narration --variants 3 --plan-only --out D:/tmp/dc-p2a-plan > /tmp/p2a-plan.log 2>&1; echo REAL_EXIT=$?`

Expected: **`REAL_EXIT=0`**，日志末尾的表格里 `状态=completed`，紧跟着一行附注 `规划 3 条 · 建了 0 行 export_jobs（必须为 0）`；`/tmp/p2a-plan.log` 里能看到 3 条角度的规划留痕（`全片解说·第 1 条 …` 这类 `notifier` 行不进日志，看 `summary.json`）。

**原计划这一步的 Expected 是虚构的（B10）**：它期望门禁"因为只规划不渲染而报没有成品"，可 Task 9 Step 2 的改写让门禁**总是**提交渲染，于是 `--variants 3` 跑完会真渲三部片、`REAL_EXIT=0`，什么都证不了。修法不是改期望文字，是给门禁加 `--plan-only`（Task 9 Step 2.2/2.3）：规划完就 `continue`，并**查库断言该 batch 的方案一行 `export_jobs` 都没有**。把失败当证据是假绿的一种；查库得到的 0 才是证据。

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe -c "import json,pathlib;rows=json.loads(pathlib.Path('D:/tmp/dc-p2a-plan/summary.json').read_text(encoding='utf-8'));print([{k:r.get(k) for k in ('mode','status','phase','plans','export_jobs')} for r in rows])"`

Expected: `[{'mode': 'full_narration', 'status': 'completed', 'phase': 'plan-only', 'plans': 3, 'export_jobs': 0}]`。**`plans` 必须是 3、`export_jobs` 必须是 0**：`plans < 3` 说明有角度被重叠闸门拦了（回去看 Step 2 的集数前提），`export_jobs > 0` 说明 `--plan-only` 没接住提交，两者都是真缺陷。

**不要用 `| tail` 判退出码**（管道退出码是 `tail` 的，P-1.5 真踩过）。

- [ ] **Step 2: 人工核三条角度真的互异**

**先确认前提**：本步骤期望"三条角度取三集、重叠近 0"，那要求隔离副本库里**至少有 3 集 `status='done'`**。门禁自己不分析任何东西，它读的是复制来的 `data/data.db` 里现成的东西。Task 9 Step 2.4 已为此加了停机分支（`done < --variants` → 打印原因 → `return 2`），所以：

Run: `grep -E "已分析|环境未就绪" /tmp/p2a-plan.log | head -3`

Expected: 一行 `项目 xxxxxxxx · 已分析 N 集 · …` 且 **N ≥ 3**（审查时实测活库是 **10 集**，故正常情况满足）。若看到 `环境未就绪：--variants 3 需要至少 3 集已分析`、`REAL_EXIT=2`，那不是产品坏了——先把集数分析够，或退而用 `--variants 1` 只验 Step 3。**不要为了让 Step 1 过而把 `--variants` 悄悄降到 1**：那样 `plans=3` 那条判据就自动失效了，本步骤要验的正是"K 条真的互异"。

集数够，才继续下面两条。

Run: `ls -dt tmp_dc-verify-data_*/logs/llm/llm_angles_*.json 2>/dev/null | head -1`

Expected: 打印出一个路径，形如 `tmp_dc-verify-data_xxxxxxxx/logs/llm/llm_angles_full_narration_0912_183041.json`。**若为空就是选题层没被调用**，停下排查，不要继续本步骤后面的断言。

（拿到路径后）Run: `.venv/Scripts/python.exe -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));print(d['user'][:1500]);print('---');print(json.dumps(d['attempts'][-1],ensure_ascii=False)[:1200])" <上一步的路径>`

Expected: prompt 里有「需要 3 条卖点互异的取材角度」、「恰好一个集号」、跨集转写摘录；`attempts` 末项里有 3 条 `name` 互不相同、`episode_numbers` 互不相同的角度。

**若一个 `llm_angles_*` 都没有，说明选题层根本没被调用，别往下走**——那比任何后续数字都严重（与 P-1.5 Task 10 Step 2 对 `llm_copy_*` 的判据同理）。

再从隔离副本库里读落库的角度与重叠（**副本，不是 `data/data.db`**）：

Run: `.venv/Scripts/python.exe -c "import sqlite3,glob,sys;p=sorted(glob.glob('tmp_dc-verify-data_*/*.db'))+sorted(glob.glob('tmp_dc-verify-data_*/data.db'));print(p);c=sqlite3.connect(p[0]);print(c.execute('select variant_index,angle,overlap_max,episode_ids from narration_plans order by variant_index').fetchall())"`

Expected: 3 行，`angle` 三个不同名字，首行 `overlap_max` 为 `None`，其余两行为接近 0 的小数（三集互异取材）。**若三行 `overlap_max` 都是 0.0，说明首条被误当成"比过且不重叠"，回去查 `_worst_overlap` 的 None 分支。**

- [ ] **Step 3: 规划 + 提交两步都跑通，出一条真片**

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe scripts/verify_modes.py --modes full_narration --variants 1 --out D:/tmp/dc-p2a > /tmp/p2a-gate.log 2>&1; echo REAL_EXIT=$?`

Expected: `REAL_EXIT=0`，表格里 `planner=llm_script`、`LUFS` 落在目标 ±2.5、`峰dB` 在门限内、`max_freeze_s < 2`。**这一步同时证明渲染侧一行未改**：P-1.5 的响度与 planner 判据在拆分之后仍然成立。

耗时提示：LLM 选题 1 次 + 成稿 1 次 + TTS 若干 + 渲染，单集素材约 5-10 分钟；用 `run_in_background`，不要中途判死。

- [ ] **Step 3b: 加跑一次跨集模式与一个规则模式（本轮新增，补两处覆盖缺口）**

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe scripts/verify_modes.py --modes dialogue_narration,raw_clip --variants 1 --out D:/tmp/dc-p2a-cross > /tmp/p2a-cross.log 2>&1; echo REAL_EXIT=$?`

Expected: `REAL_EXIT=0`，表格里两行都 `状态=completed`，且：

- `dialogue_narration` 的 `来源=llm_script`、响度落在窗口内。这是**跨集规划路径唯一的端到端证据**：Task 6 Step 10 的变异 #14（删掉 `_reject_same_episode_sibling` 对 `_CROSS_EPISODE_MODES` 的豁免）在单元测试里红不了，因为本批次没有 `dialogue_narration` 的端到端用例（要真 LLM 写剧本，或造一个能产出可控跨集时间轴的替身——后者会钉住替身的形状而不是产品的行为）。**这一跑就是它的替代证据**，别省。
- `raw_clip` 的 `来源=rule`、`TTS=0`、`带旁白=0`。这是**规则类没被拖进 LLM** 的真机证据（《定案四》第 5 点）：`EXPECT_PLANNER["raw_clip"] == "rule"` 是门禁自己钉的，若规划侧把 `raw_clip` 送进了成稿链，这一行会当场红。顺带它也在真数据上跑通了 `top_conflict_windows` → `_rule_variants` → `_plan_one` 这条新链路。

耗时提示：`dialogue_narration` 的编剧链比单集成稿慢（跨集转写摘录 + 一次剧本往返），加渲染约 10-20 分钟；`raw_clip` 很快。整条命令用 `run_in_background`。

**若 `dialogue_narration` 因"取材集都没有转写"或剧本不合格而 failed**：那是 P-1.5 已知的编剧链行为（禁止降级，拿不到合格剧本就抛），不是 P-2a 引入的回归。判据是看 `/tmp/p2a-cross.log` 里的失败原因串——含「选题」/「剧本」字样属上游，含 `-32601` / `不可渲染` / `没有配音音频` 才是本批次的问题。

- [ ] **Step 4: 用耳朵验收一条（不可省略）**

至少人工听 Step 3 出的那条 `full_narration`，确认：① 旁白没有被原声盖住；② 没有因 `normalize=0` 带来的爆音；③ **解说内容与角度名对得上**（这是本批次唯一能靠耳朵验的东西——重叠率是数字，"这条片是不是在讲它宣称的那个卖点"只能听）。

把结论写进 Step 5 的记录里——**写"已听，结论 X"，不接受"断言全绿所以应该没问题"**。

- [ ] **Step 5: 把实测写回本计划并清理临时目录**

在本文档末尾追加 `## Task N 落地后的实测修正` 小节（与 P-1.5 同一体例），记录：三条角度的实测名字与 `overlap_max`、选题 prompt 的实际形态、Step 1 的 `plans`/`export_jobs` 实测值、Step 3b 里 `dialogue_narration` 与 `raw_clip` 的 `来源`/`TTS`/`带旁白` 三列实测值、与预期不符之处、以及计划里被证伪的假设（如有）。**Task 9 Step 1b 要求移交的 `scripts/verify_e2e.mjs` 两处失效派发也记在这里**（文件、行号、旧方法名、新调用形态、属主名字）——那是给下一个人看的，不是给本批次验收用的。

清理。临时目录由 `_same_drive_temp` 创建，**首选 `dir=REPO`，所以它们落在仓库根**。其中 `tmp_dc-verify-data_*` 里有一个名为 `models` 的目录联接指向真实的 `data/models`——**顺序不可颠倒**：先 `rmdir` 摘掉联接，再 `rm -rf` 目录；反过来会顺着联接删掉开发者的模型。

```bash
cd /d/PersonProjects/DramaClip
for d in tmp_dc-verify-data_*; do cmd //c "rmdir $(cygpath -w "$PWD/$d/models")" 2>/dev/null || true; done
rm -rf tmp_dc-verify-data_* tmp_dc-verify_* D:/tmp/dc-p2a D:/tmp/dc-p2a-plan D:/tmp/dc-p2a-cross
ls data/models/tts/kokoro/*/ | head -3   # 必须仍在：联接被删过一次就再也没有了
```

若最后一条 `ls` 为空，立刻停下并报出来——那说明联接连同模型被误删，需要从备份或重新下载恢复，不要继续提交。

- [ ] **Step 6: 提交**

```bash
git add docs/superpowers/plans/2026-09-12-p2-plan-render-split.md
git commit -m "docs(plan): 记录 P-2a 真机复验结果与实测修正"
```

---

## P-2b / P-2c 交接规格

本计划只交付规格 §6 的 P-2 五项里的前三项。后两项与一项被本批次显式收窄的工作，按下面的边界各自成计划。**这里给的是边界与已知陷阱，不是任务步骤**——步骤由各自的 writing-plans 轮次产出。

### P-2b：剧库（规格 §6 的 P-2 第 ④⑤ 项）

**出口**：批量建项目与阶段定位可用。

**内容**：

1. `project.batch_create`（规格 §5 #4）：一次多个目录 → 一部剧一个项目，剧名默认取文件夹名。已知陷阱：`projects.source_path` 是 `TEXT NOT NULL UNIQUE`（`migrations/001_init.sql:7`），同一目录选两次会撞唯一约束——必须逐目录给结果（成功/已存在/目录不存在/目录里没有视频），不许一整批炸掉，形态与 `export.submit` 的 `{exports, rejected}` 同构。建项目之后是否顺带 `scan_episodes` 要定案：`scan_episodes` 逐文件跑 ffprobe，35 部剧 × 80 集会让这个 RPC 阻塞几分钟，故应做成 job 而不是同步返回。
2. `project.list` 阶段聚合（规格 §5 #3/#5）：每部剧回四阶段状态（§3.1 的四态：未开始/进行中/完成/已过期）+ 卡点文案 + `current`（卡片点击直跳）。已知陷阱：**`jobs.ref_id` 的语义按 job 类型而变**——`prescreen`/`analysis`/`narration` 是 project_id，`semantic` 是 episode_id（`api/analysis.py:223`），`export` 是 **export_id**（`api/export.py:79`），`model_download` 是 model_id。所以"这部剧有没有在跑的出片作业"必须经 `export_jobs` 联查，不能直接按 ref_id 过滤 jobs。规模：§9 验收 7 要求 50 部剧下不卡，故聚合必须是 SQL 而不是 N+1 的 Python 循环（`projects_repo.list_all` 现在的 `episode_count` 已经是 JOIN + GROUP BY，照那个形态扩）。
3. 「已过期」判据（§3.1）：`episode_analysis.analyzed_at` 的最大值 vs `narration_plans.created_at` 的最大值。P-2a 之后还要多判一层：**同 batch 内最新的方案**才算数，否则一次重掷会让整阶段显示过期。

**冲突面（必须等 P-2a 合入再开工）**：`protocol/ts/index.ts`（`METHOD_NAMES` 与 `Project` 类型）、`protocol/schemas/project.json`、`docs/03-IPC协议规范.md` §5.2/§6、`docs/service/01-传输与API层设计.md` §4/§6、`docs/service/04-数据模型.md` §4 迁移清单、`desktop/src/services/client.ts` 的 `projectApi`。**迁移号用 `011`**（P-2a 占了 `010`）；若 P-2b 其实不需要新列（阶段聚合是纯查询），就不要建迁移。

### P-2c：单条方案内的跨集拼接（**开工前须业主先回答《开放问题》#1**）

> ⚠️ **P-2c 是否必须存在，取决于业主对规格 §1 那句"跨集方案"的读法（R2）。**
> 若业主认定 §1 的"跨集"只要求"K 条合起来覆盖全剧"，那么 P-2a 已经交付了它，P-2c 降格为一次可选的成质量优化；
> 若业主认定"每条方案自己就要跨集取画面"，那么 **P-2a 的出口判据是不完整的**，P-2c 是补完规格所必需、且必须排在 P-1.5 出口闭环之后。
> **在拿到这个答复之前，不要把 P-2c 写成"已计划推迟"，也不要拿本节的收窄当既成事实。**

P-2a 让**角度之间**跨集（不同角度取不同集），但六个单集模式的**单条方案内**仍限于一集，因为它们的编排器签名是 `(episode_id, scenes, strategy)`。要真正做到"一条片跨集取画面"，得让 `ConflictScore` 带上集身份、或让编排器接受"每集一组场景"，并重新分配时长预算（`_fit_duration` 现在按 `strategy.max_duration_s` 截断单集场景，多集直接叠加会超预算数倍）。

**同一个前置也卡着《定案四》的后半句**：规则类两模式今天只能做到"用全剧 top-K 冲突窗决定**条数与取材集**"，做不到"每条方案的内容就是它那一窗"——因为 `build_raw_clip`/`build_subtitle_flow` 是 `(episode_id, 该集场景表)` 的确定性纯函数，喂同一集必得同一片。P-2c 给 `ConflictScore` 加集身份之后，这一半也才做得成。两件事是同一个改动，应排在同一份计划里。

**为什么不在 P-2a 里做**：它改成片形态，而九模式真机门禁的出口判据（时长窗、响度窗、冻结帧）正压在这个形态上。P-1.5 Task 10 尚未闭环时改成片结构，等于把两批的验收证据混在一起，出问题时无法归因。**P-2c 必须在 P-1.5 出口闭环之后、且自己带一轮九模式门禁。**

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
4. Task 11 Step 3 的真机门禁 `REAL_EXIT=0`，且 `planner=llm_script`、响度落在窗口内——**这是"渲染侧一行未改"的证据**。
5. Task 11 Step 2 的实测记录已写回本文件：三条角度名互异、`overlap_max` 首条为 `None`、其余接近 0。
6. `grep -rn "generate_plans\|_run_generation_parallel\|_generate_one\|_newest_ready_plan\|_run_produce\|narration.produce\|export.start" service/dramaclip desktop/src protocol scripts --include=*.py --include=*.ts --include=*.tsx --include=*.json` **无输出**——旧入口一个不剩。
7. `export.submit` 对一个已规划好的 batch 提交后，`export_jobs` 行数等于该 batch 的方案行数（一条方案一行），且每行都有对应的 `jobs` 行（`type='export'`、`ref_id=export_id`）。
8. 本计划里每一张变异检查表都逐条跑过并逐条按字节还原。

## 已知不做 / 不在本批

- **队列页、K 条角度出片、成本预估卡**：规格 §6 的 P-2.5。本批次只把数据准备好（`batch_id`/`variant_index`/`overlap_max`/`plan_cost`），不建页面。
- **成品自检四项、`export.set_cover`**：P-3。
- **`tools.*` 工具箱**：规格 §6 建议的独立小批次，与本批次无交集。
- **画面通道 / `subtitle_probe` / `vision` 域**：规格 §10，批次 2。
- **`serial_per_episode`（连载模式开关，规格 §5 #21）**：**规格自相矛盾**——§5 #21 把它挂在 `plan_variants` 上，§4.3 ④ 又说它是"提交时参数，不写入 `project.settings`"。两处不可能同时对。本批次不实现，等这个矛盾被裁决；若最终归规划侧，它的语义是"每集各出一条方案"，会让方案数变成 `集数 × 模式数`（80 集 × 9 模式 = 720 条），**没有队列页根本不可用**，故它天然属于 P-2.5 而不是 P-2a。
- **渲染侧的项目级覆盖**（字幕预设、输出四键、响度目标）：`render_export` 仍直接读 `context.settings`。P-2a 只把 K 与风格接上了项目覆盖（那是 `plan_variants` 自己的入参）。接线归 P-3 的包装区。
- **阶段③ 如何把"重掷的单条"并回 K 条一组显示**：P-2a 保证方案行只追加、`batch_id` 齐全，任何并法都可行；具体并法是 P-3 的展示决策。
- **`narration_plans.tts_segments` 死列**：已在 `docs/service/04` 登记为死列，不在本批删除（理由见 Task 10 Step 4）。
- **配音音频的磁盘回收**：定案一把 `work_dir/tts/<job>/…` 变成承重存储，它只增不减。回收归 P-3 的「关于 → 本地数据」与回收站。

---

## 自查（对照规格与"无占位符"纪律）

**1. 规格覆盖**

| 规格出处 | 要求 | 本计划落点 |
|---|---|---|
| §6 P-2 第 ① 项 | 拆 `produce` → `plan_variants` + `export.submit` | Task 6（规划侧）+ Task 8（渲染侧）+ Task 9（删旧入口与迁调用点） |
| §6 P-2 第 ② 项 | `narration.get_plan` | Task 6 Step 7 实现 + Task 7 用例 |
| §6 P-2 第 ③ 项 | 角度重叠度量 | Task 2（度量）+ Task 6 Step 7 第 11 点（闸门）+ Task 11 Step 2（真机核对） |
| §5 #16 | `plan_variants(project, modes, k)` | Task 6 |
| §5 #17 | `plan_variants(exclude_plan_ids=[…])` | Task 6（`_excluded_angle_names` + `test_exclude_plan_ids_reaches_the_selection_prompt`） |
| §5 #18/#33 | `narration.get_plan` 用于详情与成品追溯 | Task 6/7；方案行只追加、永不覆写（《定案三》）保证 #33 的追溯不漂 |
| §5 #19 | 重叠率显示 | `overlap_max` 列（Task 1）+ 度量（Task 2） |
| §5 #20 | 模式多选作为 `plan_variants` 入参 | Task 6 |
| §5 #22 | `export.submit(plan_ids)` | Task 8 |
| §4.3 卡片四要素 | 角度名 / 取材集区间 / 钩子首句 / 模型自选理由 | `angle`（列）/ `episode_ids`+`plan_data.timeline`（既有）/ `narration_texts[0].text`（既有，见《定案三》为何不另立列）/ `angle_reason`（列） |
| §4.3 重叠率阈值 60% | 超阈值直接不出该角度 | `overlap.OVERLAP_LIMIT = 0.60` + Task 6 的 raise |
| §3.3.1 禁止级 | 不得重新引入模板或规则兜底、不得吞掉编剧链的 raise | Task 10 Step 6 的第三条 grep（新模块里不许出现降级语义词）；`angles._sanitize` 少答即抛（Task 3）；`_plan_one` 原样透传 `copywriter`/`script_driver` 的异常（Task 6） |
| 失败粒度=单条方案 | K 条独立失败 | Task 6 的 `test_one_variant_failure_does_not_kill_its_siblings` + `test_one_mode_failure_does_not_kill_other_modes`；try/except 位置下沉到变体循环内（变异检查 #1 钉住） |
| `narration_id` 是唯一配对键 | 不得按位置推断 | 本批次未新增任何位置推断：`_assert_renderable` 按 `narration_id` 查音频表（Task 8），`angles` 不碰配对；`plan_data` 无 `window` 字段这一事实被沿用（`copywriter._slot_block` 从配对段读区间，Task 4 未改） |
| 成本可观测 | 每变体 1 次成稿 + N 次配音，可观测而非事后重算 | `plan_cost()` 单一口径（Task 6 Step 7 第 8 点）+ 选题次数由 `batch_id` + `DISTINCT narration_mode` 数出（《定案二》） |
| §6 P-2 出口 | 阶段③ 能只看方案不渲染 | `test_plan_variants_writes_k_plans_without_rendering` 断言 `export.list == []`；Task 11 Step 1 真机复核 |
| §6 P-2 出口 | 批量建项目与阶段定位可用 | **不在本计划**，见《P-2b 交接规格》——本计划开头《范围裁决》已说明拆分理由 |

**2. 占位符扫描**：全文无 "TBD"、无"添加适当的错误处理"、无"同 Task N"式的转指（Task 9 Step 6 的对照表逐条写了处置方式与断言口径，不是"参照上文"）、代码块内无 `...（其余不变）...` 省略。每一处 `Expected:` 都给了具体的失败形态或退出码。

**3. 类型与命名一致性**（逐个核对过）：

- `angles.AngleBrief(name, reason, hook, episode_numbers)` —— Task 3 定义，Task 4（`prompt_block`）、Task 6（`_plan_one`/`_pick_episode`/`_worst_overlap`/`accepted` 的元素类型）、Task 6 测试夹具三处使用，字段名一致。
- `angles.select_angles(mode, *, mode_label, k, episode_inputs, settings, cross_episode, excluded, trace_dir)` —— Task 3 定义，Task 6 `_run_plan_variants` 调用时七个关键字全给（`mode` 为位置参数），Task 6/9 的测试替身按 `kwargs.get("mode_label")` 取用，一致。
- `angles.prompt_block(brief)` —— Task 3 定义，Task 4 测试与 Task 6 `_plan_one` 使用，一致。
- `overlap.source_spans(plan)` / `overlap.overlap(left, right)` / `overlap.OVERLAP_LIMIT` —— Task 2 定义，Task 6 与 Task 2 测试使用，一致。
- `narration_api._voice(context, plan, settings, *, job_id, mode, index)` —— Task 5 定义，Task 6 `_run_plan_variants` 调用与 Task 5/6 的测试替身签名一致（`voice_except_second` / `voice_then_cancel` 两个替身都按同一关键字集合定义）。
- `narration_api._plan_one(context, mode, episodes, episode_inputs, settings, brief)` —— Task 6 定义，Task 9 Step 6 的桩与迁移用例按同一位置参数序使用。
- `export_api._assert_renderable(plan_row, plan_data)` —— Task 8 定义，`submit` 与 `retry` 两处调用一致。
- `plans_repo.create(..., angle=, angle_reason=, variant_index=, overlap_max=, batch_id=)` —— Task 1 定义，Task 6 `_run_plan_variants` 五个关键字全给，一致。
- `plans_repo.list_by_batch(conn, project_id, batch_id)` —— Task 1 定义，Task 6/7/9 的测试与 Task 9 Step 2 的门禁 SQL（直接查库，不走仓储，因为 `verify_modes.py` 持有的是裸连接）语义一致。
- `narration_api.plan_cost(row)` → `{"copy_llm_calls", "tts_calls"}` —— Task 6 定义，Task 7 断言与 `protocol/schemas/narration.json` 的 `PlanCost` 字段名逐字一致。
- 错误码：`-32303`（K 越界）、`-32304`（方案不存在，narration 域）、`-32406`（`plan_ids` 非法）、`-32407`（不可渲染，export 域）——Task 6/8 的常量、Task 6/7/8 的测试断言、Task 10 Step 2 的文档表三处一致。注意 `narration.get_plan` 用的是 **narration 域的 `-32304`**，而 `export.submit`/`retry` 对"方案不存在"用的是 **export 域的 `-32401`**：同一个概念两个码，是因为两个命名空间各有自己的分段（docs/03 §5），**不是笔误**，与既有的"任务不存在有两个码"（`-32501` vs `-32201`）同一处境。

**4. 本计划自身发现并修正的规格问题**（详见交付报告，此处只列计划内的处置）：

- §5 #21 `serial_per_episode` 与 §4.3 ④ 自相矛盾 → 本批次不实现，写进《已知不做》并说明它天然属 P-2.5。
- `docs/03` §6 声称 `narration.get_plan` "从未实现、等同 `list_plans`" → 本批次实现它并在 Task 10 Step 2 删掉那句话，理由（K×模式条数下 `list_plans` 不再是"看一条"的合理入口）写进 `get_plan` 的 docstring。
- `docs/service/04` §4 的迁移清单漏登记 `009` → Task 10 Step 4 补上。
- `protocol/schemas/jobs.json` 的 `JobInfo.type` 词表缺 `semantic`、含即将消失的 `produce` → Task 9 Step 3 一并修正。
- `narration_plans.tts_segments` 是死列 → Task 10 Step 4 登记，不在本批删。
