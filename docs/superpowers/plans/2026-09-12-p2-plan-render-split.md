# P-2a 规划/渲染解耦 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `narration.produce` 拆成 `narration.plan_variants`（只规划）与 `export.submit`（只渲染），让阶段③ 能"只看方案、反复重掷、不付渲染成本"，并让一个模式的 K 条方案真的是 K 个互异的卖点角度。

**Architecture:** 三层切分——**选题层**（新增 `engines/narration/angles.py`：一个模式一次 LLM 调用产出 K 条卖点互异的取材角度，每条带角度名/理由/钩子首句/取材集）、**成稿层**（既有 `copywriter` / `scriptwriter`，本批次只多接一个"卖点角度"输入，不改其降级禁令）、**度量层**（新增 `engines/narration/overlap.py`：按源素材秒算 Jaccard 取材重叠，超 60% 的角度当场不出）。配音留在规划侧，故一条 `ready` 的方案行就是可渲染的成品输入，`export.submit` / `export.retry` 只读库、不做任何规划。

**Tech Stack:** Python 3.12 / pydantic v2 / SQLite（迁移 010）/ stdlib urllib（ADR-005 统一 OpenAI 协议）/ pytest / ruff / mypy strict；契约侧 JSON Schema + TypeScript（`protocol/`）。

规格出处：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §6（P-2 五项与出口判据）、§5 映射表 #16/#17/#18/#19/#20/#22、§4.3（剧空间③ 规格）、§3.3.1（降级裁决表）、§2.3（四阶段）。前批落地真相源：`docs/superpowers/plans/2026-09-11-p1-5-copy-truth-and-no-downgrade.md`（尤其《降级分类表》《实现定案修正》与四个 `### Task N 落地后的实测修正` 节）。

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

## 三处设计定案（实施前先读，代码里的注释都指回这里）

### 定案一：配音归规划侧，不归 `export.submit`

**位置**：`plan_variants` 内部配音；`export.submit` 只渲染。

**代码依据**：

1. `render_export`（`service/dramaclip/api/export.py:193-277`）从头到尾只做一件事——读传进来的 `run.plan_data` 渲染。它不合成任何音频。
2. 旁白音频的唯一来源是 `tts_audio_by_segment`（`api/export.py:165-179`），它按 `segment.narration_id` 取 `text.audio_path`。
3. `audio_path` 全仓只有一处写入：`pipeline.synthesize_narration_texts`（`engines/narration/pipeline.py:251-256`）。同一个函数还改写 `segment["end"] = start + duration`（`:249`）与 `segment["subtitle_text"] = text`（`:250`）。
4. 于是：**一条没配过音的方案行渲染出来，是一部没有解说声、也没有解说字幕的哑片，而且静默**——`api/export.py:260` 的 `tts_segments or None` 把空映射直接变成 `None`，编码器认为这条片本来就没有旁白。这正是规格 §3.3.1 禁止级「半条旁白的片子不可交付」。
5. `export.retry`（`api/export.py:124-152`）的幂等设计前提是"方案行是完整且不变的输入"：它重读同一行、复用同一个 `export_id`、只重跑渲染。若配音在 submit 侧，retry 就必须决定"要不要再配一次音"——要么重配（同一 `export_id` 两次配音、成本翻倍且结果可能不同），要么读一行没有音频的 plan（回到第 4 条）。两条都毁掉 P-1 好不容易做出来的幂等契约。

**后果（必须认）**：

- **一条 `status='ready'` 的方案行就是可渲染的成品输入**，`export.submit` 不需要任何规划知识。这是拆分能成立的根本原因。
- **`work_dir` 从缓存变成承重存储**。配音音频落在 `<data>/cache/analysis/tts/…`，而方案可能几小时后、几次重启后才被提交渲染。全仓没有任何路径清理 `work_dir`（`shutil.rmtree` 只出现在 `api/models.py:119`，删的是模型目录），所以今天它是"事实上永久"的；本批次把这个事实**变成契约**并写进注释。磁盘增长归 P-3 的「关于 → 本地数据」与回收站，不在本批。
- **重掷一条角度要重付它的配音成本**。规格 §6 承诺的是"不付**渲染**成本"，配音比渲染便宜一个量级；且 §4.3 ④ 的默认路径是 K 条全渲染，所以默认流程下一条都不浪费。

### 定案二：K 条角度怎么才真的互异

**角度由 LLM 选，一模式一次调用（不是一条角度一次）。** 规格 §4.3 定案「用户不能挑角度，角度归模型」，§4.4 的成本预估卡按「LLM 成稿次数」计账——若选题按变体付，成本账就变成 `k × 2` 次成稿，与 §4.4 的口径不符。所以：**每模式 1 次选题调用 + 每条方案 1 次成稿调用（`copywriter`，`dialogue_narration` 走 `scriptwriter`）+ 每条方案 N 次配音**。选题是模式级固定开销，一个 batch 的选题次数 = 该 batch 里不同模式的数量，可由 `narration_plans` 的 `batch_id` + `DISTINCT narration_mode` 直接数出，不落库。

**互异靠两条腿，缺一不可**：

1. **选题时把"互异"写成模型的硬约束，并让它交出可核对的证据**：每条角度必须给 `name`（角度名）/ `reason`（为什么这条值得单出一条片）/ `hook`（开场钩子首句）/ `episode_numbers`（取材集）。`angles._sanitize` 逐条验收：少一条、名字重复、字段为空、集号不存在、被排除的角度又提出来——**一律抛，绝不拿残缺的凑数**（凑数就是 §3.3.1 禁止级「假装有 K 条」）。
2. **出片前量一次取材重叠，超阈值当场不出**（规格 §4.3：阈值 60%）。这是防"K 变成老虎机"的安全阀，也是唯一能证伪模型自称互异的客观度量。

**重叠度量：量什么、在什么单位上量、阈值什么意思**

- **量取材（时间窗），不量文案。** 规格 §4.3 的用词是「角度间**取材**重叠率」，卡片四要素里对应的是「取材集区间」。文案重叠是另一个问题（同一批画面配不同解说词其实是合法的差异化手段），并进同一个数会让阈值失去意义。
- **单位是"源素材秒"，不是场景条数。** 段长不等：按条数会把"共用两个 25 秒长镜"算得比"共用五个 3 秒短镜"还轻，而观感上恰恰相反。
- **算法是 Jaccard：`共用秒数 / 两者并集秒数`。** 不用包含率（`交集 / 较短一方`）：包含率会把"一条 20 秒短片完全落在一条 100 秒长片里"报成 100%，而那条短片只占长片五分之一——真正要拦的是"两条看起来是同一部片"，Jaccard 量的正是这个。并集为 0（两条都没画面）时回 `0.0`：无素材可比重，不该判成同一部片。
- **只读 `plan_data.timeline` 的 `episode_id` / `start` / `end` 三个字段**，不读 `audio` 角色：`original` / `narration` / `ducked` 三种角色占的是同一段源画面，取材就是取材。**每集内先合并区间再算**：编排器会产出首尾相接的段（`full_narration` 逐场景、`dialogue_narration` 逐句吸附），不合并会把同一秒数出两次，重叠率能超过 1.0。
- **阈值语义**：候选角度与**同一模式内已接受的兄弟方案**逐条比，取最大值 `overlap_max`；`overlap_max > 0.60` 即抛错、这条角度不落库，其余角度不受影响（失败粒度=单条方案）。`overlap_max` 落库，因为**被拦掉的角度不留行**，事后无从重算当时那个数——存下来才有审计链。

**本批次不做的事（明确记下来，别当遗漏）**：一条方案内跨集拼画面。今天只有 `dialogue_narration` 具备（`pipeline.build_from_script_episodes` 按集号取素材，`engines/narration/pipeline.py:85-171`），其余六个模式的编排器签名是 `(episode_id, scenes, strategy)`，一条片只吃一集。所以本批次让**角度之间**跨集（不同角度取不同集，于是 K 条合起来覆盖全剧），而**单条方案内**仍限于一集。P-1.5 的《已知不做》把跨集化记成了 P-2 的事，这里如实收窄并说明理由：改六个编排器的取材结构会改成片形态，而九模式真机门禁的出口判据（时长窗、响度窗）正压在这个形态上，P-1.5 Task 10 尚未闭环时不动它。真正的跨集拼接归 P-2c（见末尾交接规格）。

### 定案三：job 与库的形状

**新列，不建新表。** `narration_plans` 加五列（迁移 `010`）：

| 列 | 类型 | 为什么必须是列而不是塞进 `plan_data` |
|---|---|---|
| `angle` | `TEXT NOT NULL DEFAULT ''` | 卡片的角度名（金色标签）。要按角度查重叠、按角度名排除重掷，塞在 JSON 里就得每行解析一遍 |
| `angle_reason` | `TEXT NOT NULL DEFAULT ''` | 卡片四要素之一「模型自选理由」，纯展示但必须留痕（模型为什么选这条） |
| `variant_index` | `INTEGER NOT NULL DEFAULT 1` | 1..K 的槽位号。不能靠 `created_at` 排序推：毫秒精度下同批多条会撞，`infra/jobs.py:94-96` 已为同一件事补过 `created_at, id` 兜底排序 |
| `overlap_max` | `REAL`（可空） | 与已接受兄弟方案的最大取材重叠。可空因为**首条没有兄弟**；存下来是因为被拦掉的角度不留行、事后算不出当时那个数 |
| `batch_id` | `TEXT`（可空） | 一次 `plan_variants` 调用产出全组的标识，取该作业的 `job_id`。它是唯一不含糊的组键：同一 (project, mode) 会被整组重规划多次，`created_at` 分段不可靠 |

**`钩子首句` 不单独立列**：卡片要展示的是"这条片实际说的第一句"，真相源是 `plan_data.narration_texts[0].text`（成稿后模型可能改写选题给的 hook）。存两份必然漂移，`get_plan` 现取即可。

**成本账不立列**：`copy_llm_calls` = `1 if plan_data.narration_texts else 0`（`raw_clip`/`subtitle_flow` 无槽位、零成稿，已由 `modes_w9.py` 全文无 `NarrationText` 证实），`tts_calls` = `len(plan_data.narration_texts)`。两个都是**恒等推导**，存下来只多一处会漂的副本（docs/04 §5.2「同一概念双处定义」）。口径写在唯一的助手 `plan_cost()` 里，`get_plan` 返回它——这就是"可观测而不必事后重算"。选题次数按定案二由 `batch_id` + `DISTINCT narration_mode` 数出。

**方案行永不覆写，只追加。** 整组重规划 = 新 `batch_id` + K 条新行；重掷此条 = 新 `batch_id` + 1 条新行，`exclude_plan_ids` 指名被替换的方案、其角度名进选题 prompt 的排除清单。不覆写的理由：`export_jobs.narration_plan_id` 指向被渲染的那一行，覆写会让成品库的「跳回方案」（规格 §5 #33）指到一个已不是当初渲染出来的角度上。阶段③ 如何把"重掷的单条"并回 K 条一组显示，是 P-3 的展示决策，本批次只保证**任何并法都可行**。

**`export.submit` 与既有幂等 `retry` 的分工**：`submit` 是"新提交"，每条方案建一行新 `export_jobs` + 一个新 export job；`retry` 是"重跑一条已失败的提交"，复用原 `export_id` 覆盖写（`api/export.py:124-152`，P-1 已幂等）。**`submit` 不复制 `retry` 的任何机械**——两者都经同一个 `_submit_export`（`api/export.py:66-94`）投递，取消事件的注册与 `_run_export` finally 里的回收因此仍只有一处。一条方案一个 export job（不是一次提交一个大 job），这样规格 §4.4 的「条级 重掷/重试」与 `jobs.cancel` 的粒度才对得上。

**`submit` 不去重历史、只去重本次调用**：同一个 `plan_id` 在一次 `plan_ids` 里出现两次只出一次片（这是纯 bug，必须拦）；跨两次提交重复渲染同一条方案是合法的（换了字幕预设再出一版——规格 §4.3 ④ 的字幕预设与连载模式都是"提交时参数"），成品去重归 P-3 的成品库批量动作。

---

## 文件结构

**新建**

| 路径 | 职责 |
|---|---|
| `service/dramaclip/engines/narration/angles.py` | 选题层：一个模式一次 LLM 调用 → K 条卖点互异的 `AngleBrief`；逐条验收、不合格即抛 |
| `service/dramaclip/engines/narration/overlap.py` | 度量层：源素材秒的 Jaccard 取材重叠 + 60% 阈值常量。纯函数，不触 IO |
| `service/dramaclip/infra/storage/migrations/010_plan_angles.sql` | `narration_plans` 五列 + batch 索引 |
| `service/tests/engines/narration/test_angles.py` | 选题层的验收分支逐条钉住（12 条变异检查） |
| `service/tests/engines/narration/test_overlap.py` | 合并、交集、Jaccard、阈值边界 |
| `service/tests/infra/storage/test_plans.py` | 五个新列的落库与读回、`list_by_batch` |
| `service/tests/api/test_plan_variants.py` | 由 `tests/api/test_produce.py` 改名而来（`git mv`）：`Harness` 与种子函数留在此文件，`test_data_paths.py:8` 的 import 随之改 |
| `service/tests/api/test_export_submit.py` | `export.submit` 的接受/拒绝两路、可渲染性守卫、与 `retry` 的同形 |

**修改**

| 路径 | 改什么 |
|---|---|
| `service/dramaclip/api/narration.py` | 删 `produce`/`_run_produce`/`generate_plans`/`_run_generation_parallel`/`_generate_one`/`_newest_ready_plan`；加 `plan_variants`/`_run_plan_variants`/`_plan_one`/`_voice`/`_store_plan`/`get_plan`/`plan_cost`/`_effective_settings`/`_worst_overlap` |
| `service/dramaclip/api/export.py` | `start` → `submit(plan_ids)`；加 `_assert_renderable` 并被 `submit`/`retry` 共用；两个新错误码 |
| `service/dramaclip/engines/narration/copywriter.py` | `write_plan_copy` 增必填关键字 `angle_block`，进 user prompt |
| `service/dramaclip/engines/narration/scriptwriter.py` | `write_script_episodes` 增必填关键字 `angle_block`；`_format_transcript_episodes` → `format_transcript_episodes`（公开给 `angles.py` 复用，与 P-1.5 公开 `FUNDAMENTALS`/`clock`/`dump_trace` 同一套路） |
| `service/dramaclip/engines/narration/script_driver.py` | `script_dialogue_plan` 增必填关键字 `angle_block` 并转交 |
| `service/dramaclip/infra/storage/repos/plans.py` | `_COLUMNS` 加五列；`create` 加五个关键字参数；新增 `list_by_batch` |
| `service/dramaclip/infra/config.py` | `DEFAULTS` 加 `narration.variants_per_mode` |
| `protocol/schemas/narration.json` | 删 `generate_plans`/`produce`，加 `plan_variants`/`get_plan`；`NarrationPlan` 加五字段 + `PlanCost`/`PlanDetail`；`list_plans` 加 `batch_id` |
| `protocol/schemas/export.json` | `start` → `submit`，返回体改 `{exports, rejected}` |
| `protocol/schemas/jobs.json` | `JobInfo.type` 的描述去掉 `produce`、补上实际在用的 `semantic` |
| `protocol/ts/index.ts` | `METHOD_NAMES` 同步（删 2 加 2，净 0）；`NarrationPlan` 加字段；新增 `PlanCost`/`PlanDetail`/`PlanVariantsResult`/`ExportSubmitResult` |
| `desktop/src/services/client.ts` | 删 `narrationApi.produce`/`generatePlans`、`exportApi.start`；加 `planVariants`/`getPlan`/`submit` |
| `desktop/src/features/narration/useProduceJob.ts` | 唯一的生产调用点（`:31`）：改成 `plan_variants` → 等作业 → `list_plans` 取本 batch → `export.submit` → 等全部 export job。**这是保住既有页面可用，不是做 UI** |
| `scripts/verify_modes.py` | `:459` 的 `narration.produce` 单次派发 → 两步派发（规划 + 提交），并加 `--variants` 旋钮（默认 1，九模式门禁口径不变） |
| `service/tests/api/test_data_paths.py` | `:8` 的 import 源改名；`:18` 的 `narration.produce` → 两步 |
| `docs/03-IPC协议规范.md` | §5.2 错误码表加 `-32303/-32304/-32406/-32407`；§6 的「46 个方法」重数、`narration.*` 与 `export.*` 条目改写、删掉「`narration.get_plan` 从未实现」那句（本批次实现它） |
| `docs/service/01-传输与API层设计.md` | §4 的方法清单与合计数、`api/narration.py` 与 `api/export.py` 两行；§6 的「`projects.settings` 尚无消费端」改成已接线并登记覆盖键名 |
| `docs/service/04-数据模型.md` | `narration_plans` 的 DDL 加五列、迁移清单加 `010` 行（并补上漏登记的 `009`）、§3 登记实际使用的项目级覆盖键名 |

**不动**：`docs/05-开发路线图.md`（用户自维护）；另一位工程师的 `scripts/verify_e2e.mjs`、`scratch/`、`tests/api/test_analysis.py`、`tests/engines/analysis/*`、`hotwords.py`、`docs/07-*`；`data/data.db`（只读）；六个模式编排器 `modes/__init__.py`、`modes_w5.py`、`modes_w8.py`、`modes_p2.py`、`modes_w9.py`（定案二：本批次不改成片形态）；`engines/exporter/*`（渲染侧一行不动，这是拆分干净的证明）。

---

## Task 1: 迁移 010 + `narration_plans` 五列 + 仓储读写

**Files:**
- Create: `service/dramaclip/infra/storage/migrations/010_plan_angles.sql`
- Modify: `service/dramaclip/infra/storage/repos/plans.py`
- Modify: `service/tests/infra/storage/test_db.py:33-43`
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


def test_list_by_batch_returns_only_that_batch_in_variant_order(
    memory_db: sqlite3.Connection,
) -> None:
    project_id = _seed_project(memory_db)
    for batch, index in (("batch-a", 1), ("batch-a", 2), ("batch-b", 1)):
        plans_repo.create(
            memory_db,
            project_id,
            "full_narration",
            ["ep1"],
            {"mode": "full_narration", "timeline": []},
            angle=f"角度{batch}{index}",
            variant_index=index,
            batch_id=batch,
        )
    group = plans_repo.list_by_batch(memory_db, project_id, "batch-a")
    assert [row["variant_index"] for row in group] == [1, 2]
    assert plans_repo.list_by_batch(memory_db, project_id, "batch-缺") == []


def test_list_by_project_newest_first_still_carries_angles(
    memory_db: sqlite3.Connection,
) -> None:
    project_id = _seed_project(memory_db)
    plans_repo.create(
        memory_db, project_id, "raw_clip", [], {"mode": "raw_clip"}, angle="旧角度"
    )
    plans_repo.create(
        memory_db, project_id, "raw_clip", [], {"mode": "raw_clip"}, angle="新角度"
    )
    listed = plans_repo.list_by_project(memory_db, project_id)
    assert [row["angle"] for row in listed][:2] == ["新角度", "旧角度"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/infra/storage/test_plans.py -q`

Expected: FAIL —— 四条全红，`TypeError: create() got an unexpected keyword argument 'angle'`

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

- [ ] **Step 6: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/infra/storage -q`

Expected: PASS（`test_plans.py` 4 条 + `test_db.py` 3 条 + `test_episodes.py` 全绿）

- [ ] **Step 7: 变异检查**

依次手工破坏，每项跑 Step 6 的命令必须变红，改回后绿：

1. `plans.py` 的 `_COLUMNS` 去掉 `"overlap_max"` → `test_create_persists_the_five_angle_columns` 必须红（`zip(strict=True)` 因列数不符抛 `ValueError`——这正是 `_COLUMNS` 用 `strict=True` 的收益）。
2. 迁移里 `overlap_max REAL` 改成 `overlap_max REAL NOT NULL DEFAULT 0` → `test_angle_columns_default_to_the_migration_defaults` 必须红（`None` 变 `0.0`，「无从比」被伪装成「完全不重叠」）。
3. `list_by_batch` 的 `ORDER BY narration_mode, variant_index` 改成 `ORDER BY created_at` → `test_list_by_batch_returns_only_that_batch_in_variant_order` 必须红。
4. `list_by_batch` 的 `WHERE` 去掉 `AND batch_id = ?` → 同上用例必须红（返回 3 条而不是 2 条）。

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

## Task 3: 选题层——`angles.py` 一个模式 K 条互异卖点

**Files:**
- Create: `service/dramaclip/engines/narration/angles.py`
- Modify: `service/dramaclip/engines/narration/scriptwriter.py:160`（`_format_transcript_episodes` → 公开）
- Create: `service/tests/engines/narration/test_angles.py`

- [ ] **Step 1: 把转写拼装块转成公开函数**

`service/dramaclip/engines/narration/scriptwriter.py`：`_format_transcript_episodes` → `format_transcript_episodes`（含其唯一引用点 `write_script_episodes` 里的 `transcript_block = _format_transcript_episodes(episode_inputs)`）。函数体与 docstring 一字不动。改完执行：

Run: `cd service && grep -rn "_format_transcript_episodes" . --include=*.py`

Expected: 无输出。

（这与 P-1.5 把 `_FUNDAMENTALS` / `_dump_trace` / `_clock` 转公开是同一套路：第二个消费者出现时下划线就该去掉，而不是各抄一份。`tests/engines/narration/test_script_input_budget.py` 若引用了旧名，同批改成新名并一起提交。）

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

Expected: PASS

- [ ] **Step 6: 变异检查（本任务的重点，一条都不许省）**

`_sanitize` 与 `select_angles` 合计**十三条**拒绝分支。上一批的实测修正是这么写的：「新增拒绝分支的用例必须当场做『删掉这行分支看它红不红』的验证，否则它只是把 happy path 又跑了一遍」。逐条破坏、逐条跑 Step 5 的命令、逐条按字节还原：

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `if len(items) < k: raise` 整块删掉 | `test_fewer_angles_than_k_raises` |
| 2 | `if name in seen: raise` 整块删掉 | `test_duplicate_names_raise` |
| 3 | `if name in excluded: raise` 整块删掉 | `test_excluded_name_reproposed_raises` |
| 4 | `if not name or not reason or not hook: raise` 整块删掉 | `test_empty_field_raises` |
| 5 | `if unknown: raise` 整块删掉 | `test_unknown_episode_number_raises` |
| 6 | `if not cross_episode and len(numbers) != 1` 改成 `if False` | `test_single_episode_mode_rejects_multi_episode_angle` |
| 7 | `if not numbers: raise` 整块删掉 | `test_empty_episode_list_raises` |
| 8 | `len(name) > _MAX_NAME_CHARS` 的 raise 删掉 | `test_oversize_name_raises` |
| 9 | `len(hook) > _MAX_HOOK_CHARS` 的 raise 删掉 | `test_oversize_hook_raises` |
| 10 | `if not isinstance(items, list): raise` 整块删掉 | `test_missing_angles_array_raises` |
| 11 | `if not isinstance(item, dict): raise` 整块删掉 | `test_non_object_item_raises` |
| 12 | `if k < 1: raise` 整块删掉 | `test_k_below_one_raises` |
| 13 | `if not transcript: raise` 整块删掉 | `test_no_transcript_raises` |

**第 11 条的陷阱**（上一批踩过同类）：删掉 `isinstance(item, dict)` 之后 `AngleBrief.model_validate("一条字符串")` 会抛 `ValidationError`，被下一行转成 `ValueError("角度项字段不合法")`——用例仍然红，但红的已经不是这条分支。所以 `test_non_object_item_raises` 的 `match` 必须写死「非对象项」这个词：**变异后它要因为消息对不上而红，才算真的守着这一行**。

**第 6 条的陷阱**：`numbers` 在该分支之前已经 `sorted(set(...))`，若把去重删掉，`[1, 1]` 会被判成"给了 2 集"而误红——去重与单集判定是一对，破坏其一时要看清红的是哪条断言。

- [ ] **Step 7: 提交**

```bash
git add service/dramaclip/engines/narration/angles.py service/dramaclip/engines/narration/scriptwriter.py service/tests/engines/narration/test_angles.py service/tests/engines/narration/test_script_input_budget.py
git commit -m "feat(narration): angles 选题层，一个模式一次调用产出 K 条互异卖点"
```

---

## Task 4: 卖点角度进成稿 prompt（两条链同形）

角度只影响选题是不够的：`copywriter` 若不知道这条片的卖点，K 条方案的**文案**会趋同，而重叠度量只看取材、拦不住"同一批画面配三段同义解说"。本任务把角度块接进两条成稿链。

**Files:**
- Modify: `service/dramaclip/engines/narration/copywriter.py:93-121`
- Modify: `service/dramaclip/engines/narration/scriptwriter.py:206-249`
- Modify: `service/dramaclip/engines/narration/script_driver.py:62-102`
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
git add service/dramaclip/engines/narration/copywriter.py service/dramaclip/engines/narration/scriptwriter.py service/dramaclip/engines/narration/script_driver.py service/dramaclip/api/narration.py service/tests/engines/narration service/tests/api/test_produce.py
git commit -m "feat(narration): 卖点角度注入两条成稿链，措辞由 angles.prompt_block 独家持有"
```

---

## Task 5: 配音目录按作业与变体隔离（K 条互相覆盖的必修 bug）

**为什么这是阻塞项而不是优化**：`pipeline.synthesize_narration_texts` 把音频写成 `work_dir / f"{item.id}.mp3"`（`engines/narration/pipeline.py:232`），而 `api/narration.py:263` 传的是全局共享的 `context.work_dir / "tts"`。槽位 id 是**模式内确定的**：`intro-1`（`modes/__init__.py:18`）、`cross-{i}`（`modes_w5.py:56`）、`full-{i}`（`modes_w8.py:47`）、`dual-{i}`（`modes_p2.py:45`）、`mono-{i}`（`modes_p2.py:86`）、`hook-1`/`cta-1`（`modes_w5.py`）、`n0..nN`（`pipeline.py:126/141/157`）。于是同一模式的 K 条变体算出**同一批文件名**：变体 2 的配音覆盖变体 1 的音频文件，而变体 1 的 `plan_data.narration_texts[*].audio_path` 仍指向那个路径。渲染变体 1 时 `tts_audio_by_segment` 照路径取出的是变体 2 的声音，字幕却是变体 1 的（`subtitle_text` 存在 plan_data 里、不被覆盖）——**角度一的画面配角度二的解说，全静默，且只在 K>1 时出现**。本任务在引入 K 之前先修掉它。

（今天它已经潜在可达：两个并发 produce 作业跑同一模式就会互撞，`hardware.max_parallel_jobs` 默认 2。K 只是把它从偶发变成必然。）

**Files:**
- Modify: `service/dramaclip/api/narration.py:262-265`
- Modify: `service/tests/api/test_produce.py`

- [ ] **Step 1: 写失败测试**

追加到 `service/tests/api/test_produce.py`（该文件已有 `Harness`、`_seed_project_with_analysis`、`_wait_terminal`、`pipeline`、`narration_api`；文件顶部补 `from dramaclip.engines.narration.models import NarrationText, TimelineSegment`，`PlanData` 已在该文件 import 过）：

```python
def test_two_variants_of_one_mode_do_not_share_tts_paths(
    memory_db: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同模式两条变体的配音文件必须落在不同路径。

    槽位 id 是模式内确定的（full-1、full-2…），共用一个 tts 目录时第二条会覆盖
    第一条的音频，而第一条 plan_data 里存的 audio_path 仍指向那个路径——
    渲染出来就是「角度一的画面配角度二的声音」，字幕还是角度一的，全静默。

    夹具直接手搓两条只有文案不同的方案：撞车的充分条件就是槽位 id 相同，
    把编排器与 LLM 拉进来只会让本用例慢十倍且验的还是同一件事。
    """
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    written: list[Path] = []

    class _RecordingTts:
        def synthesize(self, text: str, _voice: str | None, out_path: Path) -> Path:
            assert text.strip(), "语言层没填上文案，槽位还是空的"
            written.append(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"")
            return out_path

    monkeypatch.setattr(pipeline, "create_tts", lambda *a, **k: _RecordingTts())
    monkeypatch.setattr(pipeline.tts_base, "audio_duration_s", lambda _p: 1.25)

    plans = [
        PlanData(
            mode="full_narration",
            timeline=[
                TimelineSegment(
                    episode_id="ep1", start=0.0, end=2.0, audio="ducked", narration_id="full-1"
                )
            ],
            narration_texts=[
                NarrationText(id="full-1", text=f"角度 {index} 的解说文案", brief="推进")
            ],
        )
        for index in (1, 2)
    ]
    for index, plan in enumerate(plans, start=1):
        narration_api._voice(
            harness.context,
            plan,
            dict(harness.context.settings),
            job_id="job-x",
            mode="full_narration",
            index=index,
        )

    assert len(written) == 2, f"本用例要两次配音，实得 {len(written)}"
    assert len(set(written)) == len(written), f"配音路径撞了：{written}"
    assert all("job-x" in str(path) for path in written), "路径未带作业 id，跨作业仍会互撞"
    assert all("full_narration-1" in str(p) or "full_narration-2" in str(p) for p in written), (
        f"路径未带变体号：{written}"
    )
```

（打桩方式与本文件既有的 `test_style_directives_reach_the_copy_prompt` 逐字同形——`pipeline.create_tts` 与 `pipeline.tts_base.audio_duration_s` 两处一起打，缺后者会让 `synthesize_narration_texts` 死在"时长无效"上，看起来像路径没修好。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_produce.py -q -k tts_paths`

Expected: FAIL —— `AttributeError: module 'dramaclip.api.narration' has no attribute '_voice'`

- [ ] **Step 3: 建 `_voice`**

`service/dramaclip/api/narration.py`，在 `_collect_episode_inputs` 之前新增：

```python
def _voice(
    context: AppContext,
    plan: PlanData,
    settings: dict[str, str],
    *,
    job_id: str,
    mode: str,
    index: int,
) -> PlanData:
    """配音，音频落在**本作业本变体独占**的目录里。

    槽位 id 是模式内确定的（full-1、cross-2、n0…），K 条同模式变体因此算出同一批
    文件名；共用一个 tts 目录时后一条会覆盖前一条的音频，而前一条 plan_data 里存的
    audio_path 仍指向那个路径——渲染出来就是「角度一的画面配角度二的声音」。
    作业 id + 模式 + 变体号才凑得出唯一目录。无槽位时由 synthesize_narration_texts
    自己早退，本函数不重复判。

    这些文件因此从缓存变成承重存储：定案一让配音归规划侧，方案可能在几小时后、
    几次重启后才被 export.submit 渲染，届时读的就是这里的路径。全仓没有任何路径清理
    work_dir（shutil.rmtree 只出现在 api/models.py 删模型），这个事实就此成为契约。
    """
    tts_dir = context.work_dir / "tts" / job_id / f"{mode}-{index}"
    return narration_pipeline.synthesize_narration_texts(
        plan, settings, tts_dir, context.data_dir / "models"
    )
```

并把 `_generate_one` 尾部的四行（`api/narration.py:262-265`）：

```python
    if plan.narration_texts:
        tts_dir = context.work_dir / "tts"
        models_dir = context.data_dir / "models"
        plan = narration_pipeline.synthesize_narration_texts(plan, settings, tts_dir, models_dir)
```

替换为一行（`_generate_one` 在 Task 6 整体删除，此处只为让本任务的测试与既有套件同时成立）：

```python
    plan = _voice(context, plan, settings, job_id="legacy", mode=mode, index=1)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_produce.py -q -k tts_paths`

Expected: PASS。若 PASS 得太顺，验一次"路径真的被走过"：在 `_RecordingTts.synthesize` 首行临时加 `raise AssertionError("没走到")`，重跑必须红，然后删掉——**用例绿而路径没被走过，是本仓已经中过两次的假绿形态**。

- [ ] **Step 5: 变异检查**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `_voice` 的 `tts_dir` 改回 `context.work_dir / "tts"` | `test_two_variants_of_one_mode_do_not_share_tts_paths`（`len(set(written)) == len(written)` 那条断言） |
| 2 | `tts_dir` 去掉 `job_id` 只留 `f"{mode}-{index}"` | 同上用例的 `"job-x" in str(path)` 那条断言 |
| 3 | `tts_dir` 去掉 `f"{mode}-{index}"` 只留 `job_id` | 同上用例的最后一条断言（路径未带变体号） |

Run（每轮）: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_produce.py -q -k tts_paths`

- [ ] **Step 6: 全量回归 + 提交**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest -q`

Expected: PASS（既有 `test_analysis.py` flake 除外）

```bash
git add service/dramaclip/api/narration.py service/tests/api/test_produce.py
git commit -m "fix(narration): 配音目录按作业与变体隔离，K 条同模式方案不再互相覆盖音频"
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

    def voice_except_second(
        context: Any, plan: Any, settings: Any, *, job_id: str, mode: str, index: int
    ) -> Any:
        seen.append(index)
        if index == 2:
            raise RuntimeError("旁白 full-1 合成失败（引擎=edge）：云端不可达")
        return real_voice(context, plan, settings, job_id=job_id, mode=mode, index=index)

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

    plans = plans_repo.list_by_batch(memory_db, project_id, str(result["batch_id"]))
    assert {row["narration_mode"] for row in plans} == {"raw_clip"}, "另一个模式被牵连了"
    assert len(plans) == 3


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

    def voice_then_cancel(
        context: Any, plan: Any, settings: Any, *, job_id: str, mode: str, index: int
    ) -> Any:
        voiced = real_voice(context, plan, settings, job_id=job_id, mode=mode, index=index)
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

文件顶部补 import（`Any` / `re` / `json` / `shutil` / `pytest` / `RpcRequest` / `PlanData` 该文件已有）：

```python
from dramaclip.engines.narration import angles
from dramaclip.infra.storage.repos import plans as plans_repo
```

- [ ] **Step 4: 跑测试确认失败**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q -k "plan_variants or variant_failure or mode_failure or overlapping_angle or exclude_plan or k_defaults or project_override or k_out_of_range or unknown_excluded or empty_modes"`

Expected: FAIL —— 全部报 `AssertionError: narration.plan_variants RPC 错误: [-32601] 方法不存在`

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
            "description": "每模式方案数；缺省读 narration.variants_per_mode（项目级覆盖优先）"
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

2. import 区加：

```python
from dataclasses import dataclass

from dramaclip.engines.narration import angles, overlap
from dramaclip.infra import config
```

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
# 单条方案内的跨集拼接归 P-2c（见计划《定案二》末段）。
_CROSS_EPISODE_MODES = frozenset({"dialogue_narration"})

# 界面 K 选择器的上限。再往上选题 prompt 会退化成让模型凑数，
# 而凑出来的角度正是重叠度量要拦的东西——不如在这里就拦掉。
_MAX_VARIANTS = 8
```

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

10. 新增重叠比对的内部类型与助手（放在 `_effective_settings` 之后）：

```python
@dataclass(frozen=True)
class _OverlapHit:
    """与一条已接受兄弟方案的重叠：名字用来点名，比值用来判阈值与落库。"""

    name: str
    ratio: float


def _worst_overlap(
    plan: PlanData, accepted: list[tuple[angles.AngleBrief, PlanData]]
) -> _OverlapHit | None:
    """与同模式已接受兄弟里最像的那条比；没有兄弟时回 None（不是 0.0）。

    None 与 0.0 是两件事，落库时必须分得开：前者是「无从比」，后者是「比过、全异」。
    """
    worst: _OverlapHit | None = None
    for brief, other in accepted:
        ratio = overlap.overlap(plan, other)
        if worst is None or ratio > worst.ratio:
            worst = _OverlapHit(name=brief.name, ratio=ratio)
    return worst
```

11. 新增 `plan_variants` 与其 runner（放在 `_collect_episode_inputs` 之后，取代原 `produce`/`_run_produce` 的位置）：

```python
def plan_variants(context: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """阶段③：为选中模式各产出 K 条卖点互异的方案，只规划不渲染（规格 §6 的拆分）。

    K 的取值顺序：入参 > 项目级覆盖 > 全局默认。回显实际用的 K，界面不必自己算一遍。
    所有可同步判定的错都在派发作业之前抛——进了作业就只是一条 failed 行，
    界面拿不到错误码（docs/service/01 §4 长任务模式第 1 步）。
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
        cancel_event,
    )
    return {"job_id": job_id, "k": k, "batch_id": job_id}


def _excluded_angle_names(context: AppContext, exclude_plan_ids: list[str]) -> list[str]:
    """重掷此条：把被替换方案的角度名交给选题，别再提同一个卖点。

    方案不存在在此抛（RPC 边界），不留到作业里——那只会变成一条 failed 行。
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
    cancel_event: threading.Event,
) -> None:
    """逐模式选题一次 → 逐条角度 成稿+配音+落库。

    失败粒度是**单条方案**：try/except 包在变体循环**内**，一条的 LLM/TTS 失败
    既不带走了它的 K-1 个兄弟，也不带走别的模式。这是 P-1.5「失败粒度=单条方案」
    从模式级下沉到变体级——原状 _run_produce 与 run_group 的 try 都包着整个模式。
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
            except Exception as exc:  # noqa: BLE001 - 选题失败 = 这个模式的 K 条全没了
                # 按 K 条记账：界面才不会把「这个模式一条都没出」显示成「这个模式本来就没有方案」
                failures.extend(f"{label}·角度{i}: {exc}" for i in range(1, k + 1))
                context.notifier.log("error", f"{label} 选题失败: {exc}")
                done_count += k
                context.job_store.set_progress(
                    job_id, round(done_count / total * 100, 1), f"{label} 选题失败"
                )
                continue

            accepted: list[tuple[angles.AngleBrief, PlanData]] = []
            for index, brief in enumerate(briefs, start=1):
                if cancel_event.is_set():
                    break
                tag = f"{label}·{brief.name}"
                try:
                    plan, used_ids = _plan_one(
                        context, mode, episodes, episode_inputs, settings, brief
                    )
                    worst = _worst_overlap(plan, accepted)
                    if worst is not None and worst.ratio > overlap.OVERLAP_LIMIT:
                        raise ValueError(
                            f"取材与「{worst.name}」重叠 {worst.ratio:.0%}，"
                            f"超过 {overlap.OVERLAP_LIMIT:.0%}——这条角度不出（规格 §4.3）"
                        )
                    plan = _voice(
                        context, plan, settings, job_id=job_id, mode=mode, index=index
                    )
                    plans_repo.create(
                        context.conn,
                        project_id,
                        mode,
                        used_ids,
                        plan.model_dump(),
                        angle=brief.name,
                        angle_reason=brief.reason,
                        variant_index=index,
                        overlap_max=None if worst is None else worst.ratio,
                        batch_id=job_id,
                    )
                    accepted.append((brief, plan))
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


def _plan_one(
    context: AppContext,
    mode: str,
    episodes: list[dict[str, Any]],
    episode_inputs: list[dict[str, Any]],
    settings: dict[str, str],
    brief: angles.AngleBrief,
) -> tuple[PlanData, list[str]]:
    """按角度产出一条方案（未配音）。

    取材集由角度决定，不再恒取 episodes[0]——那是「K 条其实是同一部片切 K 次」的
    根源之一。返回 (方案, 用到的集 id)。
    """
    angle_block = angles.prompt_block(brief)
    trace_dir = context.data_dir / "logs" / "llm"

    if mode == "dialogue_narration":
        wanted = set(brief.episode_numbers)
        scoped = [
            episode for episode in episode_inputs if int(episode["number"]) in wanted
        ]
        if not scoped:
            raise ValueError(f"角度「{brief.name}」的取材集都没有转写")
        context.notifier.log(
            "info",
            f"跨集输入：{len(scoped)} 集 → "
            f"每集约 {scriptwriter.transcript_sampling_quota(len(scoped))} 段摘录",
        )
        return script_driver.script_dialogue_plan(
            scoped, settings, angle_block=angle_block, trace_dir=trace_dir
        )

    episode = _pick_episode(episodes, brief)
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
        plan = copywriter.write_plan_copy(
            plan,
            asr_segments,
            settings,
            mode_label=narration_pipeline.MODE_LABELS.get(mode, mode),
            angle_block=angle_block,
            trace_dir=trace_dir,
        )
    return plan, [str(episode["id"])]


def _pick_episode(
    episodes: list[dict[str, Any]], brief: angles.AngleBrief
) -> dict[str, Any]:
    """角度点名的那一集。点名集不在已完成集里就抛——绝不悄悄换一集顶上。"""
    wanted = set(brief.episode_numbers)
    for episode in episodes:
        if int(episode["episode_number"]) in wanted:
            return episode
    raise ValueError(
        f"角度「{brief.name}」取材集 {sorted(wanted)} 不在已完成分析的集里"
    )
```

12. 删掉 `_generate_one`（原 `:211-272`）、`produce`（原 `:310-333`）、`_run_produce`（原 `:336-413`）、`_newest_ready_plan`（原 `:416-423`）四个函数，以及随之失去引用的 import：`from dramaclip.api.export import ExportRun, render_export`。

Run: `cd service && grep -rn "_generate_one\|_run_produce\|_newest_ready_plan\|render_export" dramaclip/api/narration.py`

Expected: 无输出。

- [ ] **Step 8: 跑测试确认通过**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/api/test_plan_variants.py -q -k "plan_variants or variant_failure or mode_failure or overlapping_angle or exclude_plan or k_defaults or project_override or k_out_of_range or unknown_excluded or empty_modes or cancel_releases"`

Expected: PASS（11 条新增用例）

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/transport/test_contract_sync.py -q`

Expected: **PASS**。Step 5 删掉了 schema 里的 `generate_plans`/`produce`、Step 7 删掉了 Python 侧的注册，两侧集合同步收窄；`plan_variants`/`get_plan` 两侧同步新增。`export.start` 此时两侧都还在（Task 8 才动），故仍相等。**若这里红，说明 Step 5 与 Step 7 的方法集合没对齐——先修齐再往下走，不要靠 Task 9 兜。**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20`

Expected: **此时全套是红的，且红的地方全部可预期**：① `tests/api/test_plan_variants.py` 里那些还打 `narration.produce` / `narration.generate_plans` 的既有用例（Task 9 Step 6 迁移）；② `tests/api/test_data_paths.py`（Task 9 Step 5 迁移）。**逐条核对红的用例都在这两处**——若还有第三处红，那是本任务改坏了什么，就地修掉，不要留给 Task 9。

- [ ] **Step 9: 确认本任务不能独立提交**

契约两侧已对齐，但**这个提交仍然无法独立构建**，理由有三条，全部在 Task 9 里解决：

1. `desktop/src/services/client.ts:112,120` 仍调 `'narration.produce'` 与 `'narration.generate_plans'`，而 `METHOD_NAMES` 里已经没有这两个名字——`rpc<T>(method: MethodName, …)` 的形参类型是 `MethodName`，故 `npm run typecheck` 必红。
2. `scripts/verify_modes.py:459` 仍派发 `narration.produce`，运行时会拿到 `-32601`——九模式门禁就此失效。
3. `tests/api/test_plan_variants.py` 与 `test_data_paths.py` 里还有一批打旧方法的用例，`pytest` 必红。

所以 Task 6 的 Step 10 只暂存不提交，提交动作在 Task 9 的 Step 8 一次完成（docs/04 §4「每个提交可独立构建」）。

Run: `cd service && ../.venv/Scripts/ruff.exe check dramaclip && ../.venv/Scripts/mypy.exe dramaclip`

Expected: 无输出、退出码 0。若 mypy 报 `re.search(...).group(1)` 的 `Optional`，测试夹具里已给了 `# type: ignore[union-attr]`；若报 `_wait_terminal` 返回值的字段访问，按报错补断言而不是加 ignore。

- [ ] **Step 10: 变异检查 + 暂存（不提交）**

| # | 破坏 | 必须红的用例 |
|---|---|---|
| 1 | `_run_plan_variants` 的内层 `try/except` 上移一层，包住整个 `for index, brief` 循环 | `test_one_variant_failure_does_not_kill_its_siblings`（`seen == [1, 2, 3]`） |
| 2 | 选题失败的 `failures.extend(... for i in range(1, k + 1))` 改成 `failures.append(f"{label}: {exc}")` | `test_one_mode_failure_does_not_kill_other_modes`（`error.count("全片解说") == 3`） |
| 3 | `if worst is not None and worst.ratio > overlap.OVERLAP_LIMIT: raise` 整块删掉 | `test_overlapping_angle_is_dropped_not_stored` |
| 4 | `overlap_max=None if worst is None else worst.ratio` 改成 `overlap_max=0.0 if worst is None else worst.ratio` | `test_plan_variants_writes_k_plans_without_rendering`（`overlap_max is None` 那条断言） |
| 5 | `if not 1 <= k <= _MAX_VARIANTS: raise` 整块删掉 | `test_k_out_of_range_is_rejected_at_the_rpc_boundary` |
| 6 | `_excluded_angle_names` 的 `if row is None: raise` 改成 `continue` | `test_unknown_excluded_plan_is_rejected_at_the_rpc_boundary` |
| 7 | `if not modes: raise` 整块删掉 | `test_empty_modes_is_rejected` |
| 8 | `_effective_settings` 的 `str(value)` 改成 `value` | `test_project_override_beats_the_global_default` |
| 9 | `batch_id=job_id` 改成 `batch_id=None` | `test_plan_variants_writes_k_plans_without_rendering`（`list_by_batch` 取不到任何行） |
| 10 | `_pick_episode` 的 `raise` 改成 `return episodes[0]` | `test_one_variant_failure_does_not_kill_its_siblings` 不红（该用例的集号总是命中）——**这说明 `_pick_episode` 的兜底分支缺一条专属用例**。补一条：把 `_stub_language_and_tts` 的选题替身换成返回 `episode_numbers=[99]` 的角度，断言作业 failed 且 error 含「不在已完成分析的集里」，并对该用例重跑本条变异 |

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
    """规格 §5 #18/#33：单条详情 + 成本账。成本两个数都是恒等推导，故必须与 plan_data 对上。"""
    project_id = _seed_project_with_episodes(memory_db, tmp_path, sample_video, 3)
    harness = Harness(memory_db, tmp_path / "cache" / "analysis", data_dir=tmp_path)
    harness.context.settings.update(_LLM_SETTINGS)
    calls: list[tuple[str, str]] = []
    _stub_language_and_tts(monkeypatch, calls)

    result = harness.rpc(
        "narration.plan_variants",
        {"project_id": project_id, "modes": ["full_narration"], "k": 1},
    )
    _wait_terminal(harness, str(result["job_id"]))
    plan_id = str(plans_repo.list_by_batch(memory_db, project_id, result["batch_id"])[0]["id"])

    detail = harness.rpc("narration.get_plan", {"plan_id": plan_id})
    assert detail["plan"]["id"] == plan_id
    assert detail["plan"]["angle"] == "角度1"
    plan = PlanData.model_validate(detail["plan"]["plan_data"])
    assert detail["cost"] == {
        "copy_llm_calls": 1,
        "tts_calls": len(plan.narration_texts),
    }
    assert len(plan.narration_texts) > 0, "本用例的前提是有旁白槽位，否则什么都没验"


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
| 1 | `plan_cost` 的 `1 if voiced else 0` 改成 `1` | `test_get_plan_of_a_silent_mode_costs_no_llm_call` |
| 2 | `plan_cost` 的 `tts_calls` 改成 `len(plan.timeline)` | `test_get_plan_returns_row_and_cost` |
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
- Modify: `desktop/src/services/client.ts:126-133`
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

`exportApi` 整块替换（`:126-133`）：

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
- Modify: `scripts/verify_modes.py:453-500`
- Modify: `desktop/src/features/narration/useProduceJob.ts`
- Modify: `desktop/src/services/client.ts:108-125`
- Modify: `service/tests/api/test_data_paths.py:18-23`
- Modify: `service/tests/api/test_plan_variants.py`（迁移原 produce 用例）
- Modify: `protocol/schemas/jobs.json`

- [ ] **Step 1: 确认 `produce` 的全部触点**

Run: `cd /d/PersonProjects/DramaClip && grep -rn "narration.produce\|narration\.generate_plans\|_run_produce\|narrationApi.produce\|narrationApi.generatePlans\|exportApi.start" --include=*.py --include=*.ts --include=*.tsx --include=*.json --include=*.md . | grep -v node_modules | grep -v "^./docs/superpowers/plans"`

Expected: 命中 `service/dramaclip/api/narration.py`（Task 6 已删，此处应无）、`protocol/schemas/narration.json`（Task 6 已删）、`protocol/ts/index.ts`（Task 6/8 已改）、`desktop/src/services/client.ts:112,120,129`、`desktop/src/features/narration/useProduceJob.ts:31`、`scripts/verify_modes.py:459`、`service/tests/api/test_data_paths.py:18`、`service/tests/api/test_plan_variants.py`（原 produce 用例）、`docs/03-IPC协议规范.md`、`docs/service/01-传输与API层设计.md`。**逐条对账，一条都不许漏**——`docs/superpowers/specs` 与 `docs/superpowers/plans` 里的历史记述不改（它们是当时的真相）。

- [ ] **Step 2: 迁 `scripts/verify_modes.py`（九模式门禁）**

`scripts/verify_modes.py:453-500` 的模式循环里，把单次派发换成两步派发。原 8 行：

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
        # 规划与渲染已拆开（P-2a）：先规划 K 条角度，再逐条提交渲染。
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
            rec = {"mode": mode, "status": job["status"], "phase": "plan",
                   "elapsed_s": round(time.time() - started, 1), "error": job.get("error")}
            failures.append(f"{mode}: 规划未完成（{job['status']} · {job.get('error')}）")
            rows.append(rec)
            continue
        plan_ids = [str(row[0]) for row in ctx.conn.execute(
            "select id from narration_plans where batch_id=? order by variant_index",
            (str(resp.result["batch_id"]),)).fetchall()]
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
        job = max((wait_job(ctx.job_store, job_id, args.job_timeout) for job_id in export_jobs),
                  key=lambda item: 0 if item["status"] == "completed" else 1)
```

（`max(..., key=...)` 的口径是"有失败就报失败"：`completed` 排 0、其余排 1，取最大即优先暴露失败行。这比"取最后一条"诚实——`--variants > 1` 时最后一条恰好成功会掩盖前面的失败。）

在 `argparse` 的参数区（与 `--modes` / `--job-timeout` / `--out` 同处）加：

```python
    parser.add_argument("--variants", type=int, default=1,
                        help="每模式规划几条角度（P-2a 的 K）。门禁默认 1，与九模式口径一致")
```

`export_jobs` 的查询（原 `:482-484`）保持不动：它取"最新一条已完成出片记录"并校验模式对得上，两步派发之后这个语义不变。

- [ ] **Step 3: 迁 `protocol/schemas/jobs.json` 的 job 类型词表**

`JobInfo.properties.type.description` 改为：

```json
          "description": "prescreen|analysis|semantic|narration|export|model_download"
```

（去掉 `produce`：那个 job 类型随 `narration.produce` 一起消失，`plan_variants` 复用既有的 `narration` 类型。补上 `semantic`：`api/analysis.py:223` 一直在写它，词表却从没登记——这是本批次顺手修掉的既有文档缺陷。）

- [ ] **Step 4: 迁前端唯一的生产调用点**

`desktop/src/services/client.ts` 的 `narrationApi` 整块替换（`:108-125`）：

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

文件顶部的 `@dramaclip/protocol` 类型 import 里加 `PlanDetail`、`PlanVariantsResult`，去掉不再使用的 `NarrationMode`（若 `planVariants` 的形参仍在用则保留）。

`desktop/src/features/narration/useProduceJob.ts` 整文件替换：

```ts
/** 出片任务：规划 K 条角度 → 提交渲染 → 轮询全部导出作业（页面离开不影响后端执行）。
 *
 * P-2a 把后端的 narration.produce 拆成了 plan_variants + export.submit，本 hook 因此
 * 从"轮询一个作业"变成"轮询一串作业"。**这不是新 UI**：进度条、文案、成功/失败提示
 * 全部沿用原样，只是数据源换了。剧空间④ 与队列页的正式改写在 P-3 / P-2.5。
 */
import { App as AntdApp } from 'antd';
import { useCallback, useState } from 'react';
import type { AnalysisJobStatus, NarrationMode } from '@dramaclip/protocol';
import { analysisApi, exportApi, narrationApi } from '../../services/client';

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

const POLL_MS = 1500;
const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

async function waitJob(jobId: string): Promise<AnalysisJobStatus> {
  for (;;) {
    const status: AnalysisJobStatus = await analysisApi.status(jobId);
    if (TERMINAL.has(status.status)) return status;
    await sleep(POLL_MS);
  }
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

  const start = useCallback(
    async (modes: NarrationMode[]): Promise<void> => {
      if (modes.length === 0 || producing) return;
      setProducing(true);
      setPercent(0);
      setStageText('规划取材角度');
      try {
        const planned = await narrationApi.planVariants(projectId, modes);
        const planJob = await waitJob(planned.job_id);
        if (planJob.status !== 'completed') {
          // 规划作业 failed 时 error 里已逐条点名到「模式·角度」，原样给出即可
          message.error(planJob.error ?? '规划失败');
          return;
        }
        const plans = await narrationApi.listPlans(projectId, planned.batch_id);
        if (plans.length === 0) {
          message.error('规划没有产出任何方案');
          return;
        }
        setStageText(`提交 ${plans.length} 条方案渲染`);
        const submitted = await exportApi.submit(plans.map((plan) => plan.id));
        for (const item of submitted.rejected) {
          message.warning(`方案 ${item.plan_id.slice(0, 8)} 未提交：${item.reason}`);
        }
        if (submitted.exports.length === 0) {
          message.error('没有方案可渲染');
          return;
        }
        // 逐条等：进度取全部作业的平均，与原先"一个作业的进度"在观感上同级
        const statuses: AnalysisJobStatus[] = [];
        for (const [index, entry] of submitted.exports.entries()) {
          setStageText(`渲染中 ${index + 1}/${submitted.exports.length}`);
          statuses.push(await waitJob(entry.job_id));
          setPercent(Math.round(((index + 1) / submitted.exports.length) * 100));
        }
        const failed = statuses.filter((status) => status.status === 'failed');
        if (failed.length > 0) {
          message.error(`${failed.length} 条出片失败：${failed[0].error ?? ''}`);
        } else {
          message.success('出片完成，成品已入作品库');
        }
        await onFinished();
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      } finally {
        setProducing(false);
        setStageText('');
      }
    },
    [message, onFinished, producing, projectId],
  );

  return { producing, percent, stageText, start };
}
```

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

- [ ] **Step 6: 迁 `tests/api/test_plan_variants.py` 里的原 produce 用例**

原 `test_produce.py` 里那些打 `narration.produce` / `narration.generate_plans` 的用例，按下面对照表逐条处置。**不许整块删除**：它们各自钉着一条真实不变量，只是入口换了。

| 原用例 | 处置 |
|---|---|
| `test_produce_renders_work_end_to_end` | 改成两步（`plan_variants` → `list_plans` → `export.submit` → 等 export job），断言原样保留（`export.list` 有 completed 行、`output_path` 是文件、`list_works` 含该项目）。重命名为 `test_plan_then_submit_renders_work_end_to_end` |
| `test_produce_invalid_mode` | 方法名换成 `narration.plan_variants`，错误码仍是 `-32302`。重命名为 `test_plan_variants_invalid_mode` |
| `test_style_selection_runs_once_per_job` | 方法名换成 `narration.plan_variants`；桩掉的对象从 `narration_api._generate_one` 换成 `narration_api._plan_one`（签名不同，桩用 `lambda *_a, **_k: (PlanData(mode="raw_clip"), [])`，因为 `_plan_one` 返回二元组）。断言 `len(calls) == 1` 不变 |
| `test_style_selection_only_paid_for_modes_that_narrate` | 同上换方法名与桩；`_plan_one` 的桩返回空时间轴的 PlanData，作业会以「没有可用素材」失败，终态由 `_wait_terminal` 兜住（该用例本来就只数选题请求） |
| `test_only_sound_only_modes_skip_tts_group` | **整条删除**：`_NO_TTS_MODES` 的"分组并行"用途随 `_run_generation_parallel` 一起消失。`_NO_TTS_MODES` 本身保留（`_NARRATION_MODES` 仍由它派生，用于口味层设闸），另补一条钉住派生关系的用例：`assert narration_api._NARRATION_MODES == frozenset(narration_api.SUPPORTED_MODES) - narration_api._NO_TTS_MODES` |
| `test_every_supported_mode_has_a_chinese_label` | 原样保留（两面镜子都还在） |
| `test_style_directives_reach_the_copy_prompt` | 入口从 `_inject_run_settings` + `_generate_one` 换成 `_inject_run_settings` + `_plan_one`，多传一个 `brief`：`angles.AngleBrief(name="复仇线", reason="第 1 集最狠", hook="他跪着进了门", episode_numbers=[1])`。原断言全部保留，并**新增一条** `assert "复仇线" in prompt`（角度与风格是两个独立注入，各钉一条）。落库断言从 `_newest_ready_plan` 换成 `plans_repo.list_by_project(...)[0]` |
| `test_dialogue_without_transcript_fails_loudly` | `_generate_one` → `_plan_one`，`episode_inputs` 传 `[]`，`brief` 同上。断言 `pytest.raises(ValueError, match="都没有转写")`（`_plan_one` 的 dialogue 分支对空 `scoped` 抛的是这句，与原先 `_generate_one` 的「没有带转写的已完成集」不同——**按新代码的实际文案断言，不要沿用旧串**） |
| `test_pinned_style_survives_a_project_without_transcripts` | 原样保留（它只打 `_inject_run_settings`，与拆分无关） |
| `test_dialogue_unconfigured_llm_fails_the_plan` | `_generate_one` → `_plan_one`，多传 `brief`（`episode_numbers=[1]`）。`pytest.raises(LlmUnavailable, match="引擎")` 保留 |
| `test_assembly_failure_lands_in_jobs_table` | `@pytest.mark.parametrize("method", [...])` 的两个方法名换成 `["narration.plan_variants"]`（`generate_plans` 已不存在，参数化只剩一项——**保留 parametrize 结构**，P-2b/P-3 若再加规划入口可直接扩列表） |
| `test_produce_runner_raise_still_settles_the_job` | 方法名换 `narration.plan_variants`；注入点仍是 `harness.context.notifier.progress`——但 `_run_plan_variants` 不调 `notifier.progress`（它只调 `job_store.set_progress`），故改注入 `harness.context.job_store.set_progress` 抛 `RuntimeError("进度写不进去")`，断言 error 含该串、作业 failed、`cancel_events` 已释放。重命名为 `test_plan_variants_runner_raise_still_settles_the_job` |
| `test_generation_runner_raise_still_releases_cancel_event` | 同上换方法名与注入点。重命名为 `test_plan_variants_bookkeeping_raise_releases_cancel_event` |
| `test_bookkeeping_error_never_replaces_the_original` | 方法名换 `narration.plan_variants`；`monkeypatch.setattr(narration_api, "_generate_one", ...)` 换成 `_plan_one` 的桩（返回空时间轴二元组），`mark_completed` 的注入原样保留 |
| `test_tts_failure_fails_one_mode_not_the_batch` | **由 Task 6 的 `test_one_variant_failure_does_not_kill_its_siblings` 与 `test_one_mode_failure_does_not_kill_other_modes` 两条取代，整条删除**。它验的"失败粒度=单条方案"在变体级比在模式级更细，旧断言（`rendered == ["intro_narration"]`）依赖已删除的渲染耦合 |

- [ ] **Step 7: 跑测试**

Run: `cd service && ../.venv/Scripts/python.exe -m pytest -q`

Expected: PASS（`tests/api/test_analysis.py` 的既有隔离 flake 除外）。

Run: `cd service && ../.venv/Scripts/python.exe -m pytest tests/transport/test_contract_sync.py -q`

Expected: PASS —— 契约两侧至此对齐（Python 少两个方法、schema 少两个方法；Python 多两个、schema 多两个）。

Run: `cd /d/PersonProjects/DramaClip && npm run typecheck && npm run test`

Expected: `tsc --noEmit` 两个 project 都无错；`vitest run` 全绿，含 `desktop/src/__tests__/contract.test.ts` 的「METHOD_NAMES 与 protocol/schemas 的 x-methods 一致」。

Run: `cd /d/PersonProjects/DramaClip && npm run lint`

Expected: 无错。`useProduceJob.ts` 改写后若报 `max-lines-per-function`（单函数 ≤ 60 行，docs/04 §1），把 `start` 回调里"提交并等待全部导出作业"那一段抽成同文件内的模块级 `async function submitAndWait(...)`，**不要用 eslint-disable 绕过**。

- [ ] **Step 8: 提交（Task 6 + 7 + 8 + 9 合成一个提交）**

Task 6 的 Step 10、Task 7 的 Step 4、Task 8 的 Step 9 都只暂存不提交，就是为了这里。契约同步本身在 Task 6 结束时已经两侧对齐，**真正让这个提交不能拆开的是三处调用点**（Task 6 Step 9 已列）：`desktop/src/services/client.ts` 的 `MethodName` 类型会让 `npm run typecheck` 红、`scripts/verify_modes.py` 会在运行时拿到 `-32601`、以及 `test_plan_variants.py` / `test_data_paths.py` 里尚未迁移的旧用例会让 `pytest` 红。三者都在本任务里收口，故四个任务合成一个可独立构建的提交（docs/04 §4）。

Run: `git status --short`

Expected: 暂存区含 Task 6/7/8 的全部路径，加上本任务改的 5 个文件；**不含**另一位工程师的 `scripts/verify_e2e.mjs`、`scratch/`、`tests/api/test_analysis.py`、`docs/07-*`。若含，`git restore --staged <路径>` 逐个撤出。

```bash
git add scripts/verify_modes.py desktop/src/features/narration/useProduceJob.ts desktop/src/services/client.ts protocol/schemas/jobs.json service/tests/api/test_data_paths.py service/tests/api/test_plan_variants.py
git commit -m "feat(api)!: produce 拆成 plan_variants + export.submit，规划与渲染就此分开

BREAKING CHANGE: 删除 narration.produce / narration.generate_plans / export.start，
新增 narration.plan_variants / narration.get_plan / export.submit。
调用点（scripts/verify_modes.py、desktop useProduceJob）同批迁移，不留并存灰度。
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

- [ ] **Step 6: 死码对账**

Run: `cd service && grep -rn "generate_plans\|_run_generation_parallel\|_generate_one\|_newest_ready_plan\|_run_produce\|narration.produce" dramaclip/ --include=*.py`

Expected: 无输出。

Run: `cd /d/PersonProjects/DramaClip && grep -rn "export.start\|exportApi.start" desktop/src protocol --include=*.ts --include=*.tsx --include=*.json`

Expected: 无输出。

Run: `cd service && grep -rn "降级\|兜底\|回退" dramaclip/engines/narration/angles.py dramaclip/engines/narration/overlap.py`

Expected: 无输出——**本批次新增的两个模块里不许出现任何降级语义**。规格 §3.3.1 的禁止级已经全是抛错，选题与度量两层不得重新引入模板或规则兜底。

- [ ] **Step 7: 提交**

```bash
git add docs/03-IPC协议规范.md docs/service/01-传输与API层设计.md docs/service/04-数据模型.md docs/superpowers/plans/2026-09-12-p2-plan-render-split.md
git commit -m "docs: 方法清单/错误码/迁移登记随 produce 拆分收口，并登记 tts_segments 死列"
```

---

## Task 11: 真机复验（P-2a 出口）

不产新代码，只产证据。**先决条件：P-1.5 Task 10 的九模式门禁已闭环、机器上没有别的门禁在跑**（本任务要真跑 LLM 与 ffmpeg，CPU 争用会让两边的时序断言都不可信）。

- [ ] **Step 1: 只跑规划，确认"不渲染"是真的**

Run: `cd /d/PersonProjects/DramaClip && .venv/Scripts/python.exe scripts/verify_modes.py --modes full_narration --variants 3 --out D:/tmp/dc-p2a-plan > /tmp/p2a-plan.log 2>&1; echo REAL_EXIT=$?`

Expected: 门禁本身会因为"只规划不渲染"而报没有成品（`no-export` 或类似），**这正是本步骤要看到的**——它证明规划阶段确实一条片都没渲。日志里应能看到 3 条角度的规划留痕。

**不要用 `| tail` 判退出码**（管道退出码是 `tail` 的，P-1.5 真踩过）。

- [ ] **Step 2: 人工核三条角度真的互异**

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

- [ ] **Step 4: 用耳朵验收一条（不可省略）**

至少人工听 Step 3 出的那条 `full_narration`，确认：① 旁白没有被原声盖住；② 没有因 `normalize=0` 带来的爆音；③ **解说内容与角度名对得上**（这是本批次唯一能靠耳朵验的东西——重叠率是数字，"这条片是不是在讲它宣称的那个卖点"只能听）。

把结论写进 Step 5 的记录里——**写"已听，结论 X"，不接受"断言全绿所以应该没问题"**。

- [ ] **Step 5: 把实测写回本计划并清理临时目录**

在本文档末尾追加 `## Task N 落地后的实测修正` 小节（与 P-1.5 同一体例），记录：三条角度的实测名字与 `overlap_max`、选题 prompt 的实际形态、与预期不符之处、以及计划里被证伪的假设（如有）。

清理。临时目录由 `_same_drive_temp` 创建，**首选 `dir=REPO`，所以它们落在仓库根**。其中 `tmp_dc-verify-data_*` 里有一个名为 `models` 的目录联接指向真实的 `data/models`——**顺序不可颠倒**：先 `rmdir` 摘掉联接，再 `rm -rf` 目录；反过来会顺着联接删掉开发者的模型。

```bash
cd /d/PersonProjects/DramaClip
for d in tmp_dc-verify-data_*; do cmd //c "rmdir $(cygpath -w "$PWD/$d/models")" 2>/dev/null || true; done
rm -rf tmp_dc-verify-data_* tmp_dc-verify_* D:/tmp/dc-p2a D:/tmp/dc-p2a-plan
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

### P-2c：单条方案内的跨集拼接

P-2a 让**角度之间**跨集（不同角度取不同集），但六个单集模式的**单条方案内**仍限于一集，因为它们的编排器签名是 `(episode_id, scenes, strategy)`。要真正做到"一条片跨集取画面"，得让 `ConflictScore` 带上集身份、或让编排器接受"每集一组场景"，并重新分配时长预算（`_fit_duration` 现在按 `strategy.max_duration_s` 截断单集场景，多集直接叠加会超预算数倍）。

**为什么不在 P-2a 里做**：它改成片形态，而九模式真机门禁的出口判据（时长窗、响度窗、冻结帧）正压在这个形态上。P-1.5 Task 10 尚未闭环时改成片结构，等于把两批的验收证据混在一起，出问题时无法归因。**P-2c 必须在 P-1.5 出口闭环之后、且自己带一轮九模式门禁。**

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
