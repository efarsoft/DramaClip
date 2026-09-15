# P-3.1 导航壳与工作台开工页 · 结题记录

> **状态**：Task 1-9 ✅ 完成（2026-09-11）；**Task 10 手工验收 ✅ 已执行**（2026-09-15，实测见 §3 末尾「落地后的实测」；M4/M8 局部与 M9 按计划口径由单测覆盖记录，发现①移交分析域）。
>
> 本文件已由 4008 行分步实施计划**清理为结题记录**（2026-09-11）：分步代码样例使命已尽，代码与测试即事实源。
> 清理前完整原文：`git show 7bb9f3a:docs/superpowers/plans/2026-09-12-p3-1-nav-shell-and-workbench.md`。
>
> 规格出处：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §2.1/§2.2/§3.2/§3.3/§4.1/§9.1/§9.5；
> 拆分依据：`docs/superpowers/plans/2026-09-12-p3-decomposition.md`；视觉真相源：`docs/desktop/04-设计系统方案.md`（DSS v1）。
> 执行时机裁决原文中"Task 9 的手工浏览器步骤"为笔误，实指 Task 10（Task 9 只跑 grep 与文档同步）。

## 1. 交付与提交（分支 feat/correctness-wiring）

| Task | 内容 | 提交 |
|---|---|---|
| 1 | 导轨清单化：`navItems.ts` 唯一真相源 + Rail 抽出 + 前缀高亮 + 作品→成品 | 4e422c0 |
| 2 | 路由表清单化 + 重定向表驱动 + iaContract 三方守卫 | 4bddfee |
| 3 | 假文案清零（"关键词降级"谎言）+ copyTruth 永久门禁 | 7002d23 |
| 4 | 待办接通 jobs.list + 可执行动作化（删只通知的 useTodos） | b428c08 / 933eeb9 / 8dcb971 |
| 5 | 三统计芯片 + ETA 线性外推（全退化边界守卫） | 26c0993 |
| 6 | useWorkbench 装载器 + TodoList/StatChips 视图 | 24d30e7 |
| 7 | createDrama + lastDrama + EmptyWorkbench + ContinueCard | ef9e355 |
| 8 | 工作台整页重写 + 删五个死组件与假工具箱面板 | 113afb2 |
| 9 | jobs.list 取不到不谎报 0 + 分层守卫 + 渲染层文档同步 | 2732451 |

门禁终态：vitest 17 文件 114 条全绿 / `tsc` 零错误 / `eslint` 零输出。

关键产物：

- **IA 数据层**：`app/navItems.ts`（导轨清单）、`app/routes.ts`（路由 + 重定向表，叶子模块，禁 import 本地模块——iaContract 守卫）
- **派生层**（不碰 RPC 的纯函数）：`features/home/todos.ts`（五类待办各带动作）、`stats.ts`（三芯片 + ETA 外推）
- **装载层**：`features/home/useWorkbench.ts`（五源并发、`jobsAvailable`/`jobsError` 诚实透传、服务端时钟优先）
- **视图**：`TodoList` / `StatChips` / `EmptyWorkbench` / `ContinueCard` / `relativeTime.ts`
- **偏好**：`stores/lastDrama.ts`（继续上次，localStorage 三函数，坏数据退化 null）
- **契约**：protocol/ts 增 `JobInfo`/`JobStatus`/`JobsListResult{jobs, server_time_ms}`；`jobsApi.list(limit)`
- **守卫**：`app/__tests__/iaContract.test.ts`（导轨↔路由↔router 三方一致 + 分层纪律两条）、`src/__tests__/copyTruth.test.ts`
- **删除**：StartCards / TodoCard / useTodos / RecentProjects / SectionTitle 五个死组件 + EnvPanel 假工具箱（三项全是导轨重复跳转）
- **theme 唯一新增 token**：`fontEmptyIcon: '48px'`（DSS §3.5 空态图标）

## 2. 执行核对记录（2026-09-11，与业主逐条核实过）

### A. 计划缺陷 11 处（执行时已修正落地）

| # | 位置（原文行号） | 问题 | 处置 |
|---|---|---|---|
| A1 | L1764 vs L1780 | 同一 90 分钟在"取最慢"用例期望 `90 分`、在格式化用例要求 `1 小时 30 分`，实现只能满足其一 | 格式化规则以专门用例为准；"取最慢"用例期望改 `1 小时 30 分`，其选择逻辑断言保留 |
| A2 | L2018 | `renderList` 忘返 render 结果，5 个解构 `container` 的用例 TypeError | `return { ...view, onNavigate, onRestartService }` |
| A3 | L2035 | 两条 item 同名动作「去处理」撞 `getByRole` 唯一性 | 第二条改「去下载」，各自断言唯一命中 |
| A4 | L2070/2075/2078 | hex 色值断言在 jsdom 必败（cssstyle 规范化为 rgb()） | 断言写 `rgb(248, 113, 113)` 等形式，hex 留注释 |
| A5 | L2507 测试 vs 实现样例 | `folderName('D:\')` 按样例实现返回 `'D:'`，满足不了自家测试的 `'新剧'` | 实现补盘符判定 `/^[a-zA-Z]:$/` |
| A6 | L2840 vs L2647 | 样例文案「不做下载与网盘对接」含禁词「网盘」，照抄必被同 Task 门禁拦下 | 文案改「素材已在本地，无需任何额外录入。」 |
| A7 | L2616 | `renderEmpty` 同 A2 忘返 container；`textContent ?? ''` 吃 no-unnecessary-condition | 同 A2 修法；去 `?? ''` |
| A8 | Task 7 loading 用例 | antd 6 `<Button loading>` 不写 HTML disabled 属性 | 组件补 `disabled={creating}` |
| A9 | L1960/2439/2989/2999/3424/3707/3795 | 全量计数链失准且 Task 7 内部 115/118 自相矛盾；每步**增量**全对，错在假设基线高 13 条 | 以"增量正确 + 全绿"为准，按实际数提交（74/87/105/105/114） |
| A10 | L3724 vs L2666 | 清扫 grep 含 `StartCards` 却期望零输出，而自家 createDrama 样例 docstring 就提它 | 口径改"无代码引用、仅注释提及"；出处注释保留 |
| A11 | Task 5 Step 5 变异 1 | `WORKS_SCAN_LIMIT` 改 10_000 不可能红——夹具用同一常量构造，变异结构性不可观测 | 该常量一致性由"测试导入常量"保证，不作变异验证 |

### B. 计划自我更正 3 处（正文原样保留"不要照抄"更正块，按更正落地）

Task 8 Step 1 的三处：`failedJobs` 形参缺 `status` 且带恒真废过滤；`EnvPanel` 被喂假值（`llmBaseUrl={...'set'...}`/`ttsEngine="edge"`）——回改 Task 6 的 useWorkbench 加真实字段；`gap: tokens.spaceMd + 2`（=14）非 DSS 栅格值。计划 L3196 明示"不要照抄"，L3964 自注错误形状系有意保留。

### C. 我方实现与计划的偏差 4 处（非计划缺陷）

| # | 事项 | 说明 |
|---|---|---|
| C1 | `keys` 助手签名 | 计划定义 `(input: TodoInput) => buildTodos(input).map(...)`，其 Task 9 片段在该签名下自洽；我早期实现定义成 `(items: TodoItem[]) => ...`，套用计划片段才炸。按已提交实现收口 |
| C2 | JobsListResult 的 `total` | 计划 L289-291 写的就是 `{jobs, server_time_ms}`（与服务器一致）；`total` 是我早期转录笔误，Task 6 接线时改正 |
| C3 | serviceDown 待办 key | 计划 `'service-down'`（L1562）vs 我实现 `'svc'`（todos.ts，落地早于计划细读）。Task 9 测试按已提交实现写 `['svc']` |
| C4 | 'produce' 任务类型 | 计划 L1160-1165 有预判与处置规则（"谁后落地谁收口"）。实测 P-2 已先合入（服务端 job_type 无 produce），按规则执行删除分支：JOB_ROUTES 去 produce、测试改名「narration 失败 → 跳出片页」 |

### D. 沉淀的计划写作纪律（后续写计划的硬规矩）

1. **样例测试代码必须真跑过再进计划**——A2-A4/A7 这类笔误（忘返回值、重名撞断言、环境序列化差异）占了缺陷的一半，跑一遍即可全歼。
2. **同一行为的全部用例先交叉对账**——A1 的"同一输入两种期望"在写完时对比一遍即可发现。
3. **验收断言写增量、不写绝对值**——A9/A10 均因拿假设基线当事实；凡代表真实工具输出的夹具一律现场捕获（沿 P-1.5 计划纪律）。

## 3. Task 10 手工验收清单（✅ 已执行 2026-09-15）

**前置**：九模式真机门禁跑完。`npm run dev`（Vite 固定端口 5180，Electron 自动拉起；若状态栏红点，待办首条会是「Python 服务不可用」+ 重启按钮——那是 M7 的真实样本，先记录再排查）。

- **M1 导轨形态**：5 项（工作台/项目/成品/引擎/设置），图标上两字标签下；成品与引擎之间一条浅色分隔线；无「作品」、无斜杠复合词；无「队列/工具箱/关于」。
- **M2 高亮·引擎深链**：`#/engines` 高亮；`#/engines/llm` 仍高亮且 LLM tab 选中；工作台右栏「去下载」落 `#/engines/asr` 保持高亮。
- **M3 高亮·单剧详情**：项目→任一剧卡，`#/projects/<id>/analysis` 保持「项目」高亮。
- **M4 旧路径一跳**：手输 `#/models/llm` → `#/engines/llm`（replace 不 push，历史只多一条）；`#/models` → `#/engines`。
- **M5 工作台结构**：页头「工作台」+问候行+右上唯一 primary「新增项目」；主区=待办(有才出现)→三芯片→最近成品→继续上次；右栏无「工具箱」面板；无「开始创作」三卡、无「最近项目」列表。
- **M6 三芯片对账**（只读 SELECT，不写库）：
  ```bash
  ./.venv/Scripts/python -c "import sqlite3;c=sqlite3.connect('data/data.db');print('projects',c.execute('select count(*) from projects').fetchone()[0]);print('works',c.execute(\"select count(*) from export_jobs where status='completed' and output_path is not null\").fetchone()[0]);print('export_jobs_all',c.execute('select count(*) from export_jobs').fetchone()[0])"
  ```
  芯片「部剧」=projects、「条成品」=works；works 与 export_jobs_all 不相等恰好证明不用 dashboard_summary.export_count 的理由。
- **M7 待办逐条点**：先查失败样本（`select id,type,ref_id,status,substr(coalesce(error,''),1,80) from jobs where status='failed' order by updated_at desc limit 5`）；有 analysis/prescreen/narration 失败行→待办悬浮显 error 原文、「去处理」落对页；**无样本则如实记"未验证，由 todos.test.ts 覆盖"，不要人为制造失败**。无条件可验的两条：引擎总览「文案 LLM」卡不含「关键词降级」；LLM tab 的降级说明段常驻且逐字正确。
- **M8 继续上次**：开剧→回工作台→底部「继续上次/剧名/N 分钟前」→点击回分析页；localStorage 有 `dramaclip.last-drama`（id/name/visitedAtMs）；手工改坏为 `{"id":"nope"}` 后刷新→不渲染且不出现 `/projects/undefined/`。
- **M9 空态（有条件）**：**不为验证删唯一剧**（§3.4 唯一不可恢复动作）。默认记"由 EmptyWorkbench.test.tsx 4 条覆盖"；愿意可用 `DRAMACLIP_DATA_DIR` 指空目录演练：主区整块变空态引导、页头无 primary、待办仍在。
- **M10 同构对照 + M11 控制台**：工作台/成品库/引擎/设置四页截图两两并排——页头同形、竖条标题同形、每屏 primary≤1、纵向节奏只有 20/24（已知不达标：ProjectsPage 与 ProductionPage 的手写页头，归 P-3.2，照实记录不越界改）；DevTools Console 零红色报错（特别是不出现 `未知 RPC 方法: jobs.list`）。
- **Step 12 实测写回**：M6 三个数、M7 验到与否、M10 不达标页、被证伪的假设（"计划说 X，实测是 Y，改成了 Z"），追加到本文件末尾；关 dev server、确认无残留 Electron 进程。
- **Step 13 提交**：`git add docs/superpowers/plans/2026-09-12-p3-1-nav-shell-and-workbench.md && git commit -m "docs(plan): 记录 P-3.1 手工验收实测与偏差"`。

## 4. 完成判据（1-5 全部满足；P-3.1 收口）

1. ✅ vitest 全绿（实际基线：17 文件 / 114 条；原计划按假设基线写 18/127，见 A9）。
2. ✅ typecheck 与 lint 零输出、退出码 0。
3. ✅ `contract.test.ts` 仍绿——本片未动 `METHOD_NAMES`。
4. ✅ 死引用四条 grep 符合期望（死组件仅注释提及、dashboardSummary 仅剩定义行、restartService 有唯一消费者、竖条标题收敛为 PageSection 一份）。
5. ✅ Task 10 已执行（2026-09-15，§6）：M1-M3/M5-M7/M8 上半/M10 真机通过；M4/M9/M8 局部按计划口径由单测覆盖记录；M11 的两条报错全部归因于发现①（分析域启动时序，移交），非本片回归。
6. ✅ `git status --short` 干净，全程只用显式路径 `git add`。

## 5. 已知不做 / 归属账本

- 「队列」「工具箱」「关于」导轨项与页面：P-2.5 / P-3.4 / P-3.6。
- `/projects`→`/dramas` 与 `/projects/:id/*`→`/drama/:id/*` 改名：P-3.2（波及属他人的 features/analysis）。
- 「项目」标签不改「剧库」：§4.2 页面内容要 P-2 阶段聚合，只改名等于标签许诺页面没有的东西。
- 待办两个来源：「已分析未规划」（要 project.list 阶段聚合）、「队列失败任务」（ref_id 异构 + 落点队列页）：P-2.5。
- 最近成品钩帧缩略图：要 `export.set_cover` 与 list_works 增 cover_path：P-3.3。
- 修 `projects_repo.summary` 的 export_count 无状态过滤（要动 DashboardSummary 形状）：P-3.3。
- `ProjectsPage`/`ProductionPage` 手写页头收敛与 `folderName` 上提共享：P-3.2。
- §4.2 首启三步空态（属剧库页）：P-3.2；§9.7 规模实测（无造数脚本）：建议 P-3.2 Task 0。
- 导轨/状态栏运行中角标：落点队列页，P-2.5（本片不预留 badge 字段——没有消费者的字段是投机设计）。

## 6. Task 10 落地后的实测（2026-09-15，dev 栈真机）

环境：`npm run dev`（Vite 5180 + Electron + Python ready），启动清扫正确处理 1 个中断任务与 1 个未完成导出。验收素材：小小球神不好惹（10 集全 done、45 条成品）。

**逐项结果**：

| 项 | 结果 | 证据 |
|---|---|---|
| M1 导轨形态 | ✅ | 5 项图标上/标签下；成品与引擎之间浅色分隔线；无「作品」、无队列/工具箱/关于 |
| M2 引擎深链高亮 | ✅ | `#/engines` 高亮；页内点「文案 LLM」→ `#/engines/llm` 「引擎」保持高亮且 tab 选中 |
| M3 单剧详情高亮 | ✅ | 剧卡 → `#/projects/:id/analysis` 「项目」保持高亮 |
| M4 旧路径重定向 | ⚠️ 未真机演练 | DevTools 在 frameless 窗口无法以合成键打开；由 routes 单测（LEGACY_REDIRECTS/LEGACY_PARAM_REDIRECTS + iaContract）覆盖 |
| M5 工作台结构 | ✅ | 页头唯一 primary；待办→三芯片→最近成品→继续上次；无工具箱面板/开始创作三卡/最近项目列表 |
| M6 三芯片对账 | ✅ | 芯片 1 部剧 / 0 条在跑 / 45 条成品·本周+45 ≡ SQL `projects=1` / `works=45`；**`export_jobs_all=48 ≠ 45` 实证不用 export_count 的理由**；启动清扫后 0 在跑、无 ETA 行符合预期 |
| M7 待办逐条点 | ✅ | 待办 6 条 ≡ DB failed 明细（3 条 narration 429 + 3 条服务中断；export 3 条失败正确排除）；title 挂完整 error 原文（a11y 全文核对）；narration「去处理」正确落到出片中心（出片记录含失败行+原因徽标）；引擎总览 LLM 卡「云端 · qwen3.7-plus」无「关键词降级」；LLM tab 金色说明段**逐字核对通过**（该段原系 Task 3 遗漏，本次验收发现并补上，964385f） |
| M8 继续上次 | ✅ | 进剧→回工作台出现「继续上次 / 小小球神不好惹 / 刚刚」，href 指向分析页；localStorage 形状由 lastDrama 单测覆盖（DevTools 同 M4 未开） |
| M9 空态 | ⚠️ 免演练 | 按计划记「由 EmptyWorkbench.test.tsx 4 条覆盖」 |
| M10 同构对照 | ✅（含预期内不达标） | 工作台/引擎/成品/设置四页页头与竖条标题同形、每屏 primary≤1；ProjectsPage 与 ProductionPage 手写页头不达标——预期内，归 P-3.2 |
| M11 控制台 | ❌ 已归因 | 两条 `Uncaught (in promise)`（-32603 / -32101），全部来自发现①的启动时序窗口，非本片回归 |

**发现与处置**：

1. **分析工作台首进偶发空态（移交分析域，非本片回归）**：服务启动早期窗口内 `project.get` 曾抛 `-32101 项目不存在` / `-32603`（一次性；重进即恢复；同刻 DB 直查与 repo 层复现均正常、10 集俱在）。根因在 `useAnalysisWorkspace` 的加载 effect 只依赖 `serviceState`——失败后不再重试，页面停留在「共 0 集 / 暂无剧集」。属 `features/analysis/**`（他人域），登记 P-3.2 / 分析域负责人处置（失败重试或 entered-route 重载）。
2. **Task 3 遗漏补齐（964385f）**：7002d23 删假文案时未按计划补 `UnconfiguredNotice` 常驻说明段，M7 验收抓出，已补并逐字核对。
3. 计划假设证伪记录：「DevTools 可开」不成立（frameless 窗口合成按键被拒）→ M4/M8 的 hash/localStorage 细节按计划既有口径转由单测覆盖；其余无新增（A1-A11 见 §2）。

**M6 对账读数**：projects 1 / works 45 / export_jobs_all 48（48≠45 即 `dashboard_summary.export_count` 不可用的真机实证）。

**收尾**：dev 栈已停，无残留 Electron 进程。本节即 Step 12/13 的提交内容。
