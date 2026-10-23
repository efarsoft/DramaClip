# DramaClip 就地核对与取用批次（H1-H3）· 设计规格

**日期**：2026-10-22 · **状态**：H1-H3 已实施，验收记录见 §7.1-§7.3 · **业主裁决**：「H1+H2+H3 一起推进」（含 H1 的后端那一刀）、「批准直接进入实施」
**提交切分**：后端那一刀（`srt.py` + encoder sink + 侧车 `.srt` + 跨盘符转义）已提交 `db1dbfd`；H1 前端（`features/cues/`）与 H2、H3 连同本文件在同一提交里入库。
**上位文件**：`docs/superpowers/specs/2026-10-16-ui-truth-and-polish-design.md`（W1-W3，档1 已提交 `02d7ede`）、`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md`（信息架构）、`docs/superpowers/specs/2026-09-21-desktop-typography-density-design.md`（token 与状态契约）。
**与路线图的边界**：`docs/05-开发路线图.md` 的 P3 批次表由业主自维护，本文件不合并、不引用其排期。

---

## 0. 这是第三条轴，不是 W2/W3 的重复账

并行批次管的三件事是：真相可见性（W1，已落地）、质感与 token（W2）、结构与组件家族（W3）。三档都不管一件事：**产出物能不能在原地被读懂、验证、取走**。本批次只做这一件事，配方来自已定版的工具箱「视频文案提取」屏。

### 0.1 配方四条（从工具箱定版抽象）

1. **产物在屏上读，不在文件夹里读**——路径、目录名、「已导出 N 集」都不算读懂；读的是内容。
2. **时间可点、来源可查**——逐句时间戳，点一行跳到那一句；判据与降级给常驻全文而非悬停。
3. **坏消息常驻**——不是一闪而过的 `message.error`，也不是只有鼠标悬上去才看得见。
4. **有入口才有按钮**——后端已有的动作接通；接通不了就让按钮缺席。**绝不留假按钮**。

### 0.2 覆盖表（11 屏，逐屏点名，可复核）

| 屏 | 现状能否就地核对 | 本批次 |
|---|---|---|
| `features/tools/ToolsPage.tsx` | ✅ 已定版 | 作配方源，**不再动** |
| `features/works/WorksDetailPage.tsx` | ❌ 文案只读不能定位 | **H1** |
| `features/narration/ProductionPage.tsx` | ⚠️ 留痕入口规划结束即卸载 | **H1、H2** |
| `features/analysis/WorkbenchPage.tsx` | ⚠️ 有逐句转写与 seek，失败无原因、指标不上屏 | **H2、H3** |
| `features/engines/EnginesPage.tsx` | ❌ 两处口径相反、失败只在 Tooltip | **H2、H3** |
| `features/home/HomePage.tsx` | 导流屏（`DramaMatrix` 置顶 + 待办 + `EmptyWorkbench` 三步），`llmBaseUrl` 只作就绪判定数据源、不上屏 | **无账，本批次不动** |
| `features/project/ProjectsPage.tsx`（含 `LibraryGrid`/`DramaCard`） | ✅ 已有「宁灰勿假绿」横幅 | **H3 一处** |
| `features/works/WorksPage.tsx`（含 `ExportsCard`） | ⚠️ 重试已接（W1），但整行点击进黑播放器、原因只在 Tooltip | **H1（§1.6）、H3（§3.1.4-5）** |
| `features/settings/SettingsPage.tsx` | ⚠️ 目录取不到时静默降级成裸 id | **H3** |
| `features/about/AboutPage.tsx` | ⚠️ 版本取不到永远 `…` | **H3** |
| `features/jobs/`（+ W3 队列页） | 屏级四态归 `StateBlock` | **只供行级口径**（§4.0 划界） |

### 0.3 复算口径

行号是写作时点工作树的方便定位，判据是**函数名/文案串 + 本文件给的 grep**。同树同分支有并行会话在改 `features/analysis`、`features/jobs`、`features/narration`，行号必漂，**行号漂移不算读数错误**。

---

## 1. H1｜成片逐句核对（本批次主菜，含一处后端）

### 1.1 病灶（实测）

`features/works/WorksDetailPage.tsx:196` 的 `NarrationSection` 就住在播放器同屏右栏，但 `NarrationRow`（`:231`）左列打的是**内部段 id**、右列纯文本——**没有时间戳，不能点**。成片是这条链的最终产物，却是全站最核对不了的一屏：想知道「第 12 句出现在第几秒」只能播着等。

（内部 id 上屏是档1 规格 §1 点名过的「成片详情把内部段 id 打在正文左侧」，W1 未销；本批次销掉。）

### 1.2 为什么客户端加不出来（两条都核过）

- `protocol/ts/index.ts:331-338` 的 `TimelineSegment.start/end` 是**源片集内时间**（同结构带 `episode_id`），不是成片时间；`narration_texts`（`:343`）只有 `id/text/voice/audio_path/duration`，没有成片位置。
- `api/export.py:579` 的 `burn_subtitle` 文档串自己写着「相对时间轴 0→duration」，且真实切点被 `jitter.safe_times`（`engines/exporter/encoder.py:1005`）挪过。

拿这两份数去 seek 成片＝造一份假对齐，破「宁缺毋假」。**结论：必须让渲染链交出成片时间轴。**

### 1.3 设计｜把已经烧上去的时间戳如实记下来

渲染是两阶段：Phase A 逐段切出 `seg_NNN.*` 并把 ASS 烧进段内，Phase B `_concat(_concat_manifest(jobs), out_path)`（`encoder.py:1220`）按清单顺序拼接。因此：

**某段的成片偏移 = 清单里它之前所有段产物的实测时长之和**——而 `_audit_film_duration`（`encoder.py:1400-1408`）**今天已经在探同一批段文件**。所以偏移不是新测量，是**已有测量的第二个消费者**。

落法（最小接口，零返回类型变更——`export_plan` 有约 20 处调用点，其中测试占多数，动返回类型是波及）：

1. `encoder.export_plan` 加一个可选关键字参数：`segment_offsets_sink: Callable[[Sequence[tuple[int, float]]], None] | None = None`，在 `_concat` 前、拿到 `_concat_manifest` 顺序后调用一次，给 `[(segment_index, offset_s), …]`。默认 `None`＝现行为逐字节不变。
2. **测量口径（2026-10-22 实施时就地修订，理由如下）**：`_audit_film_duration` 住在 `_concat` 内部，而 `_concat` 有 5 处测试替身按 `(files, target)` 双参签名打桩——为省一次探测去改它的签名，波及大于收益。因此偏移用**同一批段文件、独立一次实测**（在 `_concat` 成功后、按 `_concat_manifest` 顺序），代价是每片多 N 次 ffprobe（相对整片渲染可忽略）。两份测量对同一批文件不可能给出不同答案；探测失败则**不产 `.srt` 并记一条允许型降级**（走 W1 的 `degraded_notes`），界面按「没有时间轴」分支显示，不猜时间。sink 默认 `None`＝现行为逐字节不变，5 处替身零波及。
3. `api/export.py` 的 `burn_subtitle`（`:579`）与 `dialogue_subtitle`（`:623`）本来就在函数内构造 `lines: [{start, end, text}, …]`（`:596-604`）——把这些行连同段号暂存（导出上下文内的局部账），拼接后按 `offset + rel_start` 写成 **`out_path` 同名 `.srt`**。格式沿用 `_format_srt`（`api/tools.py`）的 `HH:MM:SS,mmm`，好让前端复用同一个解析器。
4. **`raw_clip` 与不烧字幕的模式**：没有 `lines` 就不写 `.srt`——界面走「无时间轴」分支，不做假列表。

### 1.4 诚实边界（必须写进文案与文档）

段内逐行时间是 `burn_subtitle` **按字数比例分配**的估计（`:590` 注释：长文案拆多行防止溢出画面），不是词级语音对齐。因此这份 SRT 的口径是：**「字幕烧上去的时间」的忠实记录**，不是「这个音节几点出声」的测量。这正好是核对者要问的问题（这句在片子里什么时候出现），所以它是真账；但界面文案**不得**写「精确到语音」。悬浮注词固定为：`时间轴取自烧录字幕的分行时刻，非语音对齐`。

残留风险要写明：拼接按容器时长推进，偏移与各段声明窗口之间可能有毫秒级出入，整片容差即 `AUDIT_DURATION_REL_TOLERANCE`/`_ABS_TOLERANCE_S`（`encoder.py:1390-1392`）。超出即时长审计当场抛错不出片，所以「尾句偏 1 秒以上」这种情形不会存在于成功出片的账上。

### 1.5 UI｜第二个消费者，零新依赖

先说清一件不能偷懒的事：工具箱那两个可复用件今天是**模块私有**的——`useSrtCues`（`CopyResultPanel.tsx:15`）与 `CueList`（`:50`）没有 `export`，而 `CopyResultPanel` 本身带着工具箱专属动作（`RewritePanel`、`onSendToTts`、`srtAction`）。所以正确做法不是"整个面板搬过去"，而是：

1. 把 `useSrtCues` + `CueList`（逐句行、点击 seek、未解析时不渲染切换器）**提为共享件**；工具箱的 `CopyResultPanel` 成为它的第一个消费者、行为逐字节不变（现有 11 条测试就是这条抽取的回归网）。
2. `WorksDetailPage` 成为第二个消费者：右栏换成逐句时间轴 + 点击定位。发布取用只补**保存 SRT**（`saveTextFile`，工具箱存 SRT 用的就是它）；「复制全文」已有（`WorksDetailPage.tsx:205-213`），**不重复造第二个复制按钮**（平级元素同形，不是同屏两个入口）。
3. `WorksDetailPage.tsx:125` 那个 `<video>` **没有 `ref`**——seek 需要补 `videoRef`（写法照 `PlayerCard`/工具箱：`videoRef.current.currentTime = cue.start`）。
4. `.srt` 路径**由 `output_path` 同名推导**，不新增协议字段、不加迁移（W1 刚占 `023`，本批次零 schema 变更）。三态靠 media 协议实测分开：`desktop/main/services/preview-protocol.ts:175-178` 对不存在的文件回 **404**、越界/超限回 403、异常回 500——所以 404＝「本条没有逐句时间轴（旧成片 / 该模式不烧字幕）」（**不报成失败**，未知不是错误），非 404 的读失败才常驻「逐句时间轴加载失败：读取失败（HTTP nnn）」。
5. 解析器与 `formatStamp` 沿用 `features/tools/srt.ts`（已有 7 例覆盖，含 CRLF、越界时间码整块跳过、全站时长口径），不重写。

顺带销一处：`NarrationRow` 左列的内部段 id 不再上屏——有逐句时那一列就是 `formatStamp`（走 `CueList`），没有逐句时退到方案文案列表、左列给**序号**（方案文案没有可信的成片位置，硬凑时间戳＝§1.2 禁止的假对齐）。

### 1.6 出片页的同一条链

`ExportsCard.tsx:54-57` 的整行 `onClick` 不分状态一律 `navigate('/works/'+job.id)`，而 `WorksDetailPage.tsx:126` 无条件渲染 `src={mediaUrl(job.output_path ?? '')}`（失败行的 `output_path` 是 `null`）→ 未完成的片进了一间黑房子。H1 收这条：未成功不进详情页，就地给状态＋原因＋重试（重试按钮 W1 已接 `export.retry`，`ExportsCard.tsx:44-51`，但它的 `.catch` 缺失见 §3.1.5）。

---

## 2. H2｜零入口与假按钮收编

1. **候选标题的星标是假的**：`TitlesSection.tsx:29-31` 的 `toggle` 只写 `onChange` → `useWorkDetail.ts:39` 的 `useState`，刷新即丢。而 `titlesApi.update`（`services/client.ts:218`）**全仓零调用方**，服务端 `narration.update_titles` 早已实现（`api/narration.py:125`，注册于 `:53`）。这是 W1 收编 `export.retry` 的同型账：**接通落库 + 存上给回声**（失败常驻，不弹 toast 就走）。
2. **两处口径互相打脸**：`GpuCard.tsx:28`「已就绪 · 首次转写时将自动启用 GPU 加速」与 `MachinePanel.tsx:155`「未安装 · 转写走 CPU」可同屏并存（一个讲 torch/CUDA 卡型可得性，一个讲 CUDA 运行库安装态）。修法＝同一句话只留一处真相：GPU 卡按运行库实际状态出词，未装就不得写「将自动启用」。**这条同时是上一批留给业主裁定的欠账第 1 条（GpuCard 只读 `gpu_info` 过度承诺），一并销。**
3. **指路不指按钮**：`MachinePanel.tsx:155` 让用户「在本页『转写加速（GPU）』卡下载」，安装动作却在兄弟栅格位。改成行内按钮，与 W4「引导卡一键接通」同哲学、不同屏。
4. **空态指向不存在的按钮**：`TitlesSection.tsx:53` 的空态正文写「点击『生成候选标题』…」，而那个按钮只在 `hasPlan` 时渲染（`:37`）→ 无方案时屏幕指路指向一个不在场的按钮。改成如实陈述前置条件。
5. **禁用无理由**：`WorksDetailPage.tsx:183` `disabled={!hasPlan}` 不说为什么（同仓 `WorkCard.tsx:268` 有说明，平级元素不同形）；`ModePicker.tsx:122`、`PlanPickList.tsx:153` 同型。按 W1 的「多选回声 + `canStart` disabled」口径补可见前置条件。
6. **死组件**：`PlanCard.tsx:58` 的 `copyOpen` 初值 `false`、只在 `:97` 被写回 `false` → `:97` 那个 `PlanCopyModal` 实例永不打开，真入口是 `:158` 的 `PlanCopyButton`。删死实例（不留「以后可能用」）。

**已复核为「不是缺陷」，不动**：`ReadinessCard.tsx:20-21` 的 `noop` 只是可选 props 兜底，唯一调用方 `OverviewTab.tsx:55-65` 把 `onChanged`/`onVerify` 都传了真值——代理报告把这条报成假按钮，**撤回**。

---

## 3. H3｜坏消息常驻 + 占位口径（与 `StateBlock` 划界）

### 3.0 边界声明

W3 的 `StateBlock` 管**屏级四态**（空/载入/失败/部分成功）。本批次只管**行级原因**（列表里某一行为什么坏）。为避免同一文件两处立法：H3 先立**口径与门禁**，组件落点若与 `StateBlock` 相遇，**由 W3 的家族承接渲染、本批次供数据与判读**。开工前查 `git status`，命中同文件先与并行会话对齐。

### 3.1 失败原因零读者（实测三处）

1. **集行**：`EpisodeListRow.tsx:257` 出「分析失败」四个字，服务端 `EpisodeAnalysisResult.error`（`protocol/ts/index.ts:191`）**全仓零读者**（`grep -rn "\.error" features/analysis` 只命中 `message.error` 调用）。→ 灯下面打服务端原文。
2. **模型下载**：`ModelDownloadPopover.tsx:73` 上次失败原因只在 `Tooltip`；`:35` 下载中是个 `disabled` 按钮且**没有取消**（`jobs.cancel` 全站已可用）。→ 原因进可见文本 + 补取消。
3. **运行环境安装**：`useLocalRuntime.ts:67-69` 失败弹 toast 后 `jobId=''` 让整块消失——账跟着没了（违反本仓「账在库、通知不作真相源」裁决的同一条哲学）。→ 常驻失败原因 + 重试。
4. **出片行的「原因」两个字**：`ExportsCard.tsx:69-73` 可见文本只有「原因」二字，原文进 `Tooltip`。这正是档1 规格 §3.3 判过违规的那一条（「失败原因只在 Tooltip 里、可见文本只有『原因』二字」）——W1 落了降级徽章，这条没销。→ 原文进可见文本，`Tooltip` 只作补充。
5. **重试再失败是静默的**：`ExportsCard.tsx:44-51` 的 `retry()` 只有 `.then(() => onRefresh()).finally(...)`，**没有 `.catch`** → 转圈停了，什么也没说。→ 补常驻失败原因（同 §3.1.3 写法）。

### 3.2 `unknown ≠ ok` 的剩余两处

- `useLocalRuntime.ts:49-51`：探测 `catch` → `setInstalled(false)`，把「取不到」说成「未安装」。→ 引入第三态 `unknown`（同文件 `MachinePanel.tsx:84-86` 已有此写法，照它，别新造）。
- `SettingsPage.tsx:59`/`:68`：风格与预设目录各挂一个 `.catch(() => [])` 静默兜空；目录取不到时，已存的 `style_id`/`preset_id` 找不到对应名字（选项 label 来自 `style.name`/`preset.preset_name`，`:63`/`:72`），界面上剩的就是裸 id——拿 id 冒充名字。→ 显示「目录取不到」+ 重试，不静默吞。

### 3.3 占位口径：区分「还在测」与「测不到」

这条**不是**把 `…` 全换成 `—`。实测 `MachinePanel.tsx:197` 的注释自陈「取不到就如实『…』，不冒充有答案」，说明 `…` 是引擎中心**有意**的约定；而 W1 刚落地的门禁要求量不到的数字位是 `—`。两套约定本身不冲突，冲突在于**同一个 `…` 同时表示两种终态**：

| 语义 | 该用的记号 | 现用 | 证据 |
|---|---|---|---|
| 还在测（in-flight） | `…` | ✅ 正确 | `MachinePanel.tsx:147,162,204`（`status === 'loading'`） |
| 测不到（terminal unknown） | `—` + 原因 | ❌ 也写 `…` | `MachinePanel.tsx:218,222`（`health` 缺字段）、`AboutPage.tsx:137`（`ping` 已 `catch` 于 `:114`，版本永久 `…`） |

→ H3 的判据一句话：**`…` 只准出现在还活着的过程里；已终局而无数，一律 `—` 并给原因（`AboutPage` 补重试）。** 门禁按 §5.3 穷举，不逐文件点名。

---

## 4. 门禁（防复发，与 W1 的 G1-G4 同族；每条变异锚定）

1. **零调用方客户端 API 门禁**：`services/client.ts` 导出的每个写动作（`update`/`retry`/`cancel`/`save` 类）必须有渲染层调用方。今天这条同时抓到 `titlesApi.update`（H2 修前验红）。同族先例＝W1 的 G3 留痕消费门禁。
2. **成片侧车产物门禁**：后端——`export` 成功且该模式烧字幕时，同名 `.srt` 必须存在且 `parseSrt` 解出 ≥1 句；解不出＝导出失败，**界面不许回退成"猜时间"**。同族先例＝档1 的「黑帧实编验证」纪律（量不到就失败，不伪装通过）。
3. **行级原因与占位终态门禁**：清单式穷举（扩 `rendererFiles()` 口径，别另起扫描器）——(a) 渲染失败态的行必须把原因写进可见文本，`Tooltip`/`title` 不计；(b) `…` 只准出现在 loading 分支，终局无数必须 `—`。

前端逐句复用已由 `features/tools/__tests__/srt.test.ts` 覆盖（7 例，含 CRLF、越界时间码整块跳过、`formatStamp` 全站口径），H1 只补「成片时间轴偏移」这一段的用例，不重写解析器测试。

---

## 5. 顺序、冲突与验证边界

- **批次内顺序**：H1 后端（编码器 sink + export 写 SRT）→ H1 前端复用 → H2 → H3。H2/H3 纯前端，可与 H1 后端并行开工。
- **热点文件**：`api/export.py` 是并行工程师的近期热点（档1 规格 §7.1 自己警告过）。缓解：后端改动集中在**一个可选参数 + 一个 sink + 一次写文件**，不重排既有逻辑；`_audit_film_duration` 只换数据源。
- **同树同分支**：不建 worktree；只 `git add` 明确路径，严禁宽 add；判绿一律在 `git checkout-index -a --prefix=…` 快照里，后端快照另需 `PYTHONPATH=<快照>/service`（否则 `.pth` 会把 `import dramaclip` 解析回工作树，得到假的提交绿）。
- **真机验证边界**：H1 的后端那一刀必须跑**一次真导出**才算数——`data/exports/` 与 `data/data.db` 是 live 库，需业主一句明确授权才动；无授权则本批次只交「契约 + 单测 + 门禁」，**界面不得宣称已验收**。起真 Electron 的截图验收走不含 `vite-plugin-electron` 的一次性 config + 隔离 scale 库，截图指 Temp（工具箱那批已趟过这条路）。
- **棘轮**：新增 UI 受 `measureContract` 台账与 eslint 裸字面量硬门禁约束；`srt.ts`/`CueList` 复用不新增依赖。不动档1 规格 §8「明确不动」清单（`listRow` 三态分道、外框高度链、`Rail` flex spacer、页级铺满断言等）。

---

## 6. 明确不做

- **不做**语音级对齐（word-boundary forced alignment）：那是新模型能力，不是界面人性化；本批次只如实记录已烧上去的时间。
- **不动** W2 的颜色/动效/焦点、W3 的路由合一与 `StateBlock`/`Overlay`/`cardGrid`/队列页；遇同文件让位于 W3 家族。
- **不加**数据库迁移、不加协议字段、不加依赖、不改打包与 CI。
- **不做** H4（预筛四维/`scene_count`/`peak_dbfs` 等「数据有、界面没有」）与 H5（转写编辑回声）——本批次过完再议，避免和档1 的「判据上屏」争同一块界面。
- 用户可见文案**不得**出现「消重/抗比对」类表述（合规红线）。

---

## 7. 验收口径

- **H1 前端**：jsdom 契约——逐句行渲染时间戳、点击 seek 到 `cue.start`、无 `.srt` 时走「没有时间轴」分支而非失败、内部 id 不再上屏。
- **H1 后端**：真导出一次，`.srt` 行数 == 烧录 `lines` 总数；末句 `start + 段内偏移` 落在 `probe(out).duration_s` 内；`raw_clip` 不产 `.srt`。
- **H2**：星标选中的标题刷新后仍在（读回 `plan.titles`）；`titlesApi.update` 有调用方；`PlanCard` 无死 Modal 实例；GPU 两卡同屏不再说出相反结论。
- **H3**：三条门禁全绿且每条在改前代码验红；集行/下载行/运行环境行三处失败原因可见文本非空。

### 7.1 H1 真机出片验收结果（2026-10-22 17:07，业主授权跑真导出）

跑法：隔离数据根（Temp 下一份 backup-API 快照库 + junction 指回真 `models/runtimes/voices`），**没动过 live `data/`**——live 库被运行中应用的 sidecar 独占写锁，共用数据根的第二个服务进程在启动清扫那一步就死。

- **正例**：`inner_monologue` 方案 `256e814c…` → 成片 `4bd4fa9a…`（61.331 s，`h264_nvenc` 无回退，`degraded_notes` 空）。同名 `.srt` **22 条 == 段 ass 烧录 22 行**；逐条等于「实测段偏移 + 段内相对」（±12 ms 容差）；末句止于 **61.295 s ≤ 成片 61.331 s**；8 段里 **7 段的实测偏移与声明刻度不重合**（末段 50.52 vs 声明 49.215）——用的确实是拼接实测，不是声明值。抽帧目视 25.19 s / 45.08 s 两处，画面字幕与那一行文案逐字一致。
- **反例**：`raw_clip` `2d7eab78…`（92.242 s）成片旁**无** `.srt`，`degraded_notes` 只剩与本批次无关的「候选标题生成」一条 → 「没有时间轴」没被记成降级。
- **顺带查出的真缺陷（跨盘符必炸的烧录）**：`_escape_filter_path` 在 `os.path.relpath` 抛 `ValueError`（数据目录与服务工作目录不同盘）时，把**未转义**的 `C:/…` 交给 ffmpeg；ffmpeg 在冒号处切开滤镜参数，把路径当成 `original_size` 的值，整段切割当场失败。装在 C: 而数据目录放别的盘（或反之）的用户**每次烧字幕都中**。已改：那一支落到盘符转义保底。两条门禁——`test_ass_path_beyond_relativizing_escapes_the_drive_colon`（改前红）与真 ffmpeg 量墨的 `test_an_absolute_ass_path_really_burns_ink`（证明的是 ffmpeg 认这个形状，不是字符串形状）。
- **没走通的路（不影响上面两条结论）**：本想用 `cross_narration` 一次覆盖「解说 + 原声」两提供者，被「原声空隙放不下」的闸判失败（indextts2 实测音频普遍比方案预估长，闸是对的）；`edge` 合成 403、`kokoro` 缺 `ordered_set`。两提供者混排的坐标正确性目前只有单测（`test_export_film_srt.py` 用「实测段长 ≠ 声明窗口」钉住）背书，真机双提供者待后续。另：16:04 那次 `inner_monologue` 渲染中服务进程无 traceback 静默退出（当时并发着第二个 indextts2 worker、并行会话的全量 pytest 与第三方 ffmpeg 渲染），与代码无关，重跑一次即通过。

### 7.2 H2 验收结果（2026-10-22，六项逐条对过工作树）

| 规格条目 | 落点（工作树证据） | 界面出词 |
|---|---|---|
| §2.1 星标落库 | `features/works/useWorkDetail.ts:103,120` 走 `titlesApi.update`，`onSelectTitles` 用返回的 `r.titles` 回显、失败写进常驻的 `titleProblem` | 「标题选用未保存：{原话}」 |
| §2.2 两卡口径合一 | `features/engines/GpuCard.tsx:33,37,42` 改按 CUDA 运行库实际状态出词 | 「CUDA 运行库未安装 · 转写当前走 CPU」，未装不再写「将自动启用」 |
| §2.3 指路改指按钮 | `features/engines/MachinePanel.tsx:208` 行内 `cudaInstall.start`（`:126` 注释记下原委） | 「未安装」那句旁边就是安装 |
| §2.4 空态不再指不在场的按钮 | `features/works/TitlesSection.tsx:60` 按 `hasPlan` 分岔 | 无方案时「方案已删除，候选标题与发布文案无从生成」 |
| §2.5 禁用给理由 | `ModePicker.tsx:106-110`、`PlanPickList.tsx:146-150` 勾选数为 0 时同排显式提示，按钮才 `disabled` | 「先勾选至少一个模式」/「先勾选至少一条方案」 |
| §2.6 死组件 | `PlanCard.tsx` 只剩 `:163` 一个 `open` 态与 `:177` 一个 `PlanCopyModal` 实例，`copyOpen` 那条死链已删 | — |

- **门禁 1（§4.1）落地**＝`desktop/src/__tests__/h3FailureCopyGate` 的同族件 `h2WriteActionGate.test.ts`：`services/client.ts` 导出的每个写动作都要有渲染层调用方。改前红＝`titlesApi.update` 全仓零调用方被点名（H2 实施段已录）。
- **§2 的 `ReadinessCard` `noop` 撤回**维持：唯一调用方 `OverviewTab` 两个回调都传了真值，代理报告误判。
- **测得**：H2 定点 `npx vitest run` 9 个文件 **75 例全绿**（`h2WriteActionGate`、`features/works`、`features/tools`、`h2Controls.test.tsx`、`GpuCard`、`downloadUx`）；`tsc --noEmit` 0 错。

### 7.3 H3 验收结果（2026-10-22）

**§3.1 五处 + §3.2 两处 + §3.3 三处落点**（原话一律进可见文本，`Tooltip` 只作溢出补充）：

| 位点 | 文件 | 常驻文案 |
|---|---|---|
| 集行 | `features/analysis/EpisodeListRow.tsx` | `失败原因：${error}`，库里没记也说「服务端未给出原因」 |
| 下载行 | `features/engines/AssetRow.tsx` + `assetState.ts` 的 `downloadFailureNote` | `下载失败：{原话}`；分不出原因才写「服务端未给出分类原因」 |
| 运行环境槽 | `features/engines/LocalRuntimeSlot.tsx` | 安装失败原话常驻 + `探测失败（${probeProblem}）`＝「状态未知」，不再冒充「未安装」 |
| 出片行 | `features/narration/ExportsCard.tsx` | `failureNote`：`导出失败：{reasonOr(error)}`，重试再失败改说 `重试失败：{原话}`（toast 已撤，账不再过期） |
| 目录取不到 | `features/settings/SettingsPage.tsx` + `sections.ts` 的 `FieldSpec.problem` | `风格目录取不到：{原话}` + 行内重试；取回后故障行消失 |
| 本机信息 | `features/engines/MachinePanel.tsx` | `本机信息取不到：{原话}` + 重试；`…` 只留给在飞探测，终局无数落 `—` |
| 版本行 | `features/about/AboutPage.tsx` | `取不到：{原话}` + 重试，`—` 与 `…` 按 problem 分岔 |
| 环境行 | `features/home/EnvPanel.tsx` | `探测失败：{原话}`；目录里没有必装模型写 `— · 目录里没有必装识别模型` |

- **门禁 3（§4.3）＝`desktop/src/__tests__/h3FailureCopyGate.test.ts`**（node 环境，复用 `scanSurface.rendererFiles()`）：`REASON_LEDGER` 登记 12 处失败原因位点、要求各自的原话命中「JSX 子节点」写法，外加全站 `>原因<` 禁令；`ELLIPSIS_LEDGER` 按文件钉死 `'…'` 的出现次数并要求每一处由在飞条件守着。
  - **改前红**（HEAD 快照跑同一份门禁，扫描面＝HEAD 的 169 个渲染层文件，仅把 `vitest` 换成同语义 shim，断言逻辑逐字未动）：4 条断言里 **3 条红**——12 处中 11 处的原话不在可见文本、`>原因<` 命中出片行、4 处 `'…'` 没有在飞条件守着（`AboutPage:137`、`MachinePanel:218,222`、`EnvPanel:57`）。「每文件计数不多不少」那条在 HEAD 就绿，它只做棘轮，不承担改前红。
- **门禁 2（§4.2）＝`service/tests/api/test_export_film_srt.py::test_sidecar_srt_is_readable_by_the_ui_grammar`**：解析用的是按渲染层 `features/cues/srt.ts` grammar 另写的最小镜像（**不**复用写侧 `format_srt`，自产自解会把写坏的时间码认成通过），对照面是段 ass 里真烧上去的 `Dialogue:` 行——句数、句序、正文三条都对齐，末句止于成片实测总长。
  - **三条变异锚定各红一次**：① 时间码写成界面不认的形状 ② 侧车少写一句 ③ 根本不写侧车（＝改前的代码形状，H1 那一刀已被并行会话的宽 `git add` 卷进 `10666a5`，git 里取不到「改前」，故用 ③ 复原）。
  - **「解不出＝导出失败」的口径**：没有把已 `completed` 的出片翻成 `failed`（那会推翻 §1.3 已定案的允许型降级），而是两头堵——门禁钉死「写得出来、且与实烧行一一对齐」，界面 `useSrtCues` 没有任何回退分支：404＝「本条没有逐句时间轴」（不报失败），非 404 的读失败与「SRT 里没有可解析的句子」都常驻原话，任何一支都不猜时间。
- **测得（改后复跑）**：H3 定点 8 个文件 **81 例全绿**；`features/engines` + `features/about` **238 例全绿**；`tsc --noEmit` 0 错；`ruff check` 本批次文件 0 错。
- **改前引入的 lint 债已清**：本批次新写的 6 处 eslint 错（`no-confusing-void-expression` × 4、未用导入、`prefer-optional-chain`）已改；剩下 **16 处逐行核过是 HEAD 原样**（`ExportsCard` 的 `type ReactElement`/`note.at + String(index)`、`JobDrawer`、`usePlanBatch` 超行等），不属本批次、未动。后端 `ruff` 1 错在 `engines/narration/audit.py:249`（并行 W6 的行长）。
- **全量 `npx vitest run`（桌面）＝741 例、11 红**：全部落在并行会话的 W3 路由改名与 W6 文案门禁家族（`iaContract`、`navItems` ×3、`stageState` ×3、`createDrama`、`dramaMatrix`、`TodoList`、`copyTruth` 的「指纹」），判据是这些文件本批次一行未改、失败信息一律是 `/projects/p1/analysis` vs `/drama/p1?focus=analysis` 或「指纹」注释——**待业主裁定由哪一批收口，本批次不代改**。
  - **归属复核（2026-10-23，不再只靠「没改过」推断）**：`git archive HEAD desktop protocol` 到 Temp + junction 挂真 `node_modules`，单跑那 7 个文件 → 路由家族 **10 条同名红在 HEAD 原样复现**；`copyTruth` 的「源码注释不得出现「指纹」」也在 HEAD 快照里红（该快照没带 `docs/`、`service/`，扫描面缩水会让它的其余例一起红，故只取「指纹」这一条的定性结论）。工作树 diff 里 `grep 指纹` 命中 0 行。快照跑完用 `Remove-Item` 先拆 junction 再删目录——`rm -rf` 直接穿过 junction 会删到真 `node_modules`。
- **`db1dbfd` 提交态复核**：`git archive db1dbfd service` 到 Temp，`PYTHONPATH=<快照>/service` 跑 `tests/api/test_export_film_srt.py`、`test_export_delete.py`、`tests/engines/exporter`、`tests/engines/subtitle`＝**272 passed**。首跑 70 红是快照没带只读资源：`caption_font` 要 `resources/fonts` 里的 .otf，缺字面直接 `FileNotFoundError`——判据缺失不是代码缺陷，补 `DRAMACLIP_RESOURCES_DIR` 指回真 `resources` 即全绿（`infra/paths.py:32` 认这个环境变量）。
- **本批次文件的 eslint 余量**：`npx eslint <本批次改动文件>`＝8 错，逐条 `git show HEAD:<file>` 对过字节原样（`AsrTab:107`、`TtsTab:109` 的 `onChanged?.()`；`ExportsCard` 的 `type ReactElement`、`.then(() => onRefresh())`、`.finally(() => setRetrying(false))`、`note.at + String(index)`），不属本批次、未动。本批次自己引入的两处（`downloadUx.test.tsx` 替身的未用参数）已按仓库既有写法改成 `vi.fn<(limit, activeOnly?) => Promise<…>>()`——类型带元数、实现不收参数，TS2554 与 `no-unused-vars` 一次解决。
- **全量后端 `pytest tests`＝1829 收集、4 红、0 error**：`test_scriptwriter.py::test_segments_sorted_and_overlaps_trimmed_per_episode`（`assert [22.0, 1.0] == [1.0, 22.0]`）、`test_script_driver.py` 两条、`test_rule_modes_ready.py::test_rule_mode_back_to_ready[cross_narration]`（`'failed' != 'completed'`）。被测模块 `engines/narration/{scriptwriter,pipeline,modes_w5,copywriter,numerals,audit,models}.py` 与 `api/{tools,export_audit}.py` 全是**未提交的工作树改动**（并行文案线），本批次后端只新增 `tests/api/test_export_film_srt.py` 一例，四条红与它无关。计数要显式 `-o addopts=""` 才拿得到——仓库 `addopts = "-q"` 会吞掉终态摘要行（旧坑，别再按 `tail` 有无 `passed` 判绿）。
- **格式约定不追**：`npx prettier --check src` 在 HEAD 就有约百档不合规（仓库 lint 脚本只有 eslint），本批次不整档 `--write`（会把并行会话未提交的行一起改写、把无关 diff 记到我头上），只把被自己改出空格残渣的 `tokens , layout` 四处修回。
