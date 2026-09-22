# DramaClip 桌面全站 UI/UX 定案 · 排版与密度批次设计规格

**日期**：2026-09-21 · **状态**：待用户审阅 · **分支**：`feat/correctness-wiring`
**起因**：用户对现状观感不满意（原话「感觉好廉价的感觉」），要求做一次全局 UI 与 UX 设计。
**范围裁决（用户亲手收窄）**：四个候选方向里只勾了**排版与密度**，UX 侧另加四项（长作业进度反馈 / 空·失败·部分成功统一表达 / 导入→分析→解说→出片动线 / **出片取材范围可见且可收窄**——最后一项是审阅时业主点名补上的，见 §6.5）。**品牌图形资产、层次材质、结构导航三类只作"统一来源"式收拾，不重做。**
**2026-09-22 追加（用户裁决「按②一起做，把异常修复也加进去」）**：**引擎中心的异常修复与五 tab 合一并入本批**，见 §10；合一边界是**只合并引擎中心 5 个 tab**，`/settings`、`/about`、导轨结构不动。这一追加使本批多出**两条新 RPC（`models.clean_residue`、`engines.selftest`）+ 一处既有接口的 `force` 入参**（§10.2、§10.3），故 §9 风险 6 从"唯一一处"改为两批。
**上位文件**：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md`（信息架构与页面职责）与 `docs/desktop/04-设计系统方案.md`（DSS v1 视觉真相源）。本文件**不推翻**前者；两者冲突时，**结构以 09-10 为准、本文件的 token 与状态契约优先级高于 DSS v1 的对应条目**。
**本文件不重复**：09-10 已定的导轨分组、剧空间四阶段、工具箱、后端接口缺口清单。

---

## 0. 根因判定（可反证，不是口味）

**结论：廉价感出在层级，不在字号绝对值。** 实测依据（全部指向 `desktop/src/styles/theme.ts`）：

| 对照 | 现状 token 实测 | 落差 |
|---|---|---|
| 卡内标题 / 正文 | `fontTitle 15px` / `fontBody 13px` | **1.15×** |
| 页标题 / 正文 | `fontHeading 20px` / `fontBody 13px` | 1.54× |
| 正文 / 次要信息 | `fontBody 13px` / `fontCaption 12px` | **1.08×（等于没有）** |

`fontBody 13px` 被同时当作"正文"和"次要信息"使用，这是同一 token 承载两种语义的直接后果——**层级不是靠颜色维持的就是靠不维持**。

**反证条件（写明以便日后判定这条诊断是否成立）**：若按下文把层级拉开、并在三块参照页截图复核后，首屏仍然刺眼，则真实根因是**每屏平级元素过多**（信息架构问题），要回来升级的是路线而不是继续调字号。这一条必须在参照页验收时显式判定，不许含糊通过。

三个次级根因（每条都有实测位点，构成 §1–§3 的靶子）：

1. **字阶与行高从未成对**。全站 12 处内联 `lineHeight`、**8 个不同值**：`1`、`14`、`16`、`17`、`18`、`19`、`20`、`28`（位点：`AboutPage:30,35`、`EpisodeListRow:190`、`TranscriptCard:176`、`LlmTab:43`、`PromptCard:56`、`TtsPreviewButton:72`、`EmptyWorkbench:46`、`EnvPanel:109`、`StatChips:81`、`SettingsPage:268`、`WorksDetailPage:168`）。中文正文要呼吸靠的是行高，不是字号——13px 中文配 14px 行高（`TranscriptCard:176`）是挤成一团的直接原因。
2. **内联字面量绕开已有阶梯**。间距阶梯 `4/8/12/16/20/24/32/64` 与 `font*` 字阶**都在**（`theme.ts:9,37-44,47-60`），问题不是"没有 token"。
   **实测口径（本文件所有字面量计数统一用这一条，可复算）**：扫 `desktop/src/features/**` + `desktop/src/components/**` 的 `.ts`/`.tsx`（排除 `__tests__` 目录与 `*.test.*`），按花括号配对截出每个 `style={{ … }}` 块（**含跨多行的对象**），先剥掉字符串字面量（单引号 / 双引号 / 反引号，防 `'#7C9CFF'`、`'0 14px'` 里的数字被计入），再数匹配 **`/:\s*-?\d+(\.\d+)?/`** 的出现次数——**冒号后跟数值即计一次，单位后缀可有可无**（AntD 的 style 收 number，现实里 `height: 46`、`width: 6` 都不带单位；写成"必须带 px"则命中 0 处）。锚定 **HEAD 快照**（`git archive HEAD | tar -x -C <tmp>` 后跑，避免把别的在飞改动算进基线）实测 = **248 处，跨 53 个文件**（104 个文件里 53 个至少命中一次）。其中 5 个常驻原语组件自身占 41 处（`PageKit 7`、`Rail 10`、`TitleBar 16`、`StatusBar 4`、`AppLayout 4`——原语自己就该改成读 token），**页面绕开原语的有 207 处**。
   ⚠️ 工作树当前是 **250 处**（多出的 2 处在 `PlanPickList.tsx`，属另一在飞改动，非本规格所辖）。**基线数一律按 §8.2 的"每批开工时在 HEAD 快照上复算并逐文件公布"重取，不许沿用本行的 248。**
   连常驻外框都绕：`StatusBar.tsx:54` 用 `padding: '0 14px'`——**14 不在阶梯上**、`:49` 的 `height 26` 写死；`Rail.tsx:47` 用 `width: 68`，而 `tokens.railWidth = 68`（`theme.ts:72`）**零引用**（`grep -rn railWidth src/` 只命中定义那一行）。
   ⚠️ **修正草案口径**：讨论过程中我说过的"全站 64 处""分析屏 28 处"来自一个只看单行 `style={{…}}` 的窄 grep，**按上口径复算不可重现**（同一窄口径全站是 64、分析屏只有 10——差在多行 style 对象）。以本条 248 / 45 为准。
3. **字号命名空间里混着图标尺寸**。`tokens.fontIcon = 10px` 一个值同时被当四种语义用（12 个引用位，逐位清单见 §1.3 陷阱 2）：真图标 5 处（`AboutPage:158`、`OverviewTab:116`、`ContinueCard:65`、`EnvPanel:91`、`TitleBar:237`）、**角标里的文本** 4 处（`TitleBar:37,69`、`ModePicker:141`、`EpisodeListRow:189`）、**导轨中文标签** 1 处（`Rail:101`）、**圆角** 2 处（`StepsNav:24`、`Rail:86` 的 `borderRadius: tokens.fontIcon`）。`Rail` 拿字阶当圆角不是手滑，是命名空间没分家的必然结果。

> **行号约定（读本文所有 `file:line` 前先看这条）**：行号是**写作时点工作树**的方便定位，不是判据——别的提交在同时改这些文件，行号必然漂。归段与验收的判据是 **token 名 + 文中给出的可复跑 grep 命令**；凡计数（248、9 处假图标、12 个 `fontIcon` 引用位……）都在 §0.2 声明的快照口径上复算，行号漂移不算读数错误，**计数漂移必须重发**。

---

## 1. 排版契约

### 1.1 六档字阶，行高写进同一个 token

`theme.ts` 的 `font*` 段整体替换为**成对**语义档（值即规格，不留 TBD）：

| token（新） | size/line-height | 用途 | 字重 |
|---|---|---|---|
| `text.pageTitle` | **28 / 36** | 页标题（`PageHeader` 唯一用处） | 中 500 / 西与数字 600 |
| `text.sectionTitle` | **20 / 28** | 分区标题、统计大数字 | 600 |
| `text.cardTitle` | **16 / 24** | 卡标题、弹窗标题 | 600 |
| `text.body` | **14 / 22** | 正文——**承载完整句子的最低档** | 400 |
| `text.meta` | **13 / 18** | 次要信息：数字、标签、单行元信息 | 400 |
| `text.badge` | **11 / 14** | 徽标、导轨标签、角标 | 400 / 选中 600 |

页标题对正文的落差 **2.0×**（现状 1.54×）。原 `font*` 名的映射：`fontTitleLg→sectionTitle`（22→20，降档，因为它今天实际是卡级标题在用）、`fontTitle→cardTitle`、`fontBodyLg+fontBody→body`（**两档合一，这是"正文与次要用同一 token"这条病灶的收口动作**）、`fontCaption→meta`、`fontMicro→badge`、`fontDisplay 24 / fontStat 26→sectionTitle 20`。五个图形尺寸名（`fontIcon / fontChipIcon / fontPlayGlyph / fontEmptyIcon / fontPoster`）**不进这张表**——它们是 §1.3 的 `glyph.*`。
⚠️ **`fontHeading` 与 `fontIcon` 两个名字不能按表整体替换**：`fontHeading→pageTitle` 只对三处里的一处成立，另两处是图标尺寸（详见 §1.3 陷阱 1）。

**后一条（`fontStat 26→sectionTitle 20`）是故意的降档，写清楚以免被当成笔误**：首页三枚统计芯片（`StatChips.tsx:22,23,29` 三条 `Chip` 字面量）的大数字现在配 26px（`:79` 的 `fontSize: tokens.fontStat`），与页标题同量级——**它本身就在抢层级，是"平级元素过多"的一个实例，不是层级手段**。降档后重要度改由三样承担：字重 600 + 主色 + `fontFamilyMono`（`:83` 已经在用 mono，本批只降字号）。

### 1.2 三条硬约束

- **① 承载完整句子的文本最低 14px。** `text.meta(13)` 只准用于数字 / 标签 / 单行元信息。判据可机检：任何 `Table` 单元格、任何列表主行第一列、任何解说文案渲染位，字阶必须是 `body` 及以上。理由不是好看——**本项目列表正文是完整中文句子**（15–30 字解说文案），13px 承载整句中文是"廉价"与"累眼"的同一根因。
- **② 卡片内信息层级不超过 3 档。** 一张卡同时出现"页级 + 卡级 + 正文 + 元信息 + 徽标"即为过载，必须删一层，不是缩小一层。
- **③ 中西文标题视觉等重取不同数值**：中文 500、西文与数字 600。同一 `font-weight` 下思源 500 与 Inter 600 观感等重，写死成一个数会让标题一半重一半轻。

### 1.3 命名空间分离（`font*` 退役，拆两段）

`theme.ts` 拆两段，**且 eslint 封死跨界**（§8.3）：

- `text.*` — §1.1 六档，只准出现在 `fontSize` / `lineHeight` 位。
- `glyph.*` — 图标与图形，**七枚**：`glyph.icon 10`、`glyph.railIcon 20`、`glyph.chipIcon 17`、`glyph.poster 28`、`glyph.empty 48`、`glyph.thumbW 34` + `glyph.thumbH 46`（缩略图对，`EpisodeListRow.tsx:145,150-151` 现状写死）。**内容尺寸（封面比例、缩略图、海报黑底）也归这一段**，不另起第三段。**草案里这段写的是 `glyph.icon 16`——撤掉**：全站没有任何 16px 图标位点（`grep -rhoE "fontSize: [^,}]+" src --include=*.tsx` 的取值全是 tokens 名，无 16），今天真正的行内图标尺寸是 `fontIcon` 的 **10**（10 处在用），所以照搬值是 10 而不是 16。
  承接现状错放在字号命名空间里的五个值（`theme.ts:53,57-60`）：`fontIcon 10 / fontChipIcon 17 / fontPlayGlyph 28 / fontEmptyIcon 48 / fontPoster 34`——**四个逐值照搬，一个例外**：`fontPlayGlyph(28)` 与 `fontPoster(34)` 合并为一枚 `glyph.poster 28`。理由可复核：这两个 token 各自**全站只有一处用处**（`fontSize: tokens.fontPoster` 命中 `ProjectCard.tsx:71`、`fontPlayGlyph` 命中 `WorksPage.tsx:221`），而这两处是**同一个元素**（无封面时的海报播放占位）。34 随合并退役。
  **两条迁移陷阱——它们就是这段存在的理由**：
  1. **`fontHeading(20)` 一名三职**：`WorkbenchHeader.tsx:35` 的页标题（→ 随 §1.1 升 `text.pageTitle 28`）、`Rail.tsx:34` 的导轨图标、`RecentWorks.tsx:132` 的海报占位。**按 §1.1 的名字映射做整体替换，导轨图标会从 20 涨到 28**——那不是升字阶，是走形。必须逐位点重新归段，不做名字级替换。
  2. **`fontIcon(10)` 一名四职——12 个引用位逐位归段**（`cd desktop && grep -rn fontIcon src/` 命中 13 行，减 `theme.ts:53` 定义 = **12 处使用**）：
     - **真图标 5 处** → `glyph.icon 10`：`AboutPage.tsx:158`、`OverviewTab.tsx:116`、`ContinueCard.tsx:65`、`EnvPanel.tsx:91`、`TitleBar.tsx:237`（全是 AntD 图标组件的 `fontSize`）。
     - **角标 / 徽标容器里的文本 4 处** → `text.badge 11`：`TitleBar.tsx:69`（搜索快捷键角标）、`ModePicker.tsx:141`（`NeedBadge` 文案）、`EpisodeListRow.tsx:189`（18×13 小框内的序号，配 `lineHeight: 1`）、`TitleBar.tsx:37`（22×22 品牌徽标内的 `▶`——它同时是下面假图标清单里的位点，换成随容器缩放的图标后从 text 段退出）。
     - **导轨中文标签 1 处** → `text.badge 11`：`Rail.tsx:101`（10px 中文，触 §1.2 ① 的下限）。
     - **圆角 2 处** → `tokens.radiusControl`：`Rail.tsx:86`、`StepsNav.tsx:24`。**这是现成事故**：字号 token 当圆角用，改字号会静悄悄改控件圆角（两值恰好都是 10，所以今天"看起来对"）；`radiusControl` 今天已被 15 处正确引用（含同类徽标容器 `TitleBar.tsx:32`、`AboutPage.tsx:57`、`StatChips.tsx:69`），说明这两处是漏改而非设计。
     ⚠️ **本条的计数陷阱**：`fontSize: tokens.fontIcon` 有 10 处，但**只有 5 处是图标**。按"`fontIcon` 的名字 = 图标"做名字级整体替换，会把 4 个角标文本和 1 个导轨标签送进 `glyph.*`——用图标命名空间藏文本字阶，§8.3 的命名空间↔属性矩阵门禁当场红。逐位归段，不按名字迁。
  **同构元素尺寸漂移的实测铁证**：海报/封面占位的那枚播放标记，今天有**四种尺寸**——13（`EpisodeListRow.tsx:157`、`ContinueCard.tsx:83`）、20（`RecentWorks.tsx:132`）、28（`WorksPage.tsx:221`）、34（`ProjectCard.tsx:71`）。品牌徽标另算（`TitleBar` 22×22 容器配 10、`AboutPage` 40×40 配 22——**按容器缩放是可辩护的**，不并入本条）。占位标记统一一枚 `glyph.poster`，徽标各自跟随容器，两者不互相迁就。
  ⚠️ **合并 `glyph.poster` 是有视觉变化的改动**，不是纯搬家：四处占位标记会变大（13→28 两处、20→28 一处、34→28 一处）。这属本批有意变化，**必须在参照页成对截图里显式列出这四行**（§8.2 的四项标注），不允许混在"只是收口字面量"里蒙过去。
- **数字与时间戳不另立命名空间**（避免 `metric.*` 只是 `text.*` 的别名）：仍取 `text.*` 字阶，但**必须配 `fontFamilyMono`**。这条不是新规矩——`fontFamilyMono`（`theme.ts:34`）**实测已在 11 处 / 8 个文件里用着**（HEAD 快照 `grep -rn fontFamilyMono src/ | grep -v theme.ts` 恰 11 行：`TranscriptCard.tsx:86,148`、`MachinePanel.tsx:81`、`PromptCard.tsx:50`、`PromptEditor.tsx:45`、`RecentWorks.tsx:154`、`StatChips.tsx:83`、`WorksDetailPage.tsx:157,183`、`WorksPage.tsx:186,254`）。所以判据是**补漏**而非"从零推广"：时长、集数、百分比、时间戳的渲染位，缺 mono 即为未迁；已合规的 11 处不动。

**Unicode 假图标一律换成 AntD 图标组件**（同构元素全图标或全图标，不允许一半真一半假——见 [[feedback-ui-consistency]]）。**位点实测为 9 处**，命令可复跑：`cd desktop && grep -rn "▶\|★\|▲\|▼" src/`（输出恰 9 行）。`▶` 六处——`TitleBar.tsx:41`、`AboutPage.tsx:66`（品牌徽标，换成一枚随容器缩放的 SVG/`PlayCircleFilled`，两处的容器尺寸不同是设计而非漂移）；`ContinueCard.tsx:83`、`RecentWorks.tsx:132`、`ProjectCard.tsx:76`、`EpisodeListRow.tsx:162`（四处海报/缩略图占位，统一 `PlayCircleFilled` + `glyph.poster`）。`★ ` 一处——`TitlesSection.tsx:88`（选中态星标，换 `StarFilled`）。`▲` / `▼` 两处——`EpisodeListRow.tsx:134-135`（拖序按钮，换 `UpOutlined` / `DownOutlined`）。**草案里我只点了三处**，那是只查了 `features/home/` 的结果——按三处施工必然漏掉品牌徽标和拖序按钮。验收判据：同一条 grep 返回 0 行。

**施工回写（§1.3 三处读数以现状为准，均为计数漂移必须重发的自纠）**：
1. **`glyph` 实测落成 11 枚，不是七枚**。新增四枚都为了消灭一个裸字面量：`iconMd 14`（两处真实位点：`TitleBar` 搜索框放大镜、`EngineTabNav` 导轨式标签图标，全站真实在用的第二档图标尺寸，七枚表里没有它）、`brandSm 10 / brandMd 22 / brandBox 40`（两处品牌徽标「按容器缩放」的容器边长与符号尺寸——本条既然承认「各自跟随容器是设计」，容器尺寸就必须有名字，否则它继续以 `width: 40` 裸写）。复核命令：`grep -A14 "  glyph: {" desktop/src/styles/theme.ts` 命中 11 个键。
2. **`text.body` 多出 `weightActive: 600`**，§1.1 表里没有。理由同 `badge` 的「/ 选中 600」——§3.2 的「当前查看」通道要求名称用主色**并 600**，字重必须跟字阶成对，否则又是一处「配对靠人记」。表里 `badge` 那一格本就该写成同样的形状，本条把它显式化。
3. **mono 判据要收窄成「只包数字」**。整条 `text.* + fontFamilyMono` 若套在中西混排的标签上（`共 12 集`、`下载中 45%`），`fontFamilyMono` 栈（JetBrains Mono / Cascadia / Consolas / `monospace`）没有中文字面，中文会掉到 Windows 的通用等宽映射（宋体一路），**比现状更差**。所以可施工口径改为：**数字与单位（`12s`、`45%`、`01:23`、`1.2 MB`）单独成 span 取 mono，中文留在界面字体里**。据此 `AssetKit`、`ModelDownloadPopover`、`ImportWizardLanding` 的「下载中/落位中 N%」判为**不可整段迁移**（三者的容器已各自 `minWidth` 定宽，宽度抖动这条路本就堵住了），`WorkbenchHeader` 三处计数按新口径包了数字。§8.3 的棘轮若要机检 mono，只能检「span 内含中文则不得带 fontFamilyMono」这条反向判据。

### 1.4 AntD 基线必须同批改

`theme.ts:102` 的 `fontSize: 13` → **14**。**漏这一条整个方案失效**：Table / Input / Modal / Select 继续 13，界面变成一半 13 一半 14，比现状更糟。连带核对 `components` 段（`:104-110`）里 `Button.controlHeight 32`、`Card.paddingLG`，字阶上抬后控件高度是否仍够。

---

## 2. 间距与栅格

- **阶梯不动**：`4/8/12/16/20/24/32/64`（`theme.ts:9`）保留为唯一真相源，本批**不新增档位**。新增的是**用法约束**：`style` 里出现的每个 px 必须能写成 `tokens.space*` 或 `layout.*`；写不出的说明它不是布局度量而是内容尺寸（封面比例、缩略图），那类归 §1.3 的 `glyph.*` 段。
- **字号升档的连带**：正文 13→14、行高 +8px ⇒ 同屏可视行数下降。因此**卡内 padding 从 `spaceLg(16)` 收到 `spaceMd(12)`** 作对冲，行内上下留白靠行高给，不靠 padding 硬撑。这是"中密度"的真实含义：字变大、气靠行高、不靠空白堆。
- **`layout` 段必须真的有人用**。`theme.ts:76-83` 导出的 `layout`（page / fullbleed / card / listSection / field / controlHeight）与 `railWidth` 目前**零引用**——它们是纸面真相源。本批把散落的度量收进来并**引用它**：`Rail` 宽度读 `layout.rail.width`、`StatusBar` 高度与左右内边距读 `layout.statusBar`（现在写死 26 与 `'0 14px'`）、表单标签列宽读 `layout.field.labelWidth`。
- **分栏四值逐值收口，不顺手补设定**。实测：`features/analysis/useSplit.ts:4` 的默认 `initialPct = 24` 与 `:22` 的带宽 `Math.min(40, Math.max(20, next))` 分居两处（改带宽的人看不见默认值，反之也一样）；`WorkbenchPage.tsx:106` 的 `minWidth: 250` 是左栏的**第二道下限**（拖到 20% 也可能被它顶住，两道下限不同源）；`:126` 把手 `width: 6`。收口 = 原样登记为 `layout.split = { initial: 24, min: 20, max: 40, minWidth: 250, handle: 6 }`，**五个数一个都不改**，只把它们从三处搬进 `layout` 并被引用。**本批唯一的例外**：`:128` 的 `paddingLeft: 14`——14 不在 `4/8/12/16/…` 阶梯上，无法"原样收口"，改到 `spaceLg(16)`，并在参照页成对截图里显式复核这一处变化。**不做的事**：拖拽宽度今天不持久（全站只有 `stores/lastDrama.ts` 用 `localStorage`），刷新回 24%——加持久化是新行为，不在本批，本节只消灭散落的数。
- **同一条"读现值、不改"纪律适用于另两处断口**：底部操作栏 `height: 46`（分叉两份各写一次：`StepFooter.tsx:26` 与 `PageKit.PageFooter:146`，§3.3 合流后只剩一处）、`StatusBar.tsx:49` 的 `height 26` 与 `:54` 的 `padding '0 14px'`——照现状逐值登记进 `layout`；`'0 14px'` 与上面那处同理，14 不在阶梯上。**"唯一需要改值"只在本批登记进 `layout` 的这批值里成立**：全站还有别的脱阶字面量（如 `StepsNav.tsx:22,29` 的 18 / `marginRight: 7`），它们不属 §2，由 §8.3 棘轮在碰到的那一屏收口。
- **列表行高统一**：`mixins.listRow` 补 `height`（单行 36、双行 52），派生自字阶而非另起数字。现状同一列表里行高由内容撑，是"没对齐"感的直接来源。

**明确不做**：响应式断点体系。桌面固定窗口宽度带宽余即可。
⚠️ **但 `maxWidth 1080` 这一条要先纠正我自己**：草案把它当"维持 DSS v1 的既有实现"，实测**它从来没被实现过**——1080 只活在两句注释里（`PageKit.tsx:8`、`mixins.ts:22`），`mixins.pageShell()` 给的是 `width: 100%` 且无 `maxWidth`，`theme.ts` 的 `layout.page` 里也只有 `paddingBlock / gap`。这正是 §3.3 那条"契约写了没人用"的病，只是方向相反（文档有、代码无）。处置二选一、不许留第三种：**要么**加 `layout.page.maxWidth = 1080` 并让 `pageShell` 真读它（内容页随之居中），**要么**删掉那两句注释、承认内容页就是满宽。参照页截图时按选定那条如实呈现。

---

## 3. 组件层与资产纪律

### 3.1 契约定在"原型"，每屏只写例外

19 屏逐张画不叫覆盖——第 20 次改动照样凭记忆漂。做法：把屏归成 **7 个版式原型 + 覆盖层 + 外框**，契约（字阶、栅格、四态、进度位、动作位）定在原型上，每屏只声明"套哪个原型 + 我这屏的例外"。**归错原型或漏屏会在全站清单表上直接看出来，画 19 张图不会。** 清单见附录 A。

| 代号 | 原型 | 契约要点 |
|---|---|---|
| P1 | 双栏概览 | 左主内容 + 右环境/提示侧栏；统计芯片一行三枚，芯片内 ≤3 层级 |
| P2 | 卡片库 | 网格 `minmax(236px,1fr)`；封面 9/16；卡片四态齐备才算完 |
| P3 | 详情双栏 | `minmax(300px,420px) + 1fr`；列表行复用 `mixins.listRow` |
| P4 | 主从编辑器 | 左栏按百分比可拖（`layout.split` 五值，见 §2）+ 右栏多卡 + **底部批量条**；左栏只放选择，不放编辑 |
| P5 | 流水线 | 四段纵向；任务行 = §4 三件套常驻 |
| P6 | 配置中心 | tab 收进同一 `tabs` 契约；卡容器一律 `PageSection` |
| P7 | 元信息 | 窄单列 `max-width 720`，无侧栏 |
| O | 覆盖层 | 统一 `Overlay`：标题 `cardTitle 16/24`、宽 720、footer 右对齐 |
| C | 外框 | `TitleBar` / `Rail` / `StatusBar` / `ErrorBoundary` |

### 3.2 三态分道法（本批最重要的组件级裁决）

列表行有三种"被强调"的原因，**必须用互不相干的视觉通道**，否则用户分不清自己是在勾选还是在浏览：

| 态 | 通道 | 定义 |
|---|---|---|
| **已勾选** | 复选框 + 行底 7% 主色 | 唯一的铺底语义 |
| **当前查看** | 左 3px 竖条 + 名称用主色并 600，**不铺底** | 唯一的竖条语义 |
| **悬停** | 只换背景，不加边框不加竖条 | 最弱一档 |

现状三态**撞在一起**，而且撞在共享原语上：
- `mixins.listRow(:78-87)` 的 `active` 直接铺 `accentSoft`——所有走它的列表都把"选中"渲染成"当前查看"；
- `mixins.hoverBg(:90)` 的值 **等于** `accentSoft`，即悬停与选中同一底色，两态天然不可分；
- `EpisodeListRow.tsx:88-91` 更彻底：竖条、铺底、名称主色（`:111`）三样一起上，和该行的复选框（`:211`）抢同一视觉通道。

修法：`listRow` 拆成 `listRow({ checked, active })` 两个独立入参、两通道各写各的；`hoverBg` 改成中性一档（`bgElevated`），**把铺底这一通道整个让给"已勾选"**。这条不改，§6.2 的默认勾选（前 `full_threshold` 集）会渲染成一屏蓝、看不出到底勾了什么。

### 3.3 消灭分叉

`StepFooter.tsx:6-55`（`features/analysis/`）与 `PageKit.PageFooter:126-172` 是一对分叉，实测**签名逐字节相同**（`:6-22` vs `:126-142`）。真正的差异只有两处：StepFooter 的「下一步」外面套了 `<Tooltip title={canProceed ? '' : '完成至少一集分析后解锁'}>`（`:42`），以及 `padding: '0 16px'`（`:31`，裸字面量）对 `padding: \`0 ${tokens.spaceLg}\``（`:151`，`spaceLg`=16px，**渲染完全相同**）。也就是说：**活的那一份多了一个解锁提示，死的那一份多了一个 token 引用。**

关键实测：`PageFooter` 全站**零调用点**（`grep -rn "PageFooter" src/` 只命中 `PageKit.tsx:126` 的导出本身）；`WorkbenchPage.tsx:10,55` 用的是 `StepFooter`。所以这不是"页面各自造轮子"，而是**唯一活的实现长在功能目录里、布局原语是一份没人用的副本**。

处置（不需要向后兼容）：把 Tooltip 并进 `PageKit.PageFooter`、`WorkbenchPage` 改用 `PageFooter`、**删掉 `StepFooter.tsx` 整个文件**。同一件事两份实现将来必漂——留着漂移过的那份、删掉没人用的那份是反的（见 [[feedback-cleanup-on-pivot]]）。

### 3.4 资产纪律：颜色与重复色板

- `WorksPage.tsx:13` 的 `MODE_COLORS` 六个裸 hex 与 `tokens` **逐一重复**（`#7C9CFF`=colorPrimary、`#9B7BFF`=colorAccent、`#34D399`=colorSuccess、`#FBBF24`=colorWarning、`#F87171`=colorError、`#60A5FA`=colorInfo，见 `theme.ts:13-20`）。改为**从 tokens 派生的数组**，模式色只有一处真相。
- **其余字面量色位点：全量清单（三条命令可复跑，前版说"只剩四处"是漏扫，实测见下）**
  - `cd desktop && grep -rnE "#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b" src --include=*.ts --include=*.tsx | grep -v "src/styles/theme.ts" | grep -vE "__tests__|\.test\."` → **9 行 = 6 个位点**（`WorksPage` 与 `machineFit` 各是一行多色）：`WorksPage.tsx:13`（`MODE_COLORS` 六枚，上条已述）、`engines/machineFit.ts:84-87`（ok/tight/disk/ram 四枚，全是 success/warning/error 的复制）、`layout/TitleBar.tsx:238` `'#C43A3A'`（关闭按钮热区色，非重复色 → 收进 `theme.ts` 或改 `colorError`）、`analysis/StepsNav.tsx:31` `'#FFFFFF'`（`tokens.colorWhite` 已存在）、**`analysis/PlayerCard.tsx:29` 与 `works/WorksDetailPage.tsx:88` 各一处 `'#000'`**（视频/海报的黑底——**这两处是草案漏掉的**）。另有两行是注释里的 `#FF4D4F` 禁令（`EpisodeListRow.tsx:233`、`TodoList.tsx:7`），不计位点。
  - `grep -rnE "rgba?\(" src --include=*.ts --include=*.tsx | grep -v "src/styles/theme.ts" | grep -vE "__tests__|\.test\."` → **10 处**，全在海报 scrim 与阴影上：`rgba(0,0,0,0.72)` 在 `RecentWorks.tsx:152,162` 与 `WorksPage.tsx:243,252` **逐字重复四份**、`linear-gradient(180deg, rgba(0,0,0,0) 50%, rgba(0,0,0,0.68) 100%)` 在 `RecentWorks.tsx:138` 与 `WorksPage.tsx:226` **逐字重复两份**（同一枚"海报底部渐隐"写了两遍，正是 §3.1 原型契约要收的东西）、`ProjectCard.tsx:97,112` 两种黑 alpha、`TitleBar.tsx:170` 与 `SettingsPage.tsx:110` 两处裸 `boxShadow`（`tokens.shadowPop` 全站只有 `RecentWorks.tsx:99` 一处在用，近乎空转）。
    ⚠️ **上面这条命令按 `rgba(` 扫，天然扫不到"用变量拼出来的阴影"**：`grep -rn boxShadow src/ | grep -v theme.ts` 复算得 12 行，其中三处是同一枚状态光晕 ``boxShadow: `0 0 6px ${color}` ``——`StatusBar.tsx:68`、`OverviewTab.tsx:99`、`mixins.ts:99`。**组件里那两处是 `mixins` 已有能力的重复实现**：`mixins.ts:93 statusDot(color)`（`width/height 6` + `radiusDot` + `background` + 同一枚 `0 0 6px` 光晕）已被 5 处在用（`AssetKit.tsx:18`、`GpuCard.tsx:113`、`ReadinessCard.tsx:88,145`、`TodoList.tsx:57`），而 `StatusBar.tsx:62-69` 把同一组度量手抄了一遍。收口 = 改调 `statusDot`，不是再抄一份常量。另两行 `RecentWorks.tsx:43,103` 的 `boxShadow: 'none'` 是重置、`:111` 是 transition 字符串，都不算色板位点——**写清哪些不算，门禁才不会变成数字游戏**。
  - **`token` 拼 alpha 的模板串 = 第二套隐形色值，按 hex 扫的棘轮根本测不到**：`grep -rnE '\$\{tokens\.[A-Za-z]+\}[0-9A-Fa-f]{2}`' src --include=*.ts --include=*.tsx | grep -vE "__tests__|\.test\."` → **7 处 / 5 个文件**：`EpisodeListRow.tsx:159`、`IndexttsRuntimeSlot.tsx:20,21`、`LlmTab.tsx:45,46`、`ModePicker.tsx:145,146`。**alpha 值本身有五种**（`1A / 44 / 0d / 55 / 12`）表达的却是同一件语义（"某个状态色的软底"）。修法不是逐处换成 hex，而是**立一档半透明阶梯**：与 `accentSoft` 同族命名（`…Soft`），按语义给 success/warning/error 各一枚，七个位点全部改读它；`IndexttsRuntimeSlot.tsx` 属引擎屏（另一位工程师的属主区，已于 `e6d57fe` 入库），**本批不主动重写它的内部逻辑**，只在同屏改字阶时按 §8.3 棘轮把这两处拼色收进 `…Soft` 阶梯。
- **棘轮三条禁令**（§8.3）：hex 字面量、`rgb()/rgba()` 字面量、`` `${tokens.…}XY` `` 模板拼色——三者都只准出现在 `theme.ts`。阴影类走 `tokens.shadow*`，禁止在组件里手写 `boxShadow` 字面量。
- **红色 `#FF4D4F` 只给钩子语义**（既有定案，不因本批改动）。角度名沿用 warning 金 `#FBBF24`，不得占用钩子红。
  **本批不为钩子红新增 token**：实测桌面渲染层今天**没有任何钩子色位点**——`#FF4D4F` 在 `desktop/` 只出现在 3 处注释与测试里（`EpisodeListRow:233`、`TodoList:7`、`TodoList.test:83`），全作为"**不得**使用"的引用。为一个不存在的用法造 token 是投机；等钩子视觉真进界面（封面 / 字幕侧）时再进 `theme.ts`。

---

## 4. 长作业进度契约（P5 / C 外框）

产品有 5–20 分钟级的出片作业，用户会离开当前屏去做别的。契约三件套**常驻任务行**，并同步到状态栏：

```
阶段 n/N · 当前阶段名   [====进度====]   62%  还需 4 分
```

规则（每条都是可判定的，不是风格）：

1. **三件套同时出现**：`阶段 n/N` + 百分比 + ETA。缺任一项显示 `—`，**禁止**用 0% 或假估算占位（"未验证的东西不能发通行证"的同一条纪律）。
2. **ETA 无历史样本时显示 `—`**，不显示猜测值。首个作业、或阶段切换后样本不足以线性外推时，只给百分比。
3. **进度单调不回退**：阶段从 3/5 回到 2/5 必须是显式的"重跑"事件，否则夹住不动。
4. **降级必须上任务行**，不能只进日志：某条方案走了规则编排，行内要有金色标记 + 一句原因 + 「重掷」。这是 09-10 界面主张 1 的落点。
5. **状态栏常驻在跑任务**：现状 `StatusBar.tsx:61-77` 的四项是服务 / FFmpeg / GPU / 版本，**没有任何在跑作业**；无作业时整段收起，不给空占位。
6. 状态栏信息**分级**：现状四项同为 `fontMicro 11px`、无分组（`fontSize` 在容器 `:57` 一处给死），把"有活儿在跑"和"ffmpeg 版本"压成同一个重要度。改为在跑任务 `13/18 · 500`、环境元信息 `11/14`，段间留气口。

实测缺口：出片轮询 `poll.ts:2 POLL_INTERVAL_MS = 1500` 拿到 `Progress percent` 但**算不出也不显示 ETA**；`ExportsCard.tsx:27` 的状态只剩一个三值标签（`完成 / 失败 / 进行中`），整份文件不含任何 `Progress` 或 `percent` 渲染——**进度数字根本没被读到过界面**。

---

## 5. 空 / 载入 / 失败 / 部分成功：统一 `StateBlock`

新增一个组件承担四态（P1–P7 全部复用，O 亦复用），契约：

| 态 | 视觉 | 必含 |
|---|---|---|
| 空 | 中性图标 `glyph.empty` + 一句"这里会有什么" + 主行动 | 一个主按钮；文案说清下一步做什么 |
| 载入 | 骨架（`Skeleton`），不是转圈 | 骨架行数贴近真实密度 |
| 失败 | **内联横幅**（不是只有 toast）+ 原因 + 「重试」 | 原因来自服务端字段，不许只写"失败" |
| 部分成功 | `成功 X / 失败 Y` + 可展开到失败项 | 失败项逐条列出，每条可单独重试 |

**为什么内联而不是 toast**：toast 会消失。用户 20 分钟后回到这屏，仍必须能看出这批里有 3 集没成——这与"模型到底看到了什么必须可见"是同一条主张。

**验收口径（不依赖我给的总数）**：附录 A 的"四态"列即缺口清单。本批完成的判据 = **该列不再出现「无 / 永不 / 仅加载中 / 只有 toast」字样**，且每处缺口的修法都能指回本节表格的一行。**不发布聚合计数**——上一版我写的"9 处"与自己那张表对不齐（逐条重数是 12–13 处，取决于"保存失败只有 toast"算一处还是两处），说明计数本身就是个不可判定的口径，清单才是。

一条必须点名的实测：**`ProjectsPage` 失败后永久转圈**，且有**两条**路径停在同一个形状——① `useProjects.ts:23-25` 的 `load()` 里 `setProjects(await projectApi.list())` **完全没有捕获**，初始 `project.list` 一失败就是 unhandled rejection，`projects` 永远停在初始值 `null`；② `ProjectsPage.tsx:35` 把 `ensureCovers().then(() => reload())` **整条链** `.catch(() => undefined)` 吞掉。而渲染判据 `:138` 是 `if (projects === null) return <Card loading />`——**失败与载入同形**。**这不是缺一个态，是把失败态伪装成载入态**，属于禁止降级那条纪律在界面上的对应物。
一个必须写死的区分，否则 `StateBlock` 会被接错：`null` = 从未取到数据，`[]` = **真·零项目**。判据按"最后一次成功完成的加载"分流——成功过就按长度分流（`[]` → 空态），失败过就进失败态；**任何情况下 `[]` 不得渲染成骨架，`null` 不得当成空**。

---

## 6. 动线：导入 → 分析 → 解说 → 出片

结构（导轨分组、剧空间四阶段、阶段条只读）**沿用 09-10 定案，本批不动**。本节列动线上的**五处**断口，其中 §6.4 只记边界、不在本批实现，其余四处本批补齐：

### 6.1 多选的可见性 = 计数回声 + 底部批量条

全站三个多选场景（模式、方案、剧集），**只有剧集不回显已选数**——这不是不好看，是**同构元素走样**，也是"廉价"最直接的来源。而且这一条把静默失效暴露了出来：

> `WorkbenchHeader.tsx:55` 的「批量分析所选」判据是 `disabled={total === 0}`，**完全不看勾选**（`running` 时整颗按钮被 `:49-58` 的三元换成「取消分析」）；`useAnalysisWorkspace.ts:95` 算好的 `canStart`（接口 `:111` 声明）**全站零消费**（`grep -rn canStart src` 命中只有这两处）；空选点下去撞 `:68` 的 `if (selectedIds.length === 0) return;`——**静默无事发生**。

契约：
- **表头回显** `已选 N / 总`（对齐既有约定：`ModePicker.tsx:33`「已选 N / 9 个模式」、`PlanPickList.tsx:91`「已选 N / M 条方案」——这两处今天都做对了，剧集列表是三个多选场景里唯一漏的）。
- **批量动作锚回勾选发生的地方**：左栏底部**批量条**（勾选非空才出现），内容为「已选 N 集 · 其中 M 集已分析，将重跑 · [批量分析] · 取消选择」。页头右上角那颗按钮不再是唯一入口（跨整屏找按钮是现状最大的动线成本）。
- 按钮的 enabled 判据统一用 `canStart`（同时修掉 §附录 B 的第 ④ 条缺陷）。

### 6.2 默认勾选 = 前 `full_threshold` 集（改读设置，不立新数字）

代码现状是 `useAnalysisWorkspace.ts:14` 初始 **空数组**——进页面一集都不勾。

**草案里我定的"默认前 10 集"作废**（业主指出漏掉的调度分支，复核实锤）：这个数**产品里已经有了**——`analysis.full_threshold`（`infra/config.py:18` 默认 **15**），消费端 `api/analysis.py:53-78 autostart_after_scan`，由 `api/project.py:134-136` 在扫集落库后立刻调用：

- 集数 ≤ 阈值 → 直接 `analysis.start` **全量分析所有集**；
- 集数 > 阈值 → `prescreen(then_analyze=True)`：先轻量预筛，只分析入选集。

再立一个 `DEFAULT_SELECTED_EPISODES = 10` 就是同一含义的**第二处**真相源（第一处是这个键本身；设置页字段 `sections.ts:43-49`「自动全量分析集数上限」已经在呈现它），两处并存必然漂移。契约因此改成**读，不写死**：

1. **唯一真相源 = `analysis.full_threshold`**：默认勾选数从设置当前值取——`rpc('settings.get')` 全量返回该 map（`SettingsPage.tsx:44` 已在用同一条），前端不留字面量、不再另立常量。
2. **按当前排序**取前 N；不足 N 集全勾；**用户手动改过勾选后不再自动覆盖**他的选择；阈值在会话中被改动时不追溯重算已勾集合。
3. **默认态必须可辨识、可反悔**：表头写「默认前 N 集」（N 为读到的值），批量条写「其中 M 集已分析，将重跑」。重跑是真花时间和钱的——**规则可以简单，副作用不能藏。**
4. **默认勾选与自动调度的关系必须上界面**（这是上一条规则真正的风险所在）：≤ 阈值时扫完集已经自动全量跑完，此时"前 N 集"的真实语义是**整剧重跑**；> 阈值时它的作用是**补跑预筛未入选的前 N 集**。同一个复选框在两种调度下语义不同，界面不说清就是让用户猜着花钱。批量条的「其中 M 集已分析，将重跑」就是这句话的落点——M 等于总集数时，它显示的是一整剧重跑，不是"选了 15 集"。

### 6.3 服务未就绪不得表现为空白屏

`useAnalysisWorkspace.ts:43` 在服务未就绪时直接不加载（`if (serviceState === 'ready') void loadAll();`）→ 用户看到空白屏，不知道为什么。改为渲染 `StateBlock`（载入 / 失败分支）+ 一条指向引擎总览的可点提示；状态栏的服务状态位与之同判据、同可点（**同一状态，两处入口，不许一处哑一处响**）。

### 6.4 跨页勾选传递（记为边界，不在本批实现）

分析页与出片页各持 store、勾选传不到——这是 09-10 判定的批量断裂根因（`2026-09-10-dramaclip-ui-redesign-design.md:63-64`：两页**废弃 → redirect `/drama/:id/...`**、"分析页勾选的集传不到出片页，是批量断裂的根因"）。真正的修法就是那条已定案的合并——那是结构改动，**属 09-10 批次，本批不吞**。本批只保证：两屏各自的三态与回声都合规，不让缺失的传递伪装成"已经选好了"。

### 6.5 出片取材范围：可见 + 可收窄（P4 / P5 交界）

业主复核定稿时点名的第二处缺口。**核实过程中我原以为缺口比实际更大——以下按实测重写，并把两处过头的话标出来，免得下一轮照着错话说服人。**

先说清楚"取材"在今天到底是什么（全部为工作区实测，位点可查）：

- **候选池 = 已完成分析的全部集**：`api/narration.py:252-256` 硬取 `episodes_repo.list_by_project(...)` 里 `status == "done"` 的集，入参侧只有 `project_id / modes / k / exclude_plan_ids`（`narration.py:241`、`:244`、`:259`、`:270` 四处读取，别的全被契约的 `additionalProperties: false` 挡掉），`usePlanBatch.ts:40-43` 也只发前三项。**没有任何一条路径能收窄这个池。**
- **"用哪些集"是模型选的，不是配置**：选题把整池转写喂给 LLM（`engines/narration/angles.py:134`、提示词 `:145` 原文要求"每条角度的 `episode_numbers` 给出这条片要用到的全部集号"），产出的 `_Variant.episode_numbers`（`api/narration.py:185-192`）再决定装配范围：`dialogue_narration` 按集号筛转写（`:446-452`），其余模式由 `_casting_for:485-520` 按集号取场景/高光/台词。模型答了池外集号会被整批否决（`angles.py:102-104`，判据 `:68`"绝不拿残缺的凑够 K 条"）。
- **界面上看得到"几条取材"，看不到"取材了谁"**：方案卡 `planCards.ts:41` 渲染 `取材 ${plan.episode_ids.length} 集`——**一个计数**。而卡片自己的契约写的是「取材集区间」（`planCards.ts:2`、`__tests__/planCards.test.ts:56`），`plan.episode_ids` 本来就在返回体里。**承诺过区间、交付了个数**，这是本条真正的可见性缺口。
- 重叠也已经在算：同模式同取材集 100% 直接不出（R7 闸门 `:222-235`）、跨条重叠超 `OVERLAP_LIMIT` 不出（`:361-365`），卡片回显「取材重叠 NN%」。

**两处过头的话，撤回**：① 我起草时写过"取材范围只存在于服务端一行过滤里"——不成立，`_Variant.episode_numbers` → `_casting_for` 是一条完整的取材链，还带自己的验收与重叠闸门；② "界面上完全看不到"——也不成立，卡片有「取材 N 集」与「取材重叠 NN%」。准确的说法是：**池不可见也不可改，单条方案的取材只有数量没有身份。**

所以缺口成立，但比草案里说的窄。契约：

1. **池常驻可见**：出片屏（P5）顶部一条「本次取材：已完成分析 X / Y 集」。`X` 与 `Y` 同源服务端统计，不由前端数 `episodes.length` 反推——前端算的是"勾了几集分析"，不是"哪些集进了选题"。
2. **单条方案的取材从计数改成点名**：卡片「取材 N 集」补上可点的集号（数据已在 `plan.episode_ids`），兑现 `planCards.ts:2` 自己写下的"取材集区间"。这一条**零接口改动**，是纯前端补欠。
3. **可收窄**：区间（第 a~b 集）或逐集勾选，二选一即可，不必都做。收窄后条上回显「已收窄到 Z 集」+「恢复全部」。
4. **后端补一个入参，且必须收在选题之前**：`narration.plan_variants` 增 `episode_ids`，**缺省 = 全部 done 集**，不传时语义与今天逐字一致。改一处不够：`protocol/schemas/narration.json:211` 是 `"additionalProperties": false`，光加服务端参数会被 schema 挡掉，所以**契约改动 = schema + 服务端 + 契约测试三处同批**。这是**本规格新增的一条接口缺口**：09-10 那份清单就是它 §5 表里 RPC 列标「新」的行（`2026-09-10-...-design.md:354` 起已改成"以表为准、不发布聚合数"——原先那句"29 处 = 25 全新增 + 4 扩展"按行数得 33、按去重到接口改动点得 27，两个口径都复算不出 29，故撤回）。**本条不并入那个数**，只说明它是清单外新增的一项：表里 #16 / #17 / #20 三行（`:314`、`:315`、`:318`）都是 `narration.plan_variants` 的**其它入参**（整组重规划 / `exclude_plan_ids` / `modes`），没有一条是取材范围，所以它不是"把已有的一行做全"，而是**多出一个入参**。
   **为什么过滤点只能在 `done_episodes`**：`episode_inputs` 同时是选题的转写输入（`angles.py:134`）和 `known_numbers` 的真相源（`:137`），所以窄化池会自动窄化"模型被允许选谁"与"验收放行谁"，一处过滤三线同频，`_run_plan_variants:307` 与下游签名都不用改。反过来，**若放在选题之后过滤**，模型会照常点名池外的集，`_sanitize:102-104` 的整批否决就会变成"改了收窄、K 条全没了"——这是本条唯一真正的实现陷阱。
5. **收窄的代价必须同屏回显**：参与选题的集数变少 = 角度池变小 = K 条方案更容易同质（重叠闸门 `:361-365` 会更频繁地吃掉角度）。收窄后条上直接显示"参与选题 Z 集"，不让用户收窄完只看到方案变差却不知道原因。
6. **两条通道不共用 store**：分析页勾选回答"跑哪些集"，本节回答"用哪些已完成的集"，语义不同、生命周期不同（前者在跑完后失去意义）。合店属 09-10 结构批次，本批只保证两屏各自回显正确。
7. **与 09-10「剧空间 ① 投料」不重复、不冲突**：09-10 `:180` 已把素材列表（勾选 / 排序 / 逐行三态 / 单集重试）定在剧空间第一阶段。本节**不建投料段**，只在今天的出片屏上补"取材可见 + 可收窄"这一条最小面；剧空间落地时，取材状态**同源汇入 ① 投料**，届时节 3 的收窄控件即为投料勾选，不留两套。

**勘误（同批必改，因为它会误导下一次清扫）**：09-10 规格在三处断言 `analysis.full_threshold`「有字段却全库无消费端」「代码里没有这条分支」（§3.3「参数未生效」行、§4.6 键表后的正文、§8 ⑧）。今天不成立——消费端是 `api/analysis.py:53-78`。那条断言的处置建议是"指不出读它的那行代码就删或接线"，照旧文执行会把唯一的阈值真相源删掉，§6.2 就得退回头疼医头的字面量。**已在 09-10 原文件这三处回写勘误**；同批把 §4.6 键表里另外两条随之失效的断言一并标注（`export.width/height`「控件无」→ 9fbd1f5 起 `sections.ts:100-101` 有字段；`export.encoder`「已删」→ 同一提交因 NVENC 探测把它接回来了），并把行号锚点按当前树重测（`api/export.py` `_output_size` 182→`247-251`、`default_preset` 消费端 241→`300`、`loudness.py` 136→`87-88`、`config.py` 响度两键 40→`43-44`）。**除这些"当时为真、此后被别的提交改掉"的事实外，09-10 的设计结论一字未动**，缺口清单仍是它自己的清单（本规格 §6.5 是在它之外多出的一个入参，不并入其点数，另说）。


---

## 7. 字体随包、许可与合规

### 7.1 随包内嵌（决策理由是可复核性，不是"更好看"）

现状 `global.css` 字面栈是 `Segoe UI / PingFang SC / Microsoft YaHei / system-ui`——**系统字面意味着同一构建在不同 Windows 版本拿到不同雅黑、mac 上没有雅黑，改前/改后无法机器判定**。基线截图对比要成立，字面必须是随包的。

- **界面**：Inter 可变字体（一个文件 **48 KB**）+ 思源黑体 woff2 全量子集，只带 **400 / 500** 两档 = **2.3 MB**。实测官方简体全量子集 woff2 每字重 **1.14 MB**（我先前估的"子集 3–6 MB"是错的），因此**取消构建期扫源码裁子集那个脚本**——直接随包全量子集。
- **字幕**：继续 OTF。**两份并存且都要留**：libass / DirectWrite 读不了 woff2，而 Chromium 吃 8.3 MB OTF 等于白付 7 MB。同一字面、两种容器。
- 与**立案 D（字幕字体随包兜底）**的边界：立案 D 管"渲染与拆行共用同一字体真相"（`ass_generator.py` 的 `_GLYPH_ADVANCE_PERCENT`、ffmpeg `ass` 滤镜的 `fontsdir`），本批管界面字面。**执行顺序 = 先收尾立案 D 再开 UI**——它已写完八成但测试为红，留着会污染后续每一次 commit-green 判定。

### 7.2 许可与合规

- **OFL 1.1 要求许可文本随包**：`resources/fonts/` 今天是 `NotoSansSC-Regular.otf`（8,331,336 字节）+ `OFL-NotoSansSC.txt` ——**一份许可、一个字重**（⚠️ 该目录**尚未入库**：`git ls-tree -r HEAD` 无 `resources/fonts`，它是立案 D #92 在飞的未跟踪产物，HEAD 里根本没有随包字体）。本批新增 Inter 与思源 500 档，各自的 `OFL.txt` 一并进目录，**一份许可覆盖两种字面是不成立的**。
- **「关于」页开源清单必须新增这两条字体**：`AboutPage.tsx:14` 今天是一行九个名字的字符串常量（Electron / React / Ant Design / FFmpeg / PySceneDetect / OpenCV / faster-whisper / edge-tts / Kokoro），**没有任何字体项**——分发含字体的二进制包本就该有。
- 本批不新增任何对外文案。合规红线照旧：**「消重 / 抗比对」不得作为用户可见卖点**（¥1.85M 判例）；AI 生成图片须带显式标识（2025-09-01 施行）。见 [[project-compliance-red-lines]]。

---

## 8. 参照页、验收与门禁

### 8.1 实施路线 = 参照页先行（用户选乙）

契约层（§1–§3）与进度 / 状态契约（§4–§5）先落，然后**三块参照页**：

1. **分析工作台**（P4，"廉价"最重的一屏，见 §8.4）
2. **成品库**（P2 卡片库 + 海报 + 角标）
3. **成片详情**（P3 详情双栏）
4. **引擎中心**（P6 配置中心，§10.4 合一后的单页六段）——**2026-09-22 追加**：它既是本批唯一一处功能级改动，也是 P6 原型的唯一代表屏，不进参照页 = P6 的契约没人验过。

截图定版、用户认可后再按页推其余屏。**先做全站再截图 = 用 15 屏返工换一次判断机会。**

### 8.2 基线截图与机检断言

- **改前基线**：随包字体、固定窗口尺寸与 DPR、**100% 与 150% 缩放各一组**（中文 11px 在 150% 下最容易暴露问题）→ 实现后**同参数重拍**。
- 机器侧断言：脚本按 §0.2 口径扫 `style={{…}}`（实测份额——分析屏 45、成品库 `WorksPage` 11 + `TitlesSection` 3、成品详情 4）。**"归零"的准确对象是带 px 语义的度量**（宽高、内边距、外边距、间隙、圆角、行高）；同一口径里还含 `flex: 1`、`minWidth: 0`、`zIndex` 这类**无单位结构值**，它们不是度量、不进 token，也就**不该被算作未改**——把它们混进"归零"会让门禁变成数字游戏。判据两句：① 度量类字面量归零；② 改后用同口径复算并按文件公布差值，剩余项逐条标注为结构值或写进本屏例外。**口径一旦写下就不再改**：改口径 = 重测全部基线。
  ⚠️ **一处必须撤回的草案数字**：讨论中我说过"分析屏 45 → 38"，那是**估的**，没有复算依据（本屏实际会消失的是 `WorkbenchPage` 的 250 / 6 / 14 与 `EpisodeListRow` 移入 `glyph.*` 的 34 / 46 / 18 / 13 等，减几取决于改到哪一步）。规格不预测差值，只在改后复算并公布。同理，§8.1 里"用 40 处返工"一句按可推导的口径改成屏数。其余 16 屏不进这条门禁，由 §8.3 棘轮接管（一碰就必须归零）。
- 每屏改前 / 改后成对图，**对比结论在聊天里给，不写文件**。每张图必须带**四项标注，缺一不可**：字阶档位、该行高成对值、栅格落点（token 名）、状态变体。不带字阶档位的图 = 没做，因为下一屏无法据此复现。
- **引擎页额外两条机器判据（§10 的验收，排版门禁管不到它）**：① 组件测试断言"每个异常态行都渲染出至少一个动作按钮，且该按钮的 handler 不是 `navigate`"——这条封掉 §10.0 第 2 类缺陷复发（`ReadinessCard.tsx:104-109` 那种跳转穿修复外衣）；② 契约测试断言 Small / Medium（warn 降级后）两类校验结果下 `canActivate` 为真、warn 文案进入 `failureNote`（§10.1 三条改法的直接回归网）。**判据用 §10.0 量到的真实文件形态做 fixture，不用编造样例。**

### 8.3 eslint 棘轮

现状（`eslint.config.mjs:46-63`）只管 `fontSize` / `borderRadius` 的字面量。本批扩面，**只对改动文件生效**（棘轮：未迁页面不报错、一碰就必须归零）：

- 新增禁令：`padding` / `margin` / `gap` / `lineHeight` 的字面量 → 必须 `tokens.space*` 或 `layout.*`。
- **命名空间只准出现在自己的属性位**（§1.3 的机检形式）：`text.*` 只准在 `fontSize` / `lineHeight`；`glyph.*` 只准在 `fontSize`（图标）与 `width` / `height`（图形）；两者都**不得**出现在 `borderRadius` / `padding` / `margin` / `gap`。这条直接封掉 `borderRadius: tokens.fontIcon`（实测两处：`Rail.tsx:86`、`StepsNav.tsx:24`，而 `TitleBar.tsx:32`、`AboutPage.tsx:57`、`StatChips.tsx:69` 已经在正确读 `radiusControl`——15 处 `radiusControl` 引用说明那是漏改，不是设计）。
- **颜色三条**（§3.4）：hex 字面量、`rgb()/rgba()` 字面量、`` `${tokens.…}XY` `` 模板拼色、组件内裸 `boxShadow` 字面量——一律只准出现在 `theme.ts`。
  ⚠️ **这三条的覆盖面边界必须写明，否则是假门禁**：eslint 只解析 `.ts/.tsx`，**`src/styles/global.css` 里那 7 枚裸 hex**（`:9 #10141C`、`:10 #e8eaed`、`:27 #262f47`、`:32 #3d4d73`、`:48`、`:79` 渐变两枚）**在机器判据够不着的地方**——其中 `#7c9cff / #9b7bff` 与 `tokens.gradientAccent`（`theme.ts:30`）逐字重复，是第二处品牌渐变真相。收口方式不是假装 eslint 管得到，而是 §7.1 改 `global.css`（加 `@font-face`）时同批把这些值改成 CSS 变量、由 `theme.ts` 单点导出；人工复核项进 §8.2 的成对截图。

### 8.4 参照页一（分析工作台）的已知清单

P4 是整站唯一 `mixins.ts` 与 `PageKit.tsx` **零引用**的 feature（`features/analysis/` 11 个组件全裸写 AntD 卡）。按 §0.2 口径实测本屏 **45 处内联数值字面量**（`EpisodeListRow 14`、`WorkbenchPage 8`、`PlayerCard 5`、`TranscriptCard 5`、`StepsNav 5`、其余 8）；本屏 **26 处 `fontSize` 声明里只有 2 处配了行高**（`EpisodeListRow:190` 与 `TranscriptCard:176`，而后者给 12px 中文配的是 14px 行高）。本屏要一次改齐：卡容器统一、字面量进度量层、字阶+行高成对、三态分道、批量条与回声、默认勾选改读 `analysis.full_threshold`。

---

## 9. 边界、非目标与风险

**非目标（本批明确不做，别再提议）**：结构导航重做（导轨 8 项 / 剧库更名 / 队列 / 工具箱——09-10 计划，不在本批）、品牌图形资产、层次材质重做、视频预览（定案不做）、暂停 / 恢复、亮色主题、方案片段手动调整、快捷键。

**风险与对冲**：

1. **字阶升档撑破现有布局**（导轨 68px 宽 × 11px 标签、列表列宽、Modal 固定宽）。→ 这正是先做参照页的理由：撑破在三屏内暴露，不在 19 屏内暴露。
2. **AntD 基线改 14 的连带面**（Table 行高、Modal 宽度、表单控件）。→ §1.4 列为同批必做项，不是后续。
3. **契约写在原型层，可能掩盖屏级特殊需求**。→ 附录 A 的"本屏特有例外"列是强制项；空着即视为没审这屏。
4. **根因判定可能是错的**。→ §0 的反证条件必须在 8.1 截图定版时显式判定并记录结论。
5. **执行期与另一位工程师同树同分支**（**复测 2026-09-21：索引为空，工作树有 75 个已改未提交 + 13 个未跟踪文件，其中 `desktop/` 下 16 个**——含本规格引用的 `WorkbenchHeader.tsx`、`useAnalysisWorkspace.ts`、`ModePicker.tsx`、`PlanPickList.tsx`）。→ 提交只 add 显式路径，先 `git diff --cached --name-only`；本批不碰 `engine_configs*`、`docs/05-开发路线图.md`、`tests/api/test_analysis.py`。**同树期间不 `git stash`、不 `git add -A`、不在脏树上用 `git checkout/restore` 求"干净"**；基线复算走 §0.2 的 `git archive HEAD` 快照，不在工作树上做。
6. **越出 09-10 计划范围的结构改动共两批**：§6.5 的取材契约（`protocol/schemas/narration.json` + `api/narration.py` 的 `episode_ids` + 契约测试），以及 §10 的引擎异常修复（两条新 RPC `models.clean_residue` / `engines.selftest`，加 `models.download` 的 `force` 入参，再加判据 severity 重划）。其余全是排版、状态与动线表层，不动任何方法签名。→ 各自单独成提交，与视觉改动分开，坏了能只回滚它（§10.6）。

---

## 10. 引擎中心：异常自带修法 + 五 tab 合一

**追加时间与裁决**：2026-09-22。用户看引擎资产页的截图后原话：「引擎设置相关页面需要重点规划和设计一下，引擎失效，我怎么处理，重新下载，还是怎么说，给我看看异常，我没办法修复吗，这个还有意思么 / 将所有UI汇总到一个页面。」范围收窄经选定为**只合并引擎中心 5 个 tab**（设置页 `/settings`、关于页 `/about`、导轨结构都不动），且**异常修复与本批一起做**、不另立规格。

### 10.0 为什么这不是排版问题，而是六条可证的缺陷

这一节只列**实测到位置**的事实，不列观感。每条都在 §10.1–§10.5 有一个对应的改法。

1. **修复路径在接口层就是堵死的**。`api/models.py:107-108`：`models.download` 先查 `registry.find(spec, models_dir)`，命中即 `raise RpcDomainError(_ERR_MODEL_STATE, "… 已安装")`。而 `RowActions.tsx:33-48` 的分支是 `!installed → 下载` / `installed → InstalledActions（体检 `:104` / 打开目录 / 删除 `:118-131`）`——**已安装且异常的行，界面上没有任何一个动作能重下**。用户问的「重新下载，还是怎么说」，答案是：今天说不了，界面和接口两边都不给这条路。
2. **「去修复」是一个穿着修复外衣的跳转按钮**。`ReadinessCard.tsx:104-109` 的按钮体只有 `onGo(item.tab)`（`:106`），而 `onGo` 就是 `EnginesPage.tsx:58` 的 `navigate('/engines/<key>')`。点完到的那一屏正是那张红卡本身，没有任何新信息、没有任何可执行动作。
3. **文件层的判据把"完整可用"的资产判成不可用**。判据同源 `infra/model_manager/registry.py` 的 `verify()`（`:389-443`，八条 checks 在 `:407-433`）；本机实测（`data/models/asr/faster-whisper/`，逐文件量过）：
   - **Small**：`snapshots/536b0662742c02347bc0e980a01041f333bce120/` 里 `_REQUIREMENTS["faster_whisper"]`（`registry.py:328-336`，faster_whisper 在 `:329`）要求的 4 个文件**全在**，`model.bin` 483,546,902 B；`refs/main` 40 B、`trees/<提交号>.json` 也在。**唯一问题是 `blobs/3e3059…997b98bc.incomplete` = 201,173,173 B ≈ 192 MB 的中断残留**——`_verify_residue`（`:490-496`）在 `:494` 判 **fail**。显示为「不完整」，但**残留不参与推理**。而 `assetState.ts:43-46` 的 `canActivate` 只放行 `ready|unverified` → **「选为生效」被禁**，第 1 条又堵死了重下。
   - **Medium**：`snapshots/main/`（目录名字面是 `main`，不是提交号）4 个文件齐全、`model.bin` 1,527,906,378 B、`refs/main` **4 B**、**无 `trees/`**。`_verify_snapshot_revision`（`:463-478`）在 `:472-473` 判 fail「快照目录名不是提交号：main」，`_verify_manifest`（`:481-487`）在 `:487` 出 warn「无 trees 清单」。**这正是那条 docstring（`:466-467`）举的例子本身**：「真机形态：`models--Systran--faster-whisper-medium/snapshots/main` + 4 字节的 `refs/main`——下载没解析到提交号就收工了，这种缓存随时可能少文件」。
   - **诚实边界**：Small 的"其实能用"是强推断（快照已解析到提交号、清单齐、四文件全）；**Medium 能不能加载恰好就是没被验证的那件事**——文件全在不等于 huggingface 按 `refs/main="main"` 能解析出快照。所以 §10.1 只把它从"红"降为"看得见但拦住动作"，**判定留给 §10.3 的能力层自检**，不是留给推断。
   - 两处形态差异都是**落盘方式**（导入 / 下载 / 缓存布局版本）造成的，不是权重缺损。判据把它们和"缺 `model.bin`"混成同一个「不完整」，是第 3 条缺陷的本质。
4. **未验证却发通行证（直接违反 09-10 主张 3）**。`workReadiness.ts:34` 的 `OK_STATES = new Set(['ready', 'unverified'])`（`:53` 使用），`unverified`（从没校验过）算就绪；于是 `ReadinessCard.tsx:64` 显示「全绿 · 可提交任务」。**未验证的东西不能发通行证**——这条在 09-10 已定案，引擎页是它唯一被违反的地方。
5. **界面知道、但不告诉用户的 1.43 GB**。`data/models/models--Systran--faster-whisper-medium/`（**在 `placement` 之外**，即 `models_dir` 根下；注册表按 `base = models_dir / spec.placement` 找，`registry.py:261`（`detect_status`）与 `:402`（`verify`）都是这个根）里有**同一权重的一份完整副本**：`snapshots/08e178d48790749d25932bbc082711ddcfdfbc4f/` 同 4 文件同大小、`refs/main` 40 B、`trees/08e178d4….json` 在、mtime 2026-09-16。**它确定不是引擎实际加载的那一份**：ASR 的 `download_root` 就是 placement 根（`runtime.py:48` 传 `models_dir / "asr" / "faster-whisper"` → `transcriber.py:121`（CPU 回退分支 `:131`）传给 `WhisperModel`），所以这 1.43 GB 是纯磁盘代价，不是"加载错了来源"。`_verify_unique_path`（`:506-523`，它按 `models_dir.rglob` 全根扫，`:514-518`）确实扫到了并出 **warn**（`:521`「另有 N 处同名缓存」）——但 `assetState.ts:49-56` 的 `failureNote` **只过滤 `check.status === 'fail'`**（`:51`），warn 在列表行上被折叠掉，全站只有展开 `VerifyDetail.tsx:52` 才看得到。**来源未查明**（不猜是导入还是旧版本落盘），但它占 1.43 GB 是量出来的。
6. **能力层没有自检**。`api/engine_configs.py:94` 的 `test()` 只打云端端点（LLM/VLM/TTS 的 HTTP 连通）。本地 ASR **从来没有"真跑一段音频"的自检**——所以"引擎失效"这件事今天只能在真实批量任务里撞出来，UI 无从预告。`TtsPreviewButton`（`TtsTab.tsx:185`，另 `:95,:192`）是唯一的例外，它已经是能力层自检，只是没被叫成这个名字。

> **反证条件**：若 §10.1 的 severity 重划落地后，Small 仍因一条残留文件被禁选、或 Medium 仍只能靠人肉推断"应该能用"（没有自检入口）、或「去修复」仍只能跳转，则本批只做到了表层，须回来升级判据层与接口层，而不是继续调文案。

### 10.1 判据按"能不能用"分级，不按"有没有异常现象"

现状八条 checks 一律按"查出了什么"上色，因此 192 MB 残留（不影响加载）和缺 `model.bin`（100% 不能加载）在界面上是同一个红。**改成一条判据：这项失败会不会让引擎在真实任务里跑不起来。**

| 校验项（`registry.py` 位点） | 现判 | 新判 | 依据 |
|---|---|---|---|
| 目录存在（`verify` `:407-414`） | fail | **fail** | 没目录一定跑不起来 |
| 必需文件齐全（`_REQUIREMENTS` `:328-336`、判定 `:415-424`） | fail | **fail** | 缺权重一定跑不起来 |
| 权重非空（`_verify_weights`，调用 `:426`） | fail | **fail** | 同上 |
| 快照提交号（`_verify_snapshot_revision` `:463-478`） | fail（`:472-473`） | **目录名非提交号：有 `trees/` 清单才 fail，无清单降 warn**；`refs/main` 与快照不一致（`:475-476`）**保持 fail** | 目录名叫 `main` 只是没解析到提交号，本体是"无从逐文件对账"；而 refs 与快照对不上是真矛盾，不能降 |
| 下载清单（`_verify_manifest` `:481-487`） | warn（`:487`） | **warn** | 已是 warn，保持 |
| 中断残留（`_verify_residue` `:490-496`） | fail（`:494`） | **warn，但必须上行到行内可见** | 残留占磁盘、不占推理；代价是空间与"上次没下完"这个事实 |
| 唯一路径（`_verify_unique_path` `:506-523`） | warn（`:521`） | **warn，但必须上行到行内可见** | 重复副本不改可用性，改磁盘 |
| 引擎接入（`:432-433`） | 状态降级 | **状态降级（保持）** | 「选为生效不行」在这里是对的，因为工厂确实没接 |

三条契约随之改死：

- **`canActivate`（`assetState.ts:43-46`）只由 fail 决定**：`state` 不再参与，改读 `report.checks` 有无 `status === 'fail'`（后端已有的 `report.ok` 就是这句判据，`:441`）。→ Small 从"不完整且不可选"变成"可选用 + 行内一条 warn 说清 192 MB 残留"；Medium 降 warn 后**可选，但要 §10.3 自检过了才叫就绪**。
- **`failureNote`（`:49-56`）不再过滤 warn**：warn 与 fail 都上行，用 §10.5 的文案纪律区分（fail 给动作、warn 给代价）。第 5 条那个 1.43 GB 从此在列表行上就能看到。
- **五态口径（`assetState.ts:10,31-36`）与 `workReadiness.ts:34,53` 收拢**：`unverified` **不再算就绪**（第 4 条缺陷的根），显示为「未校验」并给「校验」动作；`ready` 才是绿。措辞见 §10.5——「全绿 · 可提交任务」只在全部 `ready` 时出现。

### 10.2 异常态自带修法：三档，一行一个动作

**设计法则（本批新增，全站适用）**：每个异常态必须自带修法，且修法分三档写死——**能自动 / 要确认 / 只能给路**。只有"给路"而没有动作的异常态，视同没做。

| 异常 | 档位 | 动作与代价 | 接口 |
|---|---|---|---|
| 中断残留（`.incomplete`） | **能自动** | 「清理残留」（回收 192 MB，不动已完成的权重） | **新 `models.clean_residue`**：删除范围必须与 `_verify_residue` 的作用域**同一条**（`registry.py:430`：faster-whisper 是 cache 目录、其余是 `base`），返回释放字节数。**否则清完再校验还是红** |
| 已安装但异常，且用户想重来 | **要确认** | 「重新下载」→ 二次确认「将删除现有 N GB 并重下」 | **`models.download` 加 `force`**（解禁 `api/models.py:107-108` 的"已安装"硬拒；`force=False` 行为不变） |
| 重复副本（1.43 GB） | **要确认** | 「删除多余副本」——**只删 `placement` 之外那条路径**，列出全路径与大小再确认 | 复用既有删除路径（`api/models.py:228,235` 的 `shutil.rmtree`），但需一个只作用于 orphan 路径的入口 |
| 缺模型 / 无源（`api/models.py:100-103`） | **只能给路** | 「导入本地模型」（打开 `ImportModelModal`，当前已存在但入口在 `AssetLibrary.tsx:165-167` 顶部、异常行够不着）+ 说清去哪拿 | 已有 |
| 引擎接入未接（储备档） | **只能给路** | 说清**何时**接入（哪个模式用到它），不是「待接入」了事（`AssetLibrary.tsx:90-97` 现文案） | 无 |
| 未校验 | **能自动** | 「校验」单资产（`AssetLibrary.tsx:162` 的批量校验已存在，缺的是行内单发） | 已有 |

**按钮名与动作同权重**：写「重新下载」就必须真的重下，写「清理残留」就必须真的删文件——不允许再出现第 2 条那种名字叫修复、行为是跳转的按钮（`ReadinessCard.tsx:104-109`）。

### 10.3 能力层自检：`engines.selftest`

补第 6 条缺陷。**新 RPC `engines.selftest`**，按域三实现：

- **ASR**：真跑一段随包的 10 秒样例音频，返回「加载成功 / 识别出 N 字 / 耗时」。这是唯一能证明"这个本地权重在这台机器上能用"的判据——文件校验只证明文件在，不证明能推。样例音频随包，不进 `data/`。
- **TTS**：复用 `TtsPreviewButton` 现成的合成路径，只是把它提升为自检结果的一部分（而不是一个孤立的试听按钮）。
- **LLM / VLM**：复用既有 `engine_configs.test()`（`api/engine_configs.py:94`），不新造第二条连通测试。

自检结果进 §10.1 的就绪口径：**校验 = 文件层，自检 = 能力层，两者都过才叫 `ready`**。未自检的显示「未自检」，不发绿（§10.5）。

**契约触点（三处改动各自都要"注册 + schema 条目"成对，因为 `test_contract_sync.py:33-41` 断言 `Router.method_names` 与 `protocol/schemas/*.json` 的 `x-methods` 集合**相等**——只注册不写 schema、或只写 schema 不注册，两边都红）**：

| 改动 | 服务端注册 | schema |
|---|---|---|
| `models.clean_residue` | `api/models.py`（`router.register`，同 `:38` 那条 `models.download` 的写法） | `protocol/schemas/models.json` 的 `x-methods` 新条目 |
| `models.download` 加 `force` | 同上文件的 `download()` | `protocol/schemas/models.json:387-399` 该条目的 `params.properties`（实测整个 `models.json` 里 `additionalProperties` **零命中**，即默认宽容，加字段不破坏既有客户端） |
| `engines.selftest` | **新 `api/engines.py`，并在 `api/__init__.py` 的 `build_router` 里挂上**（契约同步测试就是用 `build_router` 数方法的） | **新 `protocol/schemas/engines.json`**（当前 14 个 schema 文件里没有 `engines.*` 命名空间，最近邻是 `engine_configs.json`） |

客户端三处 `modelsApi` / 新 `enginesApi` 调用点 + 契约测试按 §6.5 同规矩扩到 client 调用集。

### 10.4 五 tab 合一：单页六段

`EnginesPage.tsx:53` 现在是 `216px minmax(0,1fr)` 的左导航 + 右侧 tab 体（`EngineTabNav` 在 `:58` 用 `navigate('/engines/<key>')` 切屏），`tabFromPath`（`:133-135`）的正则决定进哪一屏。**合一 = 五个 tab 变成同一页的六段纵向流**，用户不必在"总览看到红卡 → 点去修复 → 到 ASR 屏 → 滚动找那一行"之间来回跳：

1. **就绪与修复**——今日 `ReadinessCard` 的升级体：每行「现象 + 后果 + 动作」，动作即 §10.2 的那五档。
2. **转写（ASR）**——引擎档选择 + 资产行内联（含五态、校验、自检、修复动作）。
3. **配音（TTS）**。
4. **文本与视觉（LLM / VLM）**——两块凭据独立、留空=继承（09-10 定案，不改）。
5. **提示词**。
6. **环境**——`GpuCard` + 磁盘 / 运行时 / 字体检查。**注意归属**：`features/home/EnvPanel.tsx` 是**工作台右栏**，不搬进来（搬它 = 动 §9 非目标里的工作台）；两处的行数据同源，本段只呈现引擎视角 + 修复入口。

**迁移与兼容**：`/engines/:tab` 五个子路由降级为**同页锚点深链**——`navigate('/engines/asr')` 变成滚到第 2 段。既有三处调用点**一行都不用重写**：`ReadinessCard.tsx:106` 的 `onGo`、`home/EnvPanel.tsx:29,33,36` 的三条 `path: '/engines/<tab>'`（经 `:47` 的 `navigate`）。这是选锚点而不是选"删路由"的直接理由。216 px 左导航取消，段标题进 §1 的 `text.sectionTitle 20/28`；段间分隔走 §2 的 `space.*`，不新增材质。

**这不是全局导航重做**：导轨 6 项、`/settings`、`/about`、`AppLayout` 都不动，09-10 那套导轨 8 项计划仍按"不作废、不在本批"处理。

### 10.5 异常文案纪律（含本机两行的改写前后对照）

三条规矩：**① 现象 + 后果 + 动作与代价**三要素齐，缺任一即未做；**② 按钮名与动作同权重**；**③ 未验证不发通行证**。

| 行 | 现状文案 | 改写后 |
|---|---|---|
| Whisper Small | 「不完整 · 中断残留 192MB」+「选为生效」禁用 | 「可用 · 有一条待办」／「上次下载留有 192 MB 残留，不影响识别，只占磁盘」／按钮「清理残留」 |
| Whisper Medium | 「不完整 · 快照目录名不是提交号：main」+ 禁用 | 「待确认 · 无从对账」／「这份没解析到提交号、也没有下载清单，文件看着齐但**没验证过能不能加载**」／按钮「自检」＋「重新下载」（自检通过才转绿，见 §10.3——**不许写"识别可用"**，那是我们恰好没证的东西） |

「全绿 · 可提交任务」（`ReadinessCard.tsx:64`）改为只在**全部参与就绪判定的资产都是 `ready`** 时出现；只要有一项是 `unverified`/未自检，那句就得写成「N 项未校验——未确认能用」并给出校验入口。

### 10.6 边界与风险

- **不改落盘约定**：`placement`（`registry.py:261,402`）与 ASR 的 `download_root`（`engines/analysis/runtime.py:48` → `transcriber.py:121,131`）、下载落盘根（`downloader.py:189-190`）本批一律不动。改它要动已下载资产的迁移，风险与本批收益不成比例。
- **那 1.43 GB 的来源未查明**，因此本批**只提供删除入口，不实际删 `data/models` 下任何文件**，也不在规格里断言它是谁留下的。执行时先查明再落 UI 文案（若要命名，得有证据）。
- **`models.download` 加 `force` 是真删真下**：默认 `False`，且二次确认必须显示将删除的体量——误点即重下数 GB。
- **`engines.selftest` 会真的加载权重**：ASR 自检在 CPU 上可能十几秒，期间该资产行必须是**进行中态**而不是"看起来卡死"（复用 §4 进度三件套，缺 ETA 显示 `—`）。
- **判据重划会改变已存库里的显示状态**，但不改数据库里存的任何字段——`state` 是每次校验时算出来的，本批只改算法。
- **`engine_configs*` 文件属另一位工程师**（§9 风险 5）：§10.3 的 LLM 分支只**调用**既有 `test()`，不改其实现。

---

## 附录 A · 全站 19 屏清单（覆盖度的可复核证据）

**推导口径（写死，便于将来核对）**：`app/router.tsx` 的 10 条路由屏 + 5 处覆盖层（`grep -rln "<Modal"` 实测：`ProjectsPage:225` 新建、`:105` 重命名、`ImportModelModal`、`CloudConfigModal`、`PromptEditor`）+ 4 个常驻外框（`TitleBar` / `Rail` / `StatusBar` / `ErrorBoundary`）= **19**。
⚠️ **草案里我说过"三个弹窗"，实测是五处 `<Modal>`**（`ProjectsPage` 新建与重命名各一）。表格行数以本推导为准。新增屏不进表 = 计划漏了。

| # | 屏 / 路由 | 原型 | 本屏契约落点 | 四态 | 本屏特有例外 |
|---|---|---|---|---|---|
| 1 | 工作台 `/` | P1 | 左三芯片 + 待办 + 海报网格；右环境 / 提示 | 空 ✓ 有数据 ✓ 无骨架 | `EmptyWorkbench` 持 primary，页标题区按钮须让位 |
| 2 | 项目 `/projects` | P2 | 网格收进度量层；封面 9/16 | **无空态 无失败态** 载入 ✓ | `useProjects.ts:24` 的 `setProjects(await projectApi.list())` **无 try/catch** → 列表请求一失败就是未处理的 rejection，`projects` 永远停在 `null`，于是 `:138` 的 `if (projects === null) return <Card loading />` **永久转圈**（不是吞错，是根本没接）；另一处真吞错在 `ProjectsPage.tsx:35` 的 `.catch(() => undefined)`（补封面失败无声）→ §5 失败态 |
| 3 | 成品库 `/works` | P2 | 按剧分组横向滚动；角标收进 `posterBadge` | 空 ✓ 载入 ✓ **无失败态** | `:13` `MODE_COLORS` 六裸 hex |
| 4 | 成品详情 `/works/:exportId` | P3 | `minmax(300px,420px) + 1fr`；行复用 `listRow` | 空 ✓ 失败 ✓ **无部分成功** | `:168` 内联 `lineHeight 19px` |
| 5 | 分析工作台 `/projects/:id/analysis` | P4 | 左栏按百分比可拖（`useSplit.ts:4` 默认 24、`:22` 带宽 20~40、`WorkbenchPage.tsx:106` `minWidth 250`、`:126` 把手 6px）——**五个数**全部收进 `layout.split` 且不改数值；勾选 + 全选 + **批量条**；右栏三卡；底栏 46（`StepFooter:26` 写死） | 空 ✓ **无骨架 无失败横幅** 部分成功仅计数 | **45 处内联字面量**（§0.2 口径）；`mixins/PageKit` **整屏零引用**；26 处字号仅 2 处配行高；三态撞道；初始空选须改读 `full_threshold`（§6.2） |
| 6 | 出片 `/projects/:id/produce` | P5 | 四段纵向：风格 → 模式 → 方案 → 产出；**顶部常驻「本次取材：已完成分析 X / Y 集」+ 可收窄**（§6.5） | 空 ✓ 失败 ✓ 部分成功 ✓ | `poll.ts:2` 1500ms 轮询**有百分比无 ETA**；取材候选池**服务端硬取全部 done 集、不可改**，卡片只有「取材 N 集」计数、无集号（§6.5 实测） |
| 7 | 引擎·总览 `/engines` | P6 | **§10.4 单页六段**（就绪与修复 / ASR / TTS / LLM·VLM / 提示词 / 环境），5 tab 合一、卡容器一律 `PageSection` | 未就绪 ✓ **下载失败永不显示** | `EnginesPage.tsx:134` 正则漏 `prompts`（**按 HEAD 成立，工作区已被另一位工程师就地修好、未提交**——见附录 B ①）；就绪判据与修复动作见 §10.1–§10.2 |
| 8 | 引擎·分 tab `/engines/:tab` | P6 | **降级为同页锚点深链**（§10.4）：既有 `navigate('/engines/<tab>')` 调用点不改，行为变滚动定位 | 同 7 | 合并后本行与 7 是同一屏，表中分列只为留证据；开工前复查附录 B ① 是否已入库，勿重复修 |
| 9 | 设置 `/settings` | P6 | 单列表单；`labelWidth/controlWidth` 收进 `layout` | 仅"加载中…" | `:268` 内联 `lineHeight 17px` + 自带 shadow 字面量 |
| 10 | 关于 `/about` | P7 | 窄单列 `max-width 720`；开源清单**必须含两条字体** | 静态，无需 | `:30,35` 两处内联 `lineHeight 18px`；`▶` 假图标 |
| 11 | 新建项目弹窗 | O | 统一 `Overlay`：标题 16/24、宽 720、footer 右对齐 | 提交失败需内联 | `ProjectsPage:225` 自带一套 footer |
| 12 | 重命名弹窗 | O | 同 11（同族小表单，禁第三种写法） | — | `ProjectsPage:105` |
| 13 | 导入模型向导 | O | 四步 `Steps`；宽 720；异常态三张 `StateBlock` | 三态已覆盖 | 自带 footer，与另两弹窗各写一套 → 收一 |
| 14 | 云配置弹窗 | O | 同 11 | **保存失败只有 toast，无内联横幅** | `CloudConfigModal` |
| 15 | 提示词编辑器 | O | 同 11；编辑器正文走 `text.body 14/22` + `fontFamilyMono` 可选 | 保存失败同上 | 从 P6 进入，但自身是 O |
| 16 | `TitleBar` | C | 高度与控件尺寸进 `layout`；图标一律 `glyph.*`，角标里的文本走 `text.badge` | 无需 | `:37,69` 是**角标文本**、`:237` 才是图标——三处同读 `fontIcon`，逐位归段见 §1.3 陷阱 2；`:41` `▶` 假图标；`:170` 裸 `boxShadow` |
| 17 | `Rail` | C | **导轨法**：`loop` 组贴顶、`config` 组 `margin-top:auto` 钉底、中间分隔线 | 无需 | `:47` 硬编码 68 而 `railWidth` 零引用；`:86` 字阶当圆角；`:101` 标签 10→11 |
| 18 | `StatusBar` | C | 四段分级：在跑任务 `13/18·500`、环境 `11/14`；§4 三件套落点 | 无需 | `padding '0 14px'`（`:54`）不在阶梯上；`height 26`（`:49`）写死；`:61-77` 四项里没有在跑任务 |
| 19 | `ErrorBoundary` | C | 复用 `StateBlock` 失败态 | 只有整页 reload | 把 `error.message` 原样给用户看 |

---

## 附录 B · 复核到的非设计缺陷（**不进本规格实现范围**，建议单独立案）

这几条是本次全站扫描顺带挖出来的真缺陷。它们**不是排版问题**，混进本批会让"改了什么"变得不可判定，因此单列：

1. `EnginesPage.tsx:134`（HEAD `381f32c5`）的 `/\/engines\/(asr|tts|llm)/` 漏 `prompts` → `EngineTabNav.tsx:30` 的 `TAB_ORDER` 有 `prompts`、`EnginesPage` 已渲染 `<PromptsTab />`，但**永远回落到总览**，「提示词」点不进。
   ⚠️ **开工前必查**：写本规格期间，**同一工作树里另一位工程师已就地把这行改成 `(asr|tts|llm|prompts)`，但尚未提交**（`git status` 显示 `M desktop/src/features/engines/EnginesPage.tsx`，`git blame` 该行为 "Not Committed Yet"）。所以这条缺陷**按 HEAD 成立、按工作区已修**——本批开工前先 `git log -S'llm|prompts'` 确认它是否已入库，已入库即结案，**不得重复修一遍、更不得把自己的改动盖在同一段上**。
   ⚠️ **与 §10.4 的关系**：五 tab 合一后 `tabFromPath` 的职责从"选屏"变成"选锚点"，这行正则可能被整体吸收掉。**结案方式由此变为"确认合一后锚点解析覆盖 `prompts`"**，而不是单独修一行正则——但在工作树那份改动入库前，本节仍按原样成立，不抢先动手。
2. 下载失败态永不渲染：`stores/ui.ts:15` 有 `'failed'`，`useDownloadProgress.ts:9` 只读 `'downloading'`。
3. `StepFooter.tsx:6-55` 与 `PageKit.PageFooter:126-172` 是一对分叉，且 **`PageFooter` 全站零调用点**（详见 §3.3：活的那份在功能目录里、原语是一份死副本）。本批 §3.3 要删的是**分叉**，其承载的批量判据缺陷另案。
4. 「批量分析所选」空选可点、点了静默无事：`canStart`（`useAnalysisWorkspace.ts:95` 算、`:111` 声明进接口）**全站零消费**；按钮用 `disabled={total === 0}`（`WorkbenchHeader.tsx:55`），点下去撞 `:68` 的早退。与设计里的批量条是同一问题的两面。
5. 另有 6 个零引用 token（`theme.ts:76-83` 整个 `layout`、`railWidth`、`colorPrimaryHover`、`colorPrimaryActive`、`colorAccent`、`mixins.hoverBg`）：**处置不是删掉，而是本批让它们变成真有人用的那个真相源**——`hoverBg` 因 §3.2 必须改值，`layout` 与 `railWidth` 因 §2 必须被引用。

**待验证（不进规格，须实测才能定）**：Electron 里 `<audio>` 走 `dramaclip://` 的可行性。**属主边界**：`IndexttsRuntimeSlot.tsx` 写作本规格时是另一位工程师的未提交改动，现已随 `e6d57fe` 入库——它仍不属任何清扫范围，动它之前先与属主对账。
