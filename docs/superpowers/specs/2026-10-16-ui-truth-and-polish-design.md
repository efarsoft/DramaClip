# DramaClip 桌面 UI 真相与质感批次 · 设计规格

**日期**：2026-10-16 · **状态**：待用户审阅 · **上位文件**：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md`（信息架构与页面职责）、`docs/superpowers/specs/2026-09-21-desktop-typography-density-design.md`（排版与密度定案）、`docs/desktop/04-设计系统方案.md`（DSS v1 视觉真相源）
**起因**：业主原话「UI 方面我想仔细打磨下，你有什么好的方案，可以大胆规划」，随后追加「UI/UX 细节都需要完善和优化，如果布局不合理，也可以大胆调整」。
**本文件不推翻** 09-10 与 09-21；冲突时**结构以 09-10 为准、token 与状态契约以 09-21 为准**，本文件只在两者未覆盖处立法（降级留痕的存储与界面落点、卡片形态选型、阶段语言归一、组件家族）。
**与路线图的边界**：与 `docs/05-开发路线图.md` 的 P3 批次表**互不合并**（那份由业主自维护）。

**范围裁决（业主亲手收窄，三次点头）**：
1. 轴向 = **三档串行全做**（真相可见性 → 质感细节 → 结构与家族）。
2. 宿主屏 = **「1+4」**：建队列页 **且** 一次还完 IA 债（导轨第 8 项、剧库 `/projects`→`/dramas`、分析/出片合一为剧空间）。
3. 验收 = **分档定口径**：档1 纯机器契约、档2 真机 + 造数库截图、档3 真机三档宽度。

**路线**：甲（判据先归位 → UI 入口 → 组件家族）。顺序偏离业主最初勾选的一处已当场说明并获认可：**队列页与 IA 债排到最后（档3）**，理由见 §0.3。

---

## 0. 根因、批次顺序与口径

### 0.1 三条根因（每条可反证）

1. **允许型降级的账在渲染层当场蒸发**。`api/export.py:67` 的 `_note_degraded` 把「名称 + 后果」的人话经 `notifier.log` 发 `log.append`，并自动绑 `job_id`（`transport/notify.py:53` 的 contextvar）。渲染层没订 `log.append`——`notify.py:54` 的注释自己就写着「通知面渲染层没订上的话业务日志就当场蒸发」。这 10 条账今天无人记账。
2. **「模式 → 文案来源」的判据有第二处真相且已经漂**。`api/narration.py:67` `_NARRATION_MODES` 是集合真相，`scripts/verify_modes.py:125` `EXPECT_PLANNER` 是手抄表（在 `:415`、`:984` 被消费），后者只有 9 条、缺 `highlight_cut`。同一含义两处立法，漂移只是时间问题。
3. **档间分离靠颜色硬撑**。深色底上 `textTertiary` 实测 2.88:1（见 §2 表），过不了 AA；而把它提到达标，与 `textSecondary` 的分离度从 2.52 压到 1.52，**比主/次之间的 1.89 还小**。三档小字在深色底上「既要达标又要分得开」数学上就是挤的——分层方式本身站不住，不是改一个值能解决。

**反证条件**：若 §1 的判据归位与留痕落库上线后，业主仍反馈「看不出哪条是凑出来的」，则真实根因是**判读口径没进界面**（要回来升级本规格），而不是继续加徽章；若 §2 的档位一分为二 + 字号分离在真机截图上仍显廉价，则根因是每屏平级元素过多（信息架构问题，归 09-10 那条线）。这两条必须在验收时显式判定，不许含糊通过。

### 0.2 复算口径与行号约定

- **行号是写作时点工作树的方便定位，不是判据**。别的提交同时在改这些文件，行号必然漂。归段与验收的判据是 **token/函数名 + 文中给出的可复跑命令**；凡计数都在 §0.2 声明的口径上复算，**行号漂移不算读数错误，计数漂移必须重发**。
- **计数口径统一**：扫 `desktop/src/**` 的 `.ts`/`.tsx`，排除 `__tests__` 目录与 `*.test.*`（本文件里标注「含测试」的除外）；`grep -rn` 逐条点名可复算。
- **后端计数口径**：`grep -n "_note_degraded(" service/dramaclip/api/export.py` 命中 **11** 行 = 定义 1（`:67`）+ **调用 10**。写「10 处」时指调用点。

### 0.3 批次顺序（为什么队列页排到最后）

| 档 | 内容 | 验收口径 |
|---|---|---|
| **档1 真相可见性** | 判据归一 + 留痕落库上屏 + 补救入口 + 状态契约 | **纯机器契约**（四条新门禁，每条变异锚定） |
| **档2 质感细节** | 文字档一分为二 + 对比度门禁 + 动效基线 + 焦点/数字排版 + 数值归一 | **真机 + 造数库截图定版** |
| **档3 结构与家族** | 剧空间合一 + 编号归一 + 导轨第 8 项 + 更名 + `StateBlock`/`Overlay`/`cardGrid` + 卡片重排 + 队列页 | **真机三档宽度** |

队列页与组件家族是同一件事的两面：先建屏再抽家族，等于用当前「各屏自写 grid」的写法把第 10 处空态写出来、然后重构它——两遍工；反过来先抽家族是过早抽象（业主反对过）。档1 不等新屏就能解决业主最在意的「看不出文案是谁写的、哪条是凑出来的」，所以它先行且独立可用。

---

## 1. 档1 设计｜判据归位 → 留痕落库 → 补救入口 → 状态契约

### 1.1 判据归位（后端，一处真相）

`_NARRATION_MODES`（`api/narration.py:67`）已经是「哪些模式必须由 LLM 成稿」的唯一真相。要做的是**把它变成可判定的接口**，而不是新建第三份表：

- 在 `api/narration.py` 紧邻 `_NARRATION_MODES` 处加纯函数 `expected_copy_source(mode) -> "llm_script" | "rule"`，由该集合派生。
- `list_plans`（`:94`，返回点在 `:107`，`plan_data` 整份随行）经已有的 `_annotate_gate`（**:110**，它就是「给方案卡补界面要用的字段」的先例）补两键：`copy_source`（原样陈述来源）与 `copy_source_expected`（判据）。**出参里不塞布尔结论**——「是否降级」是界面根据两个来源拼出来的判读，判据本身留一处。
- `scripts/verify_modes.py::EXPECT_PLANNER`（`:125`）手抄表**删掉**，改 `import expected_copy_source`。`highlight_cut` 缺失这一条由构造消失，而不是靠手补。
- **协议面**：`protocol/ts/index.ts` 的 `PlanData` 声明需登记两个新键（TS 类型要用）。`protocol/schemas/narration.json:32-34` 把 `plan_data` 声明为裸 `{"type":"object"}`，Router 对出参**不做校验**（`test_contract_sync.py:45` 记录了这一口径），所以 **`planner`/`copy_source` 都不需要 schema 注册**——这条是已复核结论，不是开放项。

**徽章判读口径（写进规格，避免实施时各自发挥）**：

| 来源 vs 期望 | 界面 |
|---|---|
| 一致 | 不占行 |
| `raw_clip` / `subtitle_flow` / `highlight_cut` 拿到 `rule` | **正常陈述**，文案槽写「无解说」；不得用警示色（这三个模式的 `rule` 是设计本意，见 `_NO_TTS_MODES` `:62`） |
| 期望 `llm_script` 却拿到 `rule` | warning 金 `#FBBF24`，文案「文案来源：规则预算」，**绝不占用钩子红**（既有硬约束） |

`engines/narration/models.py:71` 的 `planner: str = "rule"` 是默认值即「未成稿」，`:74` `dropped_segments: int = 0` 同理要进判读面。

### 1.2 留痕落库（档1 真正的手术点）

`log.append` 订阅**不能当真相源**——重启即失，拿它当账等于造假。分两层，且明确谁是账：

- **账在库**：`_note_degraded`（`api/export.py:67`）除了发通知，同时把 `{名称, 后果}` append 进 `export_jobs` 新列 `degraded_notes`（JSON 数组）。同形先例：`export_jobs.selfcheck` 就是「导出期产出字段」。**10 个调用点一行不动**，全走这一个函数。
- **实时流是通知**：渲染层新增 `log.append` 订阅（照 `stores/ui.ts:62-73` 的既有写法），只服务作业进行中的滚动视图，按 `job_id` 归档并标注「本次会话」。
- 成片卡/队列读 `degraded_notes` 出灰徽章 + 悬浮后果全文。
- **交付一张可复核的表**：`docs` 里「降级点 → 存储字段 → 界面落点」逐行列全，覆盖裁决表所有「允许且必须可见」行。档1 范围 = `export` 链 10 处 + 分析精炼分档回退（转写卡已有「AI 校对」徽标，要核它是否真的把「分档回退」说清楚了）。**不在档1**：GPU/CPU 与模型下载类降级——属引擎中心，落 09-21 §10 那批。

**迁移编号**：下一个可用号是 **023**（`020` 由 commit `18a6463c` 的提交信息明确「留给画质门设计」，工作树里 `019` 之后直接 `021`）。新增 `service/dramaclip/infra/storage/migrations/023_export_degraded.sql`，并在 `service/tests/infra/storage/test_db.py:37-59` 的**有序全等清单**末尾追加文件名——该清单是 `assert db.migrate(conn) == expected_migrations`，漏登记即红。

### 1.3 补救入口（后端能力齐、界面零入口）

- 失败成片「重试」接 `export.retry`（`desktop/src/services/client.ts:191`，**全仓零调用方**，已复核）。
- 方案「重掷此条」接 `narration.planVariants(excludePlanIds)`（`client.ts:158-167` 已封参数，`usePlanBatch.ts:115` 调用时**未传** `excludePlanIds` → 界面未接）。
- 失败粒度守住定案：**单条方案，不是整批**。
- 「作业取消」**今天已经有入口**（`JobRow.tsx:200` `showCancel` + `:219` 按钮，经 `JobDrawer.tsx:56,121` 的 `useCancelJob` 打 `jobs.cancel`）——档1 不新建，只在队列页复用同一处置逻辑。

### 1.4 状态契约

- `progress.update` 是**半死通道**：订阅确实在 `app/App.tsx:18` 装配（`subscribeAnalysisProgress()`），写进 `stores/ui.ts:28,39,47-48` 的 `analysisProgress` 却**零读者**（已复核：全仓除 store 自身定义外无引用）。裁决：**接上而不是删**。事件供即时刷新、轮询供对齐，但**两条都写同一个 store 字段**，界面只读那一个 sink——避免事件与轮询变两处真相。
- **同一 `jobs` 账本今天有三处独立轮询**（实测常量）：`JobsFeed.tsx:9-10,34`（抽屉开 2s / 关 10s）、`useAnalysisWorkspace.ts:15,62`（`JOB_POLL_MS = 3000`）、`usePlanBatch` 经 `poll.ts:2` 的 `POLL_INTERVAL_MS = 1500` 循环到终态。裁决：合流到 `stores/jobs.ts` 单写方（06 第二刀已这么干，照它）。引擎中心另有的 `StatusBar:42` 60s、`GpuCard:60` 2s、`useGpuInfo:29` 5s、`ToolsPage:45` **不并进来**——它们不是 jobs 账本，合并属越界。
- `EpisodeListRow` 把 `running` 并进「待分析」→ 单集在跑不可见，拆成四态。
- 剧集多选补 `已选 n/m 集` 回声，并把已算好的 `canStart`（`useAnalysisWorkspace.ts:177`）接到按钮 `disabled`——今天勾 0 集点「批量分析」是静默 no-op。
- `selfcheck_state` 的 `partial` 档补进筛选器（今天「有灰无红」既筛不出也看不见）；`ExportsCard.tsx:53` 拿不到时长渲染空串改 `—`，全站口径归一。
- **裸转圈**（复算口径：`grep -rn "<Spin" desktop/src --include=*.tsx` 排除测试，判据「`<Spin>` 自身无 label 文案」）实测 **3 处**：`LlmTraceModal.tsx:99`、`:118`、`ToolsPage.tsx:235`。至少带一句「正在取 X」。

### 1.5 档1 验收口径（业主定：纯机器契约）

四条新门禁 + **每条变异锚定**（在改前代码上验红，不放宽阈值换取通过）：

1. **降级落点穷举门禁**：门禁自己从 `api/export.py` **发现** `_note_degraded(` 的调用集合（不硬编码「10」这个数），断言该集合 ⊆ 界面落点表——加一处降级而不上屏即红。这是 `engine_configs` 那批学到的教训：**按登记面穷举的断言才防得住加行**，逐个点名写死三个键才让 `vision.cloud_api_key` 漏过去。
2. **判据唯一性门禁**：全仓不得出现第二处手抄的「模式 → 来源」字面量表（拦 `EXPECT_PLANNER` 复发）。
3. **留痕消费门禁**：渲染层必须存在 `log.append` 订阅 **且** 成片卡必须读 `degraded_notes`（拦「订阅了但没人用」——正是 `analysisProgress` 现在的病）。
4. **回声与占位口径门禁**：多选组件清单穷举必须带计数回声；量不到的位置必须 `—` 不得空串。

---

## 2. 档2 设计｜质感与细节（验收＝真机 + 造数库截图定版）

### 2.0 前置实测：深色底三档分层的数学

| 前景 | 最差底色 | 比值 | 判定 |
|---|---|---|---|
| `textTertiary #5E6C8C`（现值） | bgElevated | **2.88:1** | 连非文字 3.0 都不过 |
| 候选 `#7A89AB` | bgElevated | 4.32:1 | 正文仍不过 AA |
| 候选 `#8291B2` | bgElevated | **4.79:1** | AA 正文过 |
| `textPrimary ↔ textSecondary` 分离度 | — | 1.89:1 | — |
| `textSecondary ↔ #8291B2` 分离度 | — | **1.52:1** | 比原 2.52 小得多 |

**结论**：提到达标必然压缩档间分离度（1.52 < 1.89）。**档位分离不能再靠颜色，必须靠字号与用途**——与已定案的「三态分道法」同一哲学：不同语义走互不相干的通道，别抢同一个。

### 2.1 文字档一分为二

- `textTertiary` 值改为 **`#8291B2`**。**引用面实测：`textTertiary` 全仓 137 处 / 62 文件**，其中 `styles/theme.ts` 定义 2 处 → **改一行收敛 135 处引用**，这是当初选 token 路线的红利。
- 新增 `decorativeMuted = #5E6C8C`，接管现值原本承担的非文字用途（按属性分布实测：`fill:` 1 处、`background:` 1 处、antd `colorTextTertiary` 1 处）。
- **门禁锁死复发路径**：扩既有属性位矩阵（`measureContract.test.ts:145-153`，`TEXT_FIELDS` + `GLYPH_PROPS`，现规则是 `glyph.*` 只准出现在 `fontSize`/`width`/`height`）加一条——`color:` 位置只准出现「AA 达标前景集合」，`decorativeMuted` 出现在文字位置即红。**不新写扫描机制，用已有矩阵。**

### 2.2 对比度门禁的形状

矩阵从 `theme.ts` **实读**前景与五档底色（不手抄值），逐档断言最低比值：正文档 ≥4.5、非文字 ≥3.0。**新登记 token 必须进矩阵，否则测试红**——穷举面而非点名面。

### 2.3 动效基线：零新依赖 + 必须可冻结

全站 `transition` 实测 **5 处 / 2 文件**（`Rail.tsx` 1、`global.css` 4），质感确实"死"。但**不引入动效库**（依赖清单现在很干净：antd 6 + React 19 + recharts + zustand）：

- 定 `motion` token：时长三档（快 120 / 中 180 / 慢 240ms）+ 缓动两档 + **可动属性白名单**（只准 `color`/`background`/`border-color`/`opacity`/`transform`；禁 `height`/`margin` 引发布局抖动）。
- 只给三类状态加过渡：hover/active 反馈、覆盖层与抽屉进出、进度与计数变化。不做页面转场、不做列表错落进场。
- **硬约束：动效必须可关**（`prefers-reduced-motion` + 测试态常量）。理由是验收本身——基线截图要求同参数可复现，动效中的画面不可比。这条让档2 与档3 的冲突自动消解。

### 2.4 焦点与数字排版

- **焦点态实测**：全仓 `focus-visible` 零命中，且两处输入样式显式 `outline: 'none'`（`TitleBar.tsx:112`、`TranscriptCard.tsx:66`）而无替代焦点态——今天键盘操作者在暗底上看不见自己在哪。补 token 化焦点环 + 键盘走完主循环一屏。
- 时长/百分比/计数一律 `font-variant-numeric: tabular-nums`（本项目大量 `NN.Ns`、`NN%` 数字列，不等宽是廉价感的直接来源之一）。

### 2.5 数值一致性（纯归一，不新建抽象）

- 覆盖层宽度：`width={720}` 在 4 处各写（`ImportModelModal:43`、`PromptEditor:29`、`ProjectModals:26,117`）→ 收进 `overlay.width` token + 禁止 Modal 裸 `width` 数字。**档2 只归数值，档3 的 `Overlay` 组件消费它。**
- 栅格不一致：`LibraryGrid.tsx:203` 的 `236px` 与 `WorksPage.tsx:201` 的 `230px` 是同一语义两个值 → 由 §4 的 `cardGrid` 档位统一消灭。
- **阅读宽度（已更正做法）**：页级铺满**不动**——`mixins.ts:23` 注释与 `typeContract.test.ts:110` 的 `expect(layout.page).not.toHaveProperty('maxWidth')` 把「内容页 1080 居中」这条路锁死了，那是被 09-21 裁决作废的旧口径。改为**区块级** `readable` 宽度上限，只管承载完整句子的文本块：`WorksDetailPage.tsx:61` 右栏 1920 下 1367px ≈ 97 汉字/行、`AboutPage.tsx:27` 双栏各 885px 塞 200 字合规声明，这两处是真病灶。门禁断言只打在 `layout.page` 上，区块级不冲突。
- 度量债最后 **8 文件 9 处**（`measureContract.test.ts:63-72` 的 `MEASURE_DEBT` 台账，全在 `features/engines/`）清零，台账关闭。
- 死文档清扫：`docs/desktop/03-UI设计方案.md:979-982` 的手写 AA 声明对应旧色板（#E8EAED/#4D9FFF），与现 token 不符——按文档地图规则「原案与实测冲突时」更正，否则它就是下一个假账源。

### 2.6 为什么这一档必须真机

海报层判不了：`posterScrim`/`posterCaption` 在纯黑对照底板上是黑压黑，只有真素材才看得出遮罩与字底有没有分离。路线走记忆里验过的那条——`desktop/` 根另写**不含 `vite-plugin-electron`** 的一次性 vite config（带上即拉起真 Electron 并写 live `data/data.db`），配 `scripts/seed_scale_data.py` 的隔离 scale 库起真 Electron，改前基线 + 同参数重拍，100% 与 150% 缩放各一组；**截图一律指到 Temp，不入仓**。

---

## 3. 档3 设计｜导航归一、组件家族、布局重排、队列页（验收＝真机三档宽度）

### 3.1 最硬的那条指控：同一屏有三套阶段语言

逐行看过，实测证据：

| 位置 | 它在说什么 |
|---|---|
| `stageState.ts:25-30` | `STAGE_WORDS` = 进素材 / 分析 / 规划 / 出片（`:33` 另有 `STAGE_NUMERALS` ①②③④）；`stageRoute` `:161-164` 把 ①② 同指 `/analysis`、③④ 同指 `/produce` |
| `DramaShell.tsx:26` | `current = pathname.endsWith('/produce') ? 'planning' : 'analysis'` → **`intake` 与 `export` 两个 `current` 永不可达**，点 ④ 后页脚仍高亮 ③，`aria-current="step"` 从不生效 |
| `StepsNav.tsx:11-16` | 第二套四分法：「素材导入 & AI 分析 / 选择出片模式 / AI 编排 & 渲染 / 成片查看 / 导出」——合并①②、拆开③④，且第 4 项指向 `/works` |
| `StepsNav.tsx:1` | 同一文件的注释又是第三套：「1 分析 → 2 解说文案 → 3 渲染调整 → 4 成片」 |
| `ModePicker.tsx:38`、`PlanPickList.tsx:58` | 出片页区块标题写「① 选模式」「② 挑方案」——**同一屏上阶段条说③④、内容说①②** |
| `WorkbenchPage.tsx:92` | `step={1}` 写死常量，永不变 |

这不是文案不统一，是**四段只读导航被两条路由切歪了**。修法只有一条正的：**合一为单一路由**。

### 3.2 结构手术（四步，顺序有依赖）

1. **剧空间合一**：`/projects/:id/{analysis,produce}` → 单一 `/drama/:id`，四段各为一个区块，阶段条是纯锚点跳转（`?focus=` 已在用），`current` 由**实际滚动区块**决定而非路由后缀 → ①④ 可达性问题由构造消失。壳 store 已存在（`stores/dramaSelection.ts`），旧 URL 保留重定向到 `/drama/:id?focus=…`。阶段条上**不放任何编辑器**（硬约束）：合一只是把两块内容搬进一屏，不改各自交互边界。
2. **第二套编号消失**：删 `StepsNav` 的四分法与 `step={1}` 常量；区块标题去圈数字，直接用阶段名（「规划」「出片」）。门禁：全仓**只准阶段条一处**出现 ①②③④。
3. **导轨补第 8 项「队列」**：`loop` 组贴顶、`config` 组钉底的导轨法不动（`Rail.tsx:20` 的 flex spacer 已合规），只加一项；`iaContract.test.ts` 的 `navItems ↔ routes.ts ↔ router.tsx` 三方集合全等守卫同步扩。
4. **剧库更名 `/projects` → `/dramas`**：**实测当前面 = `grep -rn "/projects" desktop/src` 命中 66 处 / 26 文件**，其中 `__tests__` 39 处 / 10 文件、生产码 **27 处 / 16 文件**（含 `DramaShell.tsx:40` 的 `navigate('/projects')`）。记忆里那条「12 触点 / 6 文件」是 22 天前的数，**作废**。另加「项目」字样文案清扫 **23 行**（用户可见文案，不含 `AboutPage.tsx:25,66` 那两处指"软件工程意义的项目"）。必须包含 `EnginesPage` 那类 pathname 正则——漏则 tab 高亮静默失效（记忆里明确记过这个坑）。注意 `DramaShell.tsx:35,:43` 已经是「文案说剧库、路由是 projects」的自相矛盾现场，可作为更名完工的判据位。

### 3.3 组件家族：原型清单即验收表

19 屏归 7 原型的定案今天仍只是纸面——`P1/P4/P5/P6` 没有同名抽象，各屏自写 grid。档3 把每个原型做成**一个布局组件**，屏只声明例外：

- `StateBlock`（四态：空 / 载入 / 失败 / 部分成功）收掉各写各的空态与自制错误横幅。复算口径：`grep -rn "<Empty" desktop/src --include=*.tsx` 排除测试 = **11 处 / 8 文件**；`<Spin>` 裸转圈 3 处（见 §1.4）。审计代理给的「9 处空态 + 5 处错误横幅 + 4 处无空态」按此口径不可完全重现，**以本文件复算数为准**。「失败原因只在 Tooltip 里、可见文本只有『原因』二字」（`ExportsCard.tsx:47-49`）判为违规——违反所见原则且不可键盘聚焦。
- `Overlay` 消费 §2.5 的 `overlay.width` token（今天 `width={720}` 在 4 处各写）。
- `cardGrid` 档位家族：今天同一语义 **5 个 `minmax` 值**（`LibraryGrid.tsx:203` 236 / `WorksPage.tsx:201` 230 / `PlanPickList.tsx:62` 280 / `ModePicker.tsx:147` 200 / `ActiveEngineCard.tsx:132` 150），且 `auto-fit` 与 `auto-fill` 混用（`ActiveEngineCard.tsx:132` 用 fit 会拉伸，其余 fill 留空轨）。数值由 §4 选型定死。
  **家族边界（消歧）**：`ActiveEngineCard.tsx:132` 的 150px 是引擎中心的能力芯片阵，**不进 `cardGrid` 家族**——它要的是「等分拉伸」，`auto-fit` 在那里是正确用法。`cardGrid` 只管四个「内容卡」位点。

### 3.4 布局重排

靶子清单（每条都有实测位点）：滚动三层套嵌、分栏比例不持久、吸底栏分离度三种写法、截断无兜底、死 CSS。**其中剧卡与方案卡的重排由 §4 的草案选型决定**，不在本节重复数值。

- **滚动三层套嵌**：`AppLayout.tsx:14` → `DramaShell.tsx:59` → `mixins.ts:24-32` 只有最内层生效，但 `overflowY:'auto'` 让 `overflowX` 计算值从 `visible` 变 `auto`，于是 `SettingsPage.tsx:131` 的 `margin: 0 -24px`（全仓唯一负边距）撑出**横向滚动条**。修法：单层滚动原则 + 撤负边距 + 去 `ExportsCard.tsx:15` 的 `maxHeight:280` 内滚（同屏两根滚动条，280 还不在阶梯上）。
- **分栏比例不持久**：`useSplit.ts:9` 只存 `useState`，点阶段条跳页即复位；而同仓库 `libraryDensity` 走 localStorage。同类元素不同做法。
- **吸底栏分离度三种写法**：`shadowSticky` 只用在 `BatchBar`/`SettingsPage`，`PageKit.tsx:157` 的 `PageFooter` 靠 `bgSidebar` 对 `bgLayout` 的 5% 亮度差——深色下几乎看不出边界。
- **截断无兜底**：`DramaMatrix.tsx:169` 剧名、`JobRow.tsx:213` 整句 label、`MachinePanel.tsx:221` 显卡名；加 `TodoList.tsx:59,70` 兜底错位（`title` 挂 `detail`、可见文本是 `text`）。同一数据在 `DramaCard`/`LibraryList` 都有 `title`，**三处渲染两处漏**——这条可门禁化。
- 顺手清死 CSS：`global.css:145,155` `.work-poster-folder` 无任何元素挂此类名。

**明确说没问题、别动的**：见 §8。

### 3.5 队列页（`StateBlock`/`cardGrid` 的第一个消费者）

跨剧作业一览：逐条 label + 实测进度 + **取消**（复用 §1.3 的既有处置）+ 本会话留痕滚动（`log.append`）+ 失败带原因与**重试**（`export.retry`）；**账在库、流在通知**，队列页同时读两者并标明各自来源。它不做进度条表演——第一能力是留痕。

---

## 4. 卡片定版（草案实测，业主已看图选路）

**草案**：`scratch/uicard-2026-10-16/draft.tsx`（gitignored、一次性），import **真** `DramaCard`/`PlanCard`/`StageMicro`/`BlockNoteLine` 与真 `theme.ts`+`mixins.ts`+随包字体，经独立 `vite build`（不含 `vite-plugin-electron`）出静态包，Chrome 无头 `--dump-dom`/`--screenshot` 量取（`file://` 上的 ES module 必须带 `--allow-file-access-from-files`，否则 DOM 空）。截图在 `C:\Users\efarh\AppData\Local\Temp\uicard\`，不入仓。

**外框扣减按 220px 估**（titleBar 46 + statusBar 26 + 页面上下 48 + 页头约 60 + 工具栏约 40）——**这一项是估的，档2 真屏必须复核**，见 §6.1。

| 剧卡形态 | 卡宽 | 卡高 | 1024×768 | 1680×1050 | 1920×1080 |
|---|---|---|---|---|---|
| **A 现状** `minmax(236px)` | 292→244 | **662 / 582 / 576** | **0 部** | 6 部 | 7 部 |
| B 横条单列 | 908→1804 | 112 | 4 部 | 6 部 | 7 部 |
| C 密集海报 `minmax(150px)` | 172→153 | 229→203 | 10 部 | 21 部 | 28 部 |
| **E 横条多列** `minmax(420px)` | 448→442 | 112→124 | **8 部** | **18 部** | **24 部** |

方案卡：D1 现状 `minmax(280px)` = 高 236px / 一屏 6–9 条；**D2 文案优先 `minmax(320px)` = 高 162px / 一屏 9–15 条**。

### 4.1 四条读数

1. **A 在 1024 宽一屏放不下整行**（卡高 662 > 可用 548）。根因不是形态选错，是 `DramaCard.tsx:127` 的 `aspectRatio:'9 / 16'` 让**海报高随列宽线性增长**：卡宽 244 → 海报 434，占卡高 75%。列数越多卡越宽、卡越高——加列不解决问题，反而更糟。
2. **C 的密度是拿卡点句换的**。153px 卡宽里「卡在规划：LLM 编排连…」只剩 8 个字，灯排从一行挤成三行。卡点句是 09-10 定案的第一判据 → **C 否决**。
3. **E 同时拿到 A 的识别物和 C 的密度**（8→24 部/屏，卡点句两行基本完整），但它暴露一个新缺陷：**52px 海报条里只有一个 ▶，占掉 442px 卡宽的 14% 却不携带任何信息**。必须按 09-10 定案换成**钩子帧缩略图**，否则删掉。
4. **D1 真 `PlanCard` 有一处重复真相**：模式名同一张卡出现两次（`PlanCard.tsx:117`/`:123` 卡头互斥分支 + `:143` 卡脚恒渲染），页脚六项指标在 303px 卡宽里折成四行。D2 把钩子句升为主体后，来源徽章三态（模型文案 / 规则文案 / 无解说）在截图里都跑出来了——**这正是 §1.1 的判据位**，且证明纯剪辑模式不能被徽章指控为「规则降级」。

### 4.2 定版

- **剧卡走 E（横条多列）+ 海报条换成钩子帧缩略图**。
- **方案卡走 D2 的层级 + 保留 D1 的勾选/推荐徽章**。
- `cardGrid` 一族因此需要三枚具名 token：`minWidth`（剧卡 **420** / 方案卡 **320**）、`gap`、`posterStrip`，替掉 §3.3 那四个内容卡位点上各写的裸数。**两个槽位（成片卡 `WorksPage`、模式卡 `ModePicker`）本轮没实测，档3 用同一草案口径量完再定值——不许凭空写数**，登记进 §6.1 欠账。
- **栅格子元素必须是卡本体，不许包 wrapper `<div>`**：网格默认 `align-items: stretch`，包一层会让「整行取最高那张」的真实吞吐算错（草案第一轮就因 wrapper 量出参差卡高，误判成产品缺陷）。

### 4.3 两条诚实边界

- **海报层仍然判不了**：草案全用占位渐变，`posterScrim` 黑压黑这一条**没被推翻**，必须等档2 真素材复判。
- **E 的卡点句截断是在编造的超长失败文案上量的**：真实文案长度分布没测，`posterStrip` 与两行截断的取舍要在档2 造数库截图上复核。

---

## 5. 门禁与实现约束

| 门禁 | 归属 | 形式 |
|---|---|---|
| 降级落点穷举 | 档1 | 源码抓 `_note_degraded(` 调用点名 → 界面落点表全等 |
| 判据唯一性 | 档1 | 全仓禁第二处「模式 → 来源」字面量表 |
| 留痕消费 | 档1 | 必须存在 `log.append` 订阅 **且** 成片卡读 `degraded_notes` |
| 回声与占位口径 | 档1 | 多选必须带计数回声；量不到必须 `—` |
| 对比度矩阵 | 档2 | 从 `theme.ts` 实读，新 token 不进矩阵即红 |
| `color:` 属性位 | 档2 | 扩 `measureContract.test.ts:145-153` 既有矩阵，不新写扫描器 |
| 阶段编号唯一 | 档3 | 全仓只准阶段条一处出现 ①②③④ |
| IA 三方一致 | 档3 | 扩 `iaContract.test.ts`（含队列项与 `/drama/:id`） |
| 截断兜底 | 档3 | 清单式：截断位必须带 `title` |

**既有机制的准确定性（本规格不重复立法，只登记事实）**：
- `eslint.config.mjs:51-58` 的 `no-restricted-syntax` 对裸 `fontSize`/`borderRadius` 字面量是**全 `src/**` 硬 `error`**，`src/styles/**` 豁免——**eslint 不是棘轮**。棘轮在 `measureContract.test.ts`：`MEASURE_DEBT` 台账（`:63-72`）按文件记属性位计数、`toEqual` 全等（`:135`），加行即红、删行才降。
- 字面量/透明度/手写 boxShadow 的零命中硬禁在 `styleContract.test.ts`、`cssContract.test.ts`；token 形状（含 `layout.page` 不得有 `maxWidth`）在 `typeContract.test.ts`。
- 新增扫描面必须先扩 `rendererFiles()` 口径，别另起炉灶。

---

## 6. 已登记欠账与开放项

### 6.1 三档各自的欠账（不是"已知事实"，是待办）

1. **220px 外框估扣**（§4 表格的地基）→ 档2 真屏复核，误差直接改写每屏吞吐数。
2. **海报层判不了**（§4.3）→ 档2 真素材复判 `posterScrim`/`posterCaption`。
3. **E 的卡点句截断基于编造文案**（§4.3）→ 档2 在造数库上测真实长度分布，再定 `posterStrip` 与行数。
4. **成片卡与模式卡的 `minWidth` 槽位无实测值**（§4.2）→ 档3 用同一草案口径量完再定，不许凭空写数。

### 6.2 待业主裁定

- `docs/desktop/04-设计系统方案.md` 自相矛盾：`:12` 说「内容页 1320 流式（narrow 880 表单/文本页）」，`:53`/`:57` 说「全站统一铺满（无页宽上限）」，而 `typeContract.test.ts:110` 站在铺满一边。**必须裁定以哪句为准并清扫**，否则它是下一个假账源。
- `api/narration.py:259`、`:398` 两条进用户可见串的「（规格 §4.3）」内部行话要不要面向用户出现（其余 `:178/:188/:200/:264/:655` 是 docstring 与注释，不面向用户，不在本项范围）。
- 旧规格过期行：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md:228`。

### 6.3 本规格写作期间作废的旧读数（引用前先复核这张表）

| 曾经的口径 | 复核结论 |
|---|---|
| 「更名触点 12 处 / 6 文件」 | **66 处 / 26 文件**（生产码 27 处 / 16 文件）+「项目」文案 23 行 |
| 「作业行没有取消按钮」 | **假**：`JobRow.tsx:200,219` + `JobDrawer.tsx:56,121` 已接 `jobs.cancel` |
| 「`planner` 需注册 JSON schema」 | **不需要**：`narration.json:32-34` 把 `plan_data` 声明为裸 object，Router 不校验出参 |
| 「eslint 用棘轮扩面」 | **假**：eslint 是硬 `error` 全量门禁；棘轮是 `measureContract` 台账 |
| 「5 处裸转圈」 | 复算口径 **3 处**（§1.4） |
| 「9 处空态 / 5 处错误横幅」 | `<Empty` 复算 **11 处 / 8 文件**；横幅计数待按同一口径重发 |
| 「卡高 550px、一屏 1.7 行」 | 审计代理的算术；实测是 **662/582/576px，1024 宽一屏 0 部**（§4） |
| 「`_annotate_gate` 在 `:113`」「`EXPECT_PLANNER` 在 `:126-135`」 | 实为 **:110**、**:125**（行号按 §0.2 只作方便定位） |
| 「关于页改窄单列 `max-width:720`」 | **撤回**：撞 `mixins.ts:23` + `typeContract.test.ts:110`，改为区块级 `readable`（§2.5） |
| 「`textTertiary` 135 处」 | 引用面 135 成立；**出现面是 137 处 / 62 文件**，`styles/theme.ts` 自身定义 2 处（两种口径都要写明） |
| 「三条各自 `setInterval`」 | 三处轮询属实，但第三处是 `poll.ts:2` 的 1500ms **循环**而非 `setInterval`；且引擎中心另有 4 个独立轮询点，**不在合并范围**（§1.4） |
| 「五个 `minmax` 值同属卡家族」 | **四个**：`ActiveEngineCard.tsx:132` 的 150px 是能力芯片阵，`auto-fit` 在那儿是正确用法（§3.3） |
| 「未见任何 focus 样式定义」 | 精确化：`focus-visible` 全仓零命中 + 两处 `outline:'none'` 无替代焦点态（§2.4） |

---

## 7. 并行冲突与风险

1. `api/export.py` 与 `api/narration.py` 是另一位工程师的近期热点。缓解：档1 改动集中在**一个函数 + 一个新迁移 + 一个纯函数**，每档开工前先看这两个文件的近期动静。
2. **同树同分支**：本规格的实施不建 worktree，但提交只 `git add` 明确路径，**严禁宽 add**；开工前必查 `git status`；清洁树才能判绿时一律在 `git checkout-index -a --prefix=…` 快照里跑（后端另需 `PYTHONPATH=<快照>\service`）。
3. 迁移号 023 若被并行批次抢用，顺延并在 `test_db.py:37-59` 清单同步——清单是全等断言，号错即红，不会静默。
4. 起真 Electron 会写 live `data/data.db`：所有需要真屏的验收走**不含 `vite-plugin-electron` 的一次性 config + 隔离 scale 库**，截图指到 Temp。
5. 会改变观众所见所闻的降级一律**失败不出片**；只影响成本/可用素材的降级允许但必须留痕——档1 不得为了「界面有徽章可看」而放宽任何既有闸；**断言阈值不许为了通过而放宽**。
6. 用户可见文案里**不得出现**「消重/抗比对」类表述（合规红线）；`raw_clip`/`subtitle_flow`/`highlight_cut` 的 `rule` 来源不得被徽章指控为降级。

---

## 8. 明确不动的清单（核实过，别顺手改）

`listRow` 三态分道（`mixins.ts:89-103`）、外框高度链（`AppLayout.tsx:10-19` 的 `flexShrink:0`+`minHeight:0`）、`WorkbenchHeader`/`WorksPage`/`PlanPickList` 的 `flexWrap`、`FilterRow` 用真 `button`、`PageHeader` 的 primary 让位规矩、`Rail.tsx:20` 的 flex spacer 导轨法、`typeContract` 的页级铺满断言。

---

## 9. 验收流程（按档定口径）

- **档1**：四条门禁全绿 + 每条变异锚定（改前代码验红）；不出图。
- **档2**：真机 + 造数库截图定版，100%/150% 缩放各一组；§6.1 三条欠账在此销账或改写。
- **档3**：真机三档宽度（1024 / 1680 / 1920）复算每屏吞吐，与 §4 表格对照；偏差 >1 卡/屏即回本规格修订，不许就地调数。
