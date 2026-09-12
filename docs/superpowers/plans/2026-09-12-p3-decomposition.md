# P-3 全站重排 · 拆分、边界与依赖顺序

**日期**：2026-09-12 · **分支**：`feat/correctness-wiring` · **上游规格**：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md`
**视觉真相源**：`docs/desktop/04-设计系统方案.md`（DSS v1）
**本文件只决定"切几刀、刀口在哪、谁等谁"**；第一刀的实施细节在 `docs/superpowers/plans/2026-09-12-p3-1-nav-shell-and-workbench.md`。

---

## 0. 结论先行

规格 §6 把 P-3 写成一行（「导轨 8 项分两组、剧空间四阶段合并两页、成品库分组与逐片封面、工具箱、关于、工作台改造、旧路由与死组件清扫」），出口是「全站切到新 IA，§9 验收全过」。这一行覆盖 **6 个互不共享后端子系统的子系统**，其中 4 个各自要新增服务方法、1 个被 P-2 全量阻塞、1 个被外部资产阻塞。按 `superpowers:writing-plans` 的 Scope Check，它必须拆。

**拆成 6 份，顺序如下：**

| 切片 | 名称 | 后端依赖 | 可否与 P-2 并行 |
|---|---|---|---|
| **P-3.1** | 导航壳与工作台开工页 | **零**（不动 `service/`，只同步 `protocol/ts` 的两个既有类型） | **可，立刻开工** |
| **P-3.4** | 工具箱六件 | 6 个新 `tools.*` 薄封装（自有，非 P-2） | 可（只与 P-3.1 抢 `navItems.ts` 一行） |
| **P-3.6** | 关于覆盖层与更新检查器 | 主进程目录打开 + 更新检查器（自有，非 P-2）；**被两张二维码资产阻塞** | 可（同上） |
| **P-3.3** | 成品库质检台 | 4 个新 `export.*` + 自检度量四项（自有）；仅"角度名/跳回方案"依赖 P-2 的 `get_plan` | 后端可并行，UI 落在 P-2 之后 |
| **P-3.5** | 图片生成与封面生成器 | 新引一类图像模型 + AI 标识（自有）；**被 §8.5 的云端/本地取舍未决阻塞** | 依赖 P-3.3、P-3.4 |
| **P-3.2** | 剧库与剧空间四阶段 | **P-2 全量** | **不可，必须等 P-2 交付** |

**依赖顺序**：`P-3.1 → { P-3.4, P-3.6 } → P-2 交付 → P-3.2 → P-3.3 → P-3.5`。
其中 `P-3.3` 的服务侧（抽帧封面、自检四项、`export.delete/rename`）不需要等 P-2，可以在 P-2 实施期间并行开发，只有它的两个控件（角度名、跳回方案）要等。

**§2.1 的 8 项导轨不是一次落地的**：P-3.1 落 5 项（今天已存在的目的地），P-3.4 加「工具箱」，P-3.6 加「关于」，「队列」属 **P-2.5**（§6 P-2.5 行明写「只做三件事：K 条角度出片 + 队列页 + 成本预估」），「剧库」的改名随 P-3.2。**理由见 §2 的"导轨项不得指向不存在的页面"。**

---

## 1. 边界判据（每一条刀口都必须同时过这三关）

1. **能独立验收**：切片的出口判据不引用别的切片未交付的能力。做不到就说明刀口错了。
2. **后端依赖同质**：切片内所有页面要么都不需要新服务方法，要么都需要同一批。混着的切片会在实施中途卡死。
3. **界面不得说谎**：**导轨项、按钮、徽章、统计数字，一律不得指向或描述尚不存在的东西**（§9.5「无任何界面文案描述未实装的能力」）。这条判据直接否决了"先把 8 项导轨铺满、页面后补"的做法——一个点了跳到空壳页的导轨项就是假文案。
   推论：**能力可以缺席，缺席必须表现为"没有这个控件"，不能表现为"有个不能用的控件"。** 各切片按此原则处理自己被阻塞的部分（见 §3 每片的"本片不做"）。

---

## 2. 依赖实测：P-3 每一项内容 × 需要的能力 × 今天的真实状态

下表全部经代码核实，不是从规格抄的。✓ = 今天可用；**缺** = 不存在。

| P-3 内容 | 规格出处 | 需要的能力 | 今天的状态（证据） | P-2 阻塞 |
|---|---|---|---|---|
| 导轨分组 + `border/subtle` 分隔线 | §2.1 | 无 | 纯前端。`desktop/src/components/layout/AppLayout.tsx:15-21` 是内联 `NAV_ITEMS` 数组，无分组概念 | 否 |
| 导轨高亮规则 | §2.1 | 无 | **今天就是坏的**：`AppLayout.tsx:60` 用 `location.pathname === item.path` 精确等值比较，所以 `/engines/llm`（由 `EnvPanel.tsx:37` 的「去配置」跳入）与 `/projects/:id/analysis` 全部失高亮。§2.1 只点了后者，前者是本轮新发现 | 否 |
| 「队列」导轨项 | §2.1 序 3 | 队列页 | 属 **P-2.5**，不属 P-3（§6 P-2.5 行）。后端反而已就绪：`jobs.list/get/cancel` + `export.retry` 在 `protocol/ts/index.ts:341-343,338` 已登记、`service/dramaclip/api/jobs.py:21-24` 已注册，但 **`desktop/src` 全文 grep `jobs.` 零命中——P-1 交付的四个方法今天没有任何消费者** | 否（属别批次） |
| 「工具箱」导轨项 | §2.1 序 5 | 工具箱页 | 需 6 个新 `tools.*`；引擎全在手（§4.7 表逐行标 ✓）。`desktop/src/features/home/EnvPanel.tsx:105-153` 今天有个叫「工具箱」的面板，**里面一个工具都没有**，三项全是导轨已有目的地的重复跳转（`:118` 把 `key` 拼成 `/${key}`） | 否 |
| 「关于」导轨项 | §2.1 序 8 | 关于覆盖层 | `system.health` ✓、`appVersion` ✓、`revealInFolder` ✓——但 `desktop/main/ipc.ts:31` 用的是 `shell.showItemInFolder`，**对目录的语义是"打开父目录并选中它"，不是"打开它"**，§5 行 46 要求的正是后者。**两张二维码资产不存在**：`resources/` 下只有 `dramaclip-service/`，没有 `about/`（§4.8 按 ADR-009 要求放这里，且明写「不做远程拉取」）。更新检查器零后端（§11 行 14） | 否（被资产+更新器阻塞） |
| `/projects` → `/dramas` 改名 | §2.2 | §4.2 剧库页 | `project.list` 无阶段聚合（`service/dramaclip/api/project.py:51-52` 直接返回 `list_all`）。§4.2 的剧卡四阶段状态条、聚合行、卡片点击直跳当前阶段、首启三步空态全部要它 | **是** |
| `/projects/:id/*` → `/drama/:id/*` | §2.2 | 剧空间页 | `narration.plan_variants`/`get_plan`/`export.submit` 均不在 `protocol/ts/index.ts:311-358` 的 `METHOD_NAMES` 里 | **是** |
| `TimelineEditor.tsx` 删除 | §2.2 | — | **已完成**：全库 grep `TimelineEditor\|replace_timeline` 零命中 | 关闭 |
| `/models` → `/engines` 更名 | §2.2 | — | **已完成**（P-1）：`desktop/src/app/router.tsx:20-23,35-38`，`LegacyModelTabRedirect` 是保参重定向的既有先例 | 关闭 |
| 工作台三统计芯片 | §4.1 | 剧数 / 在跑+ETA / 成品数+周增 | `project.dashboard_summary` ✓、`jobs.list` ✓（含 `progress`/`created_at`/`updated_at` 毫秒，`service/dramaclip/infra/jobs.py:26-27,82-83`，ETA 可外推）、`export.list_works` ✓（含 `completed_at`，周增可算） | 否 |
| 工作台待办·分析失败集 | §4.1 | 失败集号 + 原因 | `analysis.results` 返回每集 `status` 但**不返回 `error`**（`service/dramaclip/api/analysis.py:301-310` 构造的 entry 里没有该键），而 `protocol/ts/index.ts:124` 却声明了 `error?: string`——**协议声明了服务从不填的字段**。且 `episodes`/`episode_analysis` 两张表都没有 error 列（实测 `pragma table_info`）。逐剧调 `analysis.results` 是 N+1 且会拖回全部 ASR 段。改走 `jobs.list`：`type='analysis'` 的失败行带 `error` 且 `ref_id=project_id`（`api/analysis.py:134`），一次 RPC 拿全 | 否（换数据源即可） |
| 工作台待办·已分析未规划 | §4.1 | 阶段聚合 | `project.list` 无 stage | **是** |
| 工作台待办·队列失败任务 | §4.1 | 队列页作落点 | `jobs.list` ✓，但 **`ref_id` 语义异构**：`analysis`/`prescreen`/`narration`/`produce` 的 `ref_id` 是 project_id（`api/analysis.py:65,134`、`api/narration.py:74,327`），`export` 的是 **export_id**（`api/export.py:79`），`model_download` 的是 **model_id**（`api/models.py:65`），`semantic` 的是 **episode_id**（`api/analysis.py:223`）。没有 `/queue` 页就没有落点可跳 | 否（被 P-2.5 阻塞） |
| 工作台待办·有素材无成品 | §4.1 | project.list + list_works | 两者都 ✓，客户端可算（`project.episode_count` 对比按 `project_id` 分组的成片数） | 否 |
| 工作台「最近成品 6 条钩帧缩略」 | §4.1 | 逐片封面 | `list_works` 的 SELECT 里没有 `cover_path`（`service/dramaclip/infra/storage/repos/exports.py:142-158`），今天只有项目级封面（`WorksPage.tsx:53` 把 `projects.cover_path` 按 project_id 映射给同剧所有片——正是 §4.5 抱怨的"9 条同剧片共用一张封面"） | 否（属 P-3.3） |
| 成品库·按剧分组 | §4.5 | — | `list_works` 已返回 `project_id` + `project_name` ✓，**纯前端即可分组** | 否 |
| 成品库·逐片封面 | §4.5 | `export.set_cover` + 导出后抽帧 | **缺**。`infra/ffmpeg/cover.py` 今天只服务项目与集（§5 行 28 已注明） | 否（P-3 自有） |
| 成品库·自检徽章四项 | §4.5 | 度量搬到服务侧 | **缺**。§4.5 的诚实原则（「四项度量落地前，徽章显示「—」，不显示绿勾」）意味着这一项要么真做要么不渲染 | 否（P-3 自有） |
| 成品库·角度名 / 跳回方案 | §4.5 | `plan.angle`、`narration.get_plan` | **缺** | **是** |
| 成品库·删除 / 重命名 | §4.5 | `export.delete`、`export.rename` | **缺**。且 §3.4 要求删除移入 `<data>/.trash/<日期>/`——实测 `data/` 下今天只有 `backups cache covers data.db logs models outputs`，无 `.trash`，服务侧零引用 | 否（P-3 自有） |
| 工具箱六件 | §4.7 | `tools.transcribe`/`build_subtitle`/`synthesize_speech`/`extract_frame`/`probe_batch`/`analyze_reference` | 六个方法全无；六个引擎全在（§4.7 表逐行 ✓）。§6 判定「全是既有引擎的薄封装，不含任何新算法」「建议作为独立小批次随时插入」 | 否 |
| 工具箱·图片生成 | §4.7 | `tools.generate_image` + 图像模型凭据与下载 | **缺**，且 §11 行 8 实测 `engine_configs[image]` 域**已声明但完全无消费者**。§8.5 的取舍未决（本机 Quadro M4000 8GB 跑不动 SDXL/Flux，默认应走云端） | 否（被决策阻塞） |
| 关于四块 + 本地数据「打开」 | §4.8 | 见上 | 见上 | 否 |
| 剧空间四阶段全部 | §2.3 §4.3 | §5 行 7-22 | 大部分**缺** | **是** |
| 设置页「生产线默认值」分区 | §4.6 | K 默认 / 时长档 / 风格默认 | `narration.style_id` ✓、`strategy.min/max_duration_s` ✓ 都在 `service/dramaclip/infra/config.py:34-36`；**K 默认没有对应设置键**——K 是 `plan_variants` 的入参（§5 行 15-17），所以「K 默认」这一格随 P-2 一起落 | **部分** |
| 设置页「字幕 / 存储 / 代理」分区 | §2.1 序 7、§4.6 | 见 §5 的规格问题清单 | **字幕键存在但设置页没有该分区**：`config.py:27-28` 有 `subtitle.default_preset`/`subtitle.smart_match`，而 `desktop/src/features/settings/sections.ts:131-138` 的 `buildSections()` 只返回 出片/分析/下载/硬件 四区。**存储、代理两区连设置键都不存在** | 否（但属规格缺口） |

**从这张表长出来的三条结论：**

1. **P-3 对 P-2 的依赖不是均匀的，而是集中在一片**：只有「剧库 §4.2」与「剧空间 §4.3」两块是 P-2 全阻塞，加上成品库的两个控件（角度名、跳回方案）。规格 §6 那句「P-3 依赖 P-1、P-2」在字面上成立、在排期上误导性极强——它会让 6 个切片里 4 个白等。
2. **P-1 已经交付但完全没被消费**：`jobs.list/get/cancel`、`export.retry`、`project.update_settings` 五个方法在桌面端零调用。P-3.1 是第一个消费者，这也是它"零后端却能交付真价值"的原因。
3. **`analysis.prescreen` 同样零消费**（`desktop/src` 全文只在 `sections.ts:37` 出现为设置键名）。§5 行 10 的括注「今天 prescreen 客户端零调用」经本轮复核**仍然成立**，归 P-3.2。

---

## 3. 六份计划

### P-3.1 导航壳与工作台开工页

**内容**：导轨清单化（两组 + `border/subtle` 分隔线 + 前缀高亮）、路由表清单化与三方一致性守卫、工作台按 §4.1 重写（三芯片 / 可执行待办 / 空态引导 / 最近成品 / 继续上次）、假文案清零（含三处"关键词降级"谎言）、home 域死组件清扫。

**为什么这条边界**：这三件事共享同一个 seam——**"IA 的真相源从 JSX 内联数组变成可测数据"**。导轨清单、路由清单、工作台的数据装载都是同一个改动的三面：把"页面在哪、叫什么、有没有数据"从渲染代码里抽出来。分开做会让 `AppLayout.tsx` 被 5 个切片各改一次。

**后端依赖**：**零**。不动 `service/` 一行。唯一的跨包改动是把 `protocol/schemas/jobs.json` 里**已经定义**的 `JobInfo` 同步进 `protocol/ts/index.ts`（该文件 `:4` 自己写着「任何变更先改 schema 再同步本文件」，而 P-1 只加了 `METHOD_NAMES` 没加类型）——**不新增任何 `METHOD_NAMES` 条目**。

**本片不做（缺席而非假控件）**：
- 「队列」「工具箱」「关于」三个导轨项——目的地不存在（判据 3）。
- `/projects`→`/dramas` 路由改名——它与 §4.2 的剧库页是同一个原子改动，且改名会波及 `desktop/src/features/analysis/WorkbenchHeader.tsx:30`、`WorkbenchPage.tsx:63,66`（**该目录属 OCR 字幕通道的另一位工程师**，本片不碰）。
- 待办的「已分析未规划」（P-2）与「队列失败任务」（P-2.5）两个来源。
- 最近成品的「钩帧缩略」（P-3.3）——本片保留今天的文字行形态，不拿项目封面冒充逐片封面。

**独立出口**：
1. 导轨 5 项分两组、中间一条 `border/subtle` 分隔线，进 `/engines/:tab` 与 `/projects/:id/*` 时所属项保持高亮（自动测试）。
2. 导轨 ↔ 路由清单 ↔ `router.tsx` 的 `path` 字面量三方一致（自动测试，防"导轨项指向不存在的路由"这一类缺陷）。
3. 全 `src/` 不再出现被禁词（自动测试，源码扫描）。
4. 工作台三芯片与四类待办全部有真数据源，每条待办的动作要么跳到一个已注册路由、要么触发一个已存在的桥接方法（自动测试 + 手工协议）。
5. `jobs.list` 首次被消费（自动测试 + 手工协议）。
6. 无剧时主区整块替换为新增项目引导（自动测试）。
7. `npm run typecheck` / `npm run lint` / `npx vitest run` 全绿。

---

### P-3.2 剧库与剧空间四阶段（**P-2 全阻塞**）

**内容**：`/projects`→`/dramas` 与 `/projects/:id/{analysis,produce}`→`/drama/:id/{stage}` 两组改名与一次性重定向；§4.2 剧库（剧卡同构五要素、四阶段微缩状态条、搜索/筛选/排序、聚合行、首启三步空态、批量新增项目、追加素材）；§2.3+§4.3 剧空间（两页合一、阶段条四态只读可跳、左栏素材列表仅①②出现、素材行三态、转写档位三选与金色覆盖度告警、行内编辑提交规则修正、方案卡只读四要素与重叠率、包装区与成本预估、提交后跳队列）；§3.1 阶段条四态；§4.6 设置页「生产线默认值」与「字幕」分区；`modeMeta.ts` 第三面镜子收口（P-1.5 计划 Task 4 实测修正登记的「P-3 已知接受项」）。

**为什么这条边界**：它是唯一一片**页面之间必须同时改**的区域。§2.2 自己给出了理由：「今天两页各持不同 store、分析页勾选的集传不到出片页，是批量断裂的根因」——所以合并两页与改路由是同一个原子动作，拆开做会留下一个"改了一半的 store"中间态。而剧库的卡片点击直跳当前阶段（§5 行 3）又必须与剧空间的阶段条同一套阶段定义，否则两处会各算一遍"这部剧走到哪了"。

**后端依赖**：P-2 全量（`narration.plan_variants`/`get_plan`/`export.submit`、`project.batch_create`、`project.list` 阶段聚合、`analysis.results` 的 `planned_coverage`、重叠度量、`project.scan_episodes` 的 `issues`）。P-1 的 `project.update_settings` 已就绪可用。
**另需**：§10 的 `semantic/subtitle_probe` 属批次 2，不在 P-2 也不在 P-3——所以 §4.3 ④ 的原字幕三档必须按 §10.4 渲染「未检测到，使用默认位置」，**这是 §3.3 静默禁止清单第 5 行的落点，不得因为探测器没来就把这一档藏掉**。

**本片不做**：`narration.replace_timeline` 相关的任何编辑能力（§2.3 硬约束「阶段条内不放任何编辑器」、§7 非目标）。

**独立出口**：两页合一且旧路由一跳即达新址；阶段条四态可点跳、只读；§3.3 五类静默事件中四类有明确落点（第五类按 §10.4 回退并显式标注）；批量建项目一次可选多目录；§9.3 逐条可指认。

---

### P-3.3 成品库质检台

**内容**：§4.5 按剧分组 + 组内网格、逐片钩帧封面、自检结论徽章四项、多选批量动作（打开目录 / 复制到指定目录 / 删除进回收站）、单片重命名与显示完整 `output_path`、筛选（含"只看自检通过"）；§3.4 危险操作统一规则的全部四条（量化确认「删除 N 条 · 共 X GB」、`<data>/.trash/<日期>/`、清空回收二次量化确认、`danger` 样式且同屏不出现第二个 primary/danger）。

**为什么这条边界**：它是 P-3 里唯一一片**"页面形态由新度量决定"**的区域——徽章四项不落地，§4.5 的诚实原则就要求徽章显示「—」，那这个页面就没有筛据，§9.4「30 秒内从 60 条里筛出可发子集」直接不成立。所以度量与页面必须同批。反过来，度量与导轨/剧空间毫无耦合，可以完全独立开发。

**后端依赖**：自有（`export.set_cover`、导出后抽帧、自检四项度量、`export.delete`、`export.rename`、`export.list_works` 增 `cover_path`/`selfcheck` 字段）。**不依赖 P-2**，除两个控件：角度名与「跳回方案」（要 `narration.get_plan`）——按判据 3，这两个控件在 P-2 交付前**不渲染**。
**服务侧可与 P-2 并行开发**（不同文件：`api/export.py`、`infra/storage/repos/exports.py`、`engines/exporter/` vs P-2 的 `api/narration.py`、`engines/narration/`）。

**本片顺带接手的一个已知缺陷**：`service/dramaclip/infra/storage/repos/projects.py:158` 的 `export_count` 是 `SELECT COUNT(*) FROM export_jobs`，**不带状态过滤**——失败与 pending 的导出记录都会被算成"成品"。P-3.1 的工作台芯片绕开它（改从 `export.list_works` 计数，那条查询带 `status='completed' AND output_path IS NOT NULL`，`repos/exports.py:145`），但 `dashboard_summary` 这个方法本身仍返回一个含义与名字不符的数。修它要改 `DashboardSummary` 的形状 = 动 `protocol/`，与 P-2 撞车，所以**登记在此，由本片（成品数的归属方）修**。

**独立出口**：§9.4 可复现（60 条片、计时、只用徽章与角度标签筛）；四项度量任一未落地时该片徽章显示「—」而非绿勾；删除进 `<data>/.trash/<日期>/` 且从「关于 → 本地数据」可达；每条片能显示完整 `output_path`。

---

### P-3.4 工具箱六件

**内容**：§4.7 的六个复用现成引擎的工具（转写取稿 / 文案转字幕 / 配音合成 / 抽帧取图 / 媒体体检 / 对标拆解）+ 三条隔离规矩的强制（不建项目不写 `projects`/`episodes` 表、不共用主流程 job 语义不进 `/queue`、产物只落 `data/toolbox/<日期>/`）+ 导轨第 5 项 + 删除 `EnvPanel.tsx:105-153` 那个假「工具箱」面板的最后一处残留引用。

**为什么这条边界**：§6 自己就把它们单列了——「工具箱的 7 个里 6 个最便宜：全是既有引擎的薄封装，不含任何新算法……建议作为独立小批次随时插入，不必排队」。它与其余五片唯一共享的文件是 `navItems.ts` 的一行。

**后端依赖**：6 个新 `tools.*` 方法，每个是对既有引擎的一层参数校验 + 落盘。**不依赖 P-2**。

**本片不做**：图片生成（§4.7 的第七件，见 P-3.5）。按判据 3，工具箱页在 P-3.5 之前只有六张卡，**不留第七个空位**。

**独立出口**：六个工具各出一次真产物到 `data/toolbox/<日期>/`；跑完一次后 `projects`/`episodes` 两表行数不变（可自动断言）；`/queue` 里不出现工具箱任务；清空该目录不影响 `data/outputs/`。

---

### P-3.5 图片生成与封面生成器

**内容**：§4.7 的第七件（文生图 + 图生图）、图像模型凭据与下载、`engine_configs[image]` 域从"已声明无消费者"变成真被消费（§11 行 8）、成品库与剧空间④ 的封面生成器（真实钩子帧打底 + 可选图生图重绘，§5 行 44）、**AI 标识三条硬约束**（默认可见角标 + 文件元数据隐式标识；关闭显式角标须二次确认并留痕，写明"平台可能拒发或自行二次加标"；封面经图生图重绘同样适用）。

**为什么单独成片**：三个理由，任一条都足以把它从 P-3.4 切出来。
1. 它是全清单里**唯一要新引一类模型**的能力（§6「图像」层、§8.5「唯一要新增的一类重模型」），带自己的下载/凭据/连通自检链路。
2. **它有一个未决的产品取舍**：§8.5 明写本机 Quadro M4000 8GB（Pascal）跑 SDXL/Flux 不现实，默认应走云端 OpenAI Images 兼容端点，且「封面经图生图重绘后须带 AI 显式标识，会影响封面观感与点击，此取舍需你确认接受」。**未决的取舍不能进实施计划**。
3. 它的下游消费者横跨两片（成品库封面 = P-3.3、剧空间④ 封面生成器 = P-3.2），所以它必须排在两者之后。

**合规约束（不可协商）**：《人工智能生成合成内容标识办法》2025-09-01 施行，第四条要求生成的图片带**显式标识**，第六条要求传播平台核验元数据，第九条的"用户主动要求不带标识"例外**以服务提供者记录告知为前提**。所以"关掉角标"不是一个前端 confirm 就完事的交互，它必须落一条可查的本地留痕。

**独立出口**：文生图与图生图各出一张带可见角标且元数据含隐式标识的 PNG；关闭角标走二次确认并在本地留下可查记录；封面生成器默认路径产出的封面**不带** AI 标识（因为它是真实帧），一旦经图生图重绘则**带**标识——两种封面在界面上可区分。

---

### P-3.6 关于覆盖层与更新检查器

**内容**：§4.8 的居中小弹窗（约 640×460，Esc 或点遮罩关闭，**永不自动弹出**）、左栏 190px 品牌与两张码、右栏四块（版本 / 本地数据 / 开源许可 / 授权与合规声明）、底部版权；主进程 `shell:reveal` 支持"打开目录"语义；更新检查器（§11 行 14，手动查一次并回显，更新提示走状态栏 + 安装/稍后，不弹窗）；导轨第 8 项。

**为什么单独成片**：它是六片里唯一**改主进程**的（`desktop/main/ipc.ts:29-34` 今天只有 `shell.showItemInFolder`，对目录的语义是"打开父目录并选中它"，而 §5 行 46 要的是"打开这个目录"）。主进程改动与渲染层重排混在一个切片里，会让回滚粒度变成"整个 IA"。

**硬阻塞（非代码）**：两张二维码 PNG 必须由所有者提供并放进 `resources/about/`。§4.8 明写「不做远程拉取（本地优先、无云账号），代价是换码必须发版」——所以没有这两个文件，品牌块就没有内容。**资产到位前本片不得开工**，否则只能渲染占位图，那是假文案。

**授权与合规声明的措辞红线**：§4.8 表格最后一行要求写明「素材授权责任由使用者承担；本软件不代为取得或证明授权，**不提供绕过平台原创性检测的能力**；媒体处理全部在本机完成、素材不上传」。配合项目合规红线：**「消重」「抗比对」永远不得作为用户可见的卖点文案出现**（185 万判例）。本轮实测 `desktop/src` 全文这两个词零命中，P-3.1 把这条钉成自动测试，此后任何切片再引入都会当场红。

**独立出口**：从导轨第 8 项与 `/about` 深链都能打开；四块信息全部有真数据（版本号来自 `appVersion()` 与 `system.health`，四个目录来自实际数据根）；四个「打开」各自打开正确的目录；首启与更新后都不弹；`检查更新` 手动点一次有明确回显（成功/失败/已是最新三态）。

---

## 4. 第一刀为什么是 P-3.1（含被否决的备选）

**先说一个否决掉的天真做法**：「先把 8 项导轨铺满，页面后补」。它直接违反判据 3——8 项里 3 项的目的地今天不存在（`/queue` 属 P-2.5、`/tools` 属 P-3.4、`/about` 被资产阻塞），铺满就是造 3 个点了跳空壳的按钮。§9.5 是验收项，不是建议。

**四个被否决的备选，以及否决理由：**

| 备选 | 否决理由 |
|---|---|
| **只做导航壳，不配页面** | 它能交付的诚实内容太薄：不改名的话，导轨 5 项的标签与今天完全一样，用户看到的变化只有一条分隔线。而且"清单化"这个抽象没有真实消费者来校验形状，等于凭空设计一个接口——正是 P-1.5 计划里反复吃亏的那类事（该计划 Task 8 实测修正：「本计划把 loudnorm 的两个 JSON 键名编造了出来，而测试抄的正是这份编造」）。抽象必须由第一个真实使用者当场校准。 |
| **剧库 `/dramas` 先行** | P-2 全阻塞。§4.2 的五项新增（四阶段微缩状态条、聚合行、卡片点击直跳当前阶段、首启三步空态的完成度、批量新增）里有四项要 `project.list` 阶段聚合或 `project.batch_create`。只改名不改内容 = 标签与页面说谎。 |
| **关于 `/about` 先行** | 被两张二维码 PNG 阻塞（`resources/about/` 不存在），且更新检查器零后端。它是"最小可见新功能"的诱人候选，但它的品牌块没有资产就是空的，而 §4.8 明确禁止远程拉取。 |
| **工具箱 `/tools` 先行** | 六个 `tools.*` 虽是薄封装，但仍是 6 个新服务方法 + 6 个 schema + 6 个 UI，体量大于 P-3.1 而价值面窄（侧门工具，不在主循环上）。它排在 P-3.1 之后可以并行，但不该抢第一刀。 |
| **成品库 `/works` 先行** | 按剧分组确实纯前端可做，但 §4.5 的其余部分（逐片封面、自检徽章、批量删除、重命名）全要新后端，而**没有徽章的成品库不满足 §9.4**（「自检徽章与角度标签是筛据，不靠逐条播放」）。只做分组等于把一个 400 行的页面重排一次，然后 P-3.3 再重排一次。 |

**选 P-3.1 的四条正面理由：**

1. **它是唯一一条零后端、零 P-2、零资产阻塞的路径。** 全片不动 `service/` 一行，因此在 P-2 实施期间可以真正并行，而不是"名义并行、实际等接口"。
2. **它是其余五片的共同前置，而且便宜。** 每片都要往导轨加一项、往路由表加一条。今天这两处都是内联在 `AppLayout.tsx:15-21` 与 `router.tsx:17-27` 的 JSX 里——五个切片各改一次同样两个文件，必然互相冲突，也必然与 P-2 撞在 `router.tsx` 上。先做一次清单化，后面每片就退化成"追加一行数据"，这是可自动合并的改动。
3. **它承载 P-3 里风险最高、最难回退的决定：路由表。** §2.2 自己统计过 `/models` 那次更名有「实测触点 12 处 / 6 文件」，还特别标注了两处会静默失效的（`EnginesPage.tsx:99` 的 pathname 正则、`EnvPanel.tsx:107` 被拼成 URL 的 `key`）。趁别的切片还没开工把路由纪律与守卫测试立起来，此后所有人写的是新路径。
4. **它交付的真价值不是"结构"，而是三件今天就是错的事**：① 导轨高亮在 `/engines/:tab` 与 `/projects/:id/*` 全线失效（`AppLayout.tsx:60`），用户进去就不知道自己在哪；② 界面上有三处承诺"P-1.5 已经取消的降级"（`useTodos.ts:32`、`LlmTab.tsx:13`、`OverviewTab.tsx:74` 都说未配 LLM 会"关键词降级"，而 P-1.5 之后**解说文案无模板兜底、未配置即抛错**，七个解说模式的每条方案都会失败）——这是会让操盘手白等一晚上的假话；③ P-1 交付的 `jobs.list` 零消费者，任务在飞而界面无感。

**关于「导轨/路由壳是否真的第一」的直接回答**：**壳本身不值第一刀，壳 + 工作台才值。** 工作台是今天唯一一个"既是导轨项、又几乎全部数据源已就绪、又集中了最多假文案"的页面，它同时充当导航清单的第一个真实消费者（校验抽象形状）与假文案清零的主战场（§9.5）。把两者绑在一起，第一刀就既有结构又有可见产出。

---

## 5. 死组件与死引用清单（§6 的「清扫」到底指什么）

全部经 grep 核实。`引用数` = 除自身文件外提到该符号的文件数。

| 对象 | 位置 | 证据 | 处置 | 归属 |
|---|---|---|---|---|
| `SectionTitle` | `desktop/src/features/home/SectionTitle.tsx:5` | 引用数 1（仅 `RecentProjects.tsx:6,19`）。与 `StartCards.tsx:160 PanelTitle`、`RecentWorks.tsx:74 SectionHeader` 是**同一份渐变竖条标题的三份拷贝**——DSS §6.3 早已点名「`SectionTitle` 三种实现 → 收敛为 PageSection 内置」 | 删除，统一走 `components/layout/PageKit.tsx:73 PageSection` | **P-3.1** |
| `PanelTitle` | `desktop/src/features/home/StartCards.tsx:160` | 同上，第二份拷贝 | 随 `StartCards` 一起删 | **P-3.1** |
| `SectionHeader` | `desktop/src/features/home/RecentWorks.tsx:74` | 同上，第三份拷贝 | 删除，改用 `PageSection` | **P-3.1** |
| `StartCards` | `desktop/src/features/home/StartCards.tsx` | 引用数 1（`HomePage.tsx:10,59`）。三张卡里「继续创作」跳 `/projects`、「引擎中心」跳 `/engines`，**两项都是导轨已有目的地的重复**；只有「新建项目」是真动作，而它要的 `createThroughFolder`（`:88-103`）应上提复用 | 删除文件，`createThroughFolder` 抽成 `features/home/createDrama.ts`，新建项目变成 PageHeader 的唯一 primary（DSS §3.1「每屏 primary 至多 1 个」） | **P-3.1** |
| `ToolboxPanel` | `desktop/src/features/home/EnvPanel.tsx:105-153` | 名为「工具箱」而**零个工具**：`TOOLS` 三项的 `key` 是 `engines`/`settings`/`projects`，`:118` 把 key 拼成 `/${key}` 后跳到三个导轨已有的页面。§2.2 已把 `:107` 标注为"被拼成 URL 的 key"这一类隐患 | 删除。§4.1 右栏的「工具箱」槽位由 P-3.4 用真工具填 | **P-3.1** |
| `RecentProjects` | `desktop/src/features/home/RecentProjects.tsx` | 引用数 1（`HomePage.tsx:8,65`）。§4.1 的主区结构是「今日待办 + 3 芯片 + 最近成品 + 继续上次」，**没有"最近项目"这一格**；它的功能被「继续上次」与剧库页覆盖 | 删除 | **P-3.1** |
| `restartService` | `desktop/src/services/client.ts:34-36` | 渲染层零调用（IPC 通道 `main/ipc.ts:35-38` 与 `preload.ts` 都在）。**是死导出，不是死功能** | 不删——P-3.1 给它接上唯一合理的消费者：服务不可用待办的「重启服务」动作（§4.1「待办必须是可执行动作，不是通知」） | **P-3.1** |
| 三份手写页头 | `HomePage.tsx:97-138`、`ProjectsPage.tsx:78-91`、`ProductionPage.tsx:86-102` | `PageKit.tsx:23 PageHeader` 已存在且被 `EnginesPage`/`SettingsPage`/`WorksPage` 使用；这三处绕过它各写一套 `<header>`，是 §9.1「页头同构」失败的直接原因 | `HomePage` 的那份在 P-3.1 收；`ProjectsPage`/`ProductionPage` 的两份随 P-3.2 页面重写一并收 | P-3.1 / P-3.2 |
| `StepsNav` | `desktop/src/features/analysis/StepsNav.tsx` | 四步（素材导入&AI 分析 / 选择出片模式 / AI 编排&渲染 / 成片查看导出）与 §2.3 的四阶段（投料/分析/规划/出片）**不是同一套东西**，且 `:13-14` 两步都指向 `produce`。被 `WorkbenchHeader.tsx:7,54` 引用 | **不在 P-3.1 处置**：该目录属另一位工程师（OCR 字幕通道）。随 P-3.2 的剧空间阶段条替换 | P-3.2（需与属主协调） |
| `EpisodeAnalysisResult.error` | `protocol/ts/index.ts:124` | 协议声明了 `error?: string`，而 `service/dramaclip/api/analysis.py:301-310` 构造的 entry 里没有该键，`episodes`/`episode_analysis` 两张表也都没有 error 列（实测 `pragma table_info`）。**是一个永远不会被填的字段** | 二选一：由 P-3.2 补服务侧（失败原因落库），或从协议删除该字段。本片不碰 `protocol/` 的既有声明 | P-3.2 |
| `AnalysisResults.prescreen` | `protocol/ts/index.ts:151-156` | 服务侧 `api/analysis.py:315-321` 返回 `prescreen` 与 `prescreen_score`/`recommended`，TS 类型里**都没有**。§5 行 12 把这三个字段标为「**新**（批1）」——**其中两个已经存在，规格此处已过期** | 由 P-3.2 同步类型（它才是覆盖度告警的消费方） | P-3.2 |
| `timeline-editor` 相关 | — | 全库 grep `TimelineEditor\|replace_timeline` 零命中 | **已关闭**（§2.2 该行可划掉） | — |

---

## 6. 「全站切到新 IA」能拿什么验（§9 七条的可达性）

先说桌面端测试基建的实测结论，因为它决定了下面哪些是"自动"哪些是"手工"：

**基建存在，但只有三层，且没有任何视觉/端到端能力。**
- 运行器：`desktop/vitest.config.ts`（vitest 5 + jsdom，`include: ['src/**/*.test.{ts,tsx}', 'main/**/*.test.ts']`）。实测 `cd desktop && npx vitest run` → **6 文件 16 用例全绿，45.07s**。
- 组件测试：**有先例但只有一处**——`desktop/src/features/analysis/EpisodeListRow.test.tsx`（`@testing-library/react` 的 `render`，`:7` 注明 vitest 未开 globals 故需手动 `afterEach(cleanup)`）。
- 契约测试：`desktop/src/__tests__/contract.test.ts` 用 node 环境**读磁盘上的 schema 文件**比对 `METHOD_NAMES`。这是本仓"扫源码/扫文件当测试"的既有先例，P-3.1 的一致性守卫与假文案守卫沿用同一手法。
- 类型检查：`npm run typecheck`（`tsc --noEmit -p tsconfig.app.json && … tsconfig.node.json`）实测干净通过。
- Lint：`npm run lint`（`eslint src main`）实测干净通过。`desktop/eslint.config.mjs:25-26` 有 `max-lines: 300` / `max-lines-per-function: 60` 硬门禁，`:51-61` 有禁裸写 `fontSize`/`borderRadius` 的 DSS 守护。
- **没有**：Playwright / 任何浏览器自动化 / Storybook / 视觉回归 / 快照测试（`desktop/package.json:16-46` 依赖表逐项核过）。§9.1 与 §9.7 因此**不可能自动化**。

| §9 条 | 能否自动验 | 归属切片 | 不能自动时的手工协议 |
|---|---|---|---|
| 1. 任取两页截图并排，页头/分区/按钮/间距同构 | **不能**（无视觉基建）。可**半自动**：源码扫描断言每个页面文件都 import 并使用 `PageShell`+`PageHeader`，禁手写 `<header>` | 每片各自 + 最后一片复核 | 起 `npm run dev`（端口固定 5180，`desktop/vite.config.ts` `strictPort`），逐页截图，两两并排比四项：页头高度与标题字号、分区标题的渐变竖条、primary 按钮个数（每屏 ≤1）、纵向间距是否只出现 20/24 |
| 2. 一次提交 10 剧 × 3 模式 × K=3 全程不出应用 | 不能 | P-3.2 之后 | 手工跑一遍，记录每一处"不得不打开资源管理器"的位置；期望为零 |
| 3. 五类静默事件各有落点，可逐条指认 | **部分能**：每类落点都可写 RTL 用例，断言给定输入下渲染出指定文案（先例 `EpisodeListRow.test.tsx`）。"用户是否真看得见"不能自动 | 分散：LLM 成稿失败→P-3.2 队列条；覆盖度→P-3.2；参数未生效→P-3.2；单集失败→P-3.2；字幕位置未检测→P-3.2 | 逐条指认表：为五类各写一行「触发方式 → 期望在哪个页面哪一块看到什么字」，人工逐条触发并截图 |
| 4. 30 秒内从 60 条片筛出可发子集 | 不能（计时 + 判断） | P-3.3 | 造 60 条真成片，只用徽章与角度标签筛，秒表计时；**不得逐条播放** |
| 5. 无任何界面文案描述未实装能力 | **能，且 P-3.1 就把它变成永久门禁**：源码扫描全 `src/` 的被禁词表 | **P-3.1 建立，此后每片自动继承** | 无需手工。被禁词表可增不可减 |
| 6. 映射表 47 行全部可点开验证 | **半自动**：可断言每行的 RPC ∈ `METHOD_NAMES`（扩展现有 `contract.test.ts`）；"可点开"仍需手工 | 最后一片 | 逐行走 §5 表：点控件 → 看是否有请求发出 / 是否有可见反馈；期望零个"按钮存在但接口缺席" |
| 7. 规模实测（50 剧 + 500 成品 + 单剧 100 集） | 不能，**且今天连造数脚本都没有**：`scripts/` 下只有 `build-service.py`/`dev.mjs`/`make_icon.py`/`verify_e2e.mjs`/`verify_modes.py`/`verify_sidecar.mjs` | 必须在 P-3.2/P-3.3 之前补 | 先写造数脚本（直接写 SQLite，不经 UI），再手工测三处帧率与首屏：剧库滚动、成品分组网格、素材列表。**§9.7 自己写着"当前未测，故列为验收项而非结论"——这一条今天连测的手段都不具备，是 P-3 的一个未登记前置缺口** |

---

## 7. 与 P-2 的文件碰撞面（排期用）

**本节已按 P-2 计划成文后核对**：`docs/superpowers/plans/2026-09-12-p2-plan-render-split.md` 在本文写就期间落地，其真实文件清单可从该文件读出（`desktop/src/__tests__/contract.test.ts`、`desktop/src/features/narration/useProduceJob.ts`、`desktop/src/services/client.ts`、`protocol/schemas/{export,jobs,narration,project}.json`、`protocol/ts/index.ts`、`service/dramaclip/api/{export,narration}.py`、`engines/narration/{angles,copywriter,overlap,script_driver,scriptwriter}.py`、`infra/config.py`、`infra/storage/migrations/010_plan_angles.sql`、`infra/storage/repos/plans.py`）。下表因此不再是推测。

| 文件 / 区域 | P-2 会改 | P-3 哪片会改 | 冲突性质 | 建议 |
|---|---|---|---|---|
| **`JobInfo.type` 词表** | **已确认会改**：P-2 Step 3 把 `jobs.json` 的描述从 `prescreen\|analysis\|semantic\|narration\|produce\|export\|model_download` 改成**去掉 `produce`**（该 job 类型随 `narration.produce` 消失，`plan_variants` 复用 `narration`），并补上 `semantic` | **P-3.1** 有三处列了 `produce`：`todos.ts` 的 `PROJECT_JOB_TARGETS`、`HomePage.tsx` 的 `PROJECT_JOB_TYPES`、`protocol/ts/index.ts` 的 `JobInfo.type` docstring | **语义冲突，不是文本冲突**——两边都不会报合并错，但后落地的一方会留下一个永不命中的 map 键或一条过期的类型注释 | P-3.1 保留 `produce`（它今天在 `api/narration.py:327` 真实存在），**谁后落地谁收口**。P-2 的计划今天没列这三处，需补 |
| `protocol/ts/index.ts` 的 `METHOD_NAMES`（`:311-358`） | **必改**（追加 `narration.plan_variants`/`get_plan`、`export.submit`、`project.batch_create`） | P-3.3（`export.set_cover`/`delete`/`rename`）、P-3.4（6 个 `tools.*`）、P-3.6（更新检查器若走 RPC） | **同一数组尾部追加 → 必冲突** | 约定：**谁先合谁赢，后者 rebase**。P-3.1 明确不碰这个数组（它只加三个 interface，位置在文件中段） |
| `protocol/ts/index.ts` 的类型区 | 追加 plan/variant 相关 interface | **P-3.1** 追加 `JobStatus`/`JobInfo`/`JobsListResult`（`jobs.json` 的 `x-models` 里已定义，P-1 漏同步）；P-3.3 追加 `WorkItem` 字段 | 不同区域追加，git 通常可自动合 | **P-3.1 先合**，把"schema 已定义但 TS 未同步"这笔 P-1 欠账还掉 |
| `protocol/schemas/jobs.json` | **已确认会改**（Step 3 的 type 描述） | P-3.1 **不改**（只读它来同步 TS 类型） | 无文本冲突 | P-3.1 的 `JobInfo` docstring 直接引用该词表，P-2 改完需回看 P-3.1 那三处 |
| `protocol/schemas/{narration,project}.json` | P-2 主战场 | P-3 各片不改 | 无 | — |
| `protocol/schemas/export.json` | P-2 加 `export.submit` | P-3.3 加 `set_cover`/`delete`/`rename` | **同文件 → 会撞** | P-3.3 的协议改动排在 P-2 合并之后 |
| `desktop/src/services/client.ts` | **已确认会改**（Step 4 整块替换 `narrationApi`，`:108-125`） | **P-3.1** 插入 `jobsApi`（在 `analysisApi` 之后、`listWorks` 之前，即 `:103-105` 之间）；P-3.3 追加 `exportApi` 三方法；P-3.4 追加 `toolsApi` | **同文件、相邻区域 → 高概率冲突** | P-3.1 的插入点刻意选在 `narrationApi` **之前**，与 P-2 的整块替换不重叠；仍建议 P-3.1 先合 |
| `desktop/src/__tests__/contract.test.ts` | **已确认会改** | P-3.1 **不改**，但依赖它保持绿（作为"没动 METHOD_NAMES"的证明） | 无 | P-3.1 的完成判据第 3 条以它为凭 |
| `desktop/src/features/narration/useProduceJob.ts` | **已确认会改** | P-3.1 只改同目录的 `ProductionPage.tsx:30-32`（加一行 `rememberDrama`） | 不同文件，但同一 feature | 两边都动 `features/narration/`，合并时留意 |
| `desktop/src/app/router.tsx` | P-2 不改 | **P-3.1 重写结构**、P-3.2 加两组改名与重定向 | P-3.1 之后无冲突 | **P-3.1 必须先合**；这是它排第一刀的理由之一 |
| `desktop/src/app/navItems.ts`（P-3.1 新建） | P-2 不碰 | P-3.2（剧库改名）、P-3.4（工具箱）、P-3.6（关于）、P-2.5（队列） | 每片追加一行，数组尾部 | 追加而非重排；`group` 字段决定插入位置 |
| `desktop/src/components/layout/*` | P-2 不碰 | **只有 P-3.1 改结构**，此后各片只改 `navItems.ts` | P-3.1 之后无冲突 | 这正是清单化的收益 |
| `desktop/src/components/modeMeta.ts` | P-2 若新增模式则要改 | P-3.2 收口"第三面镜子"（P-1.5 计划 Task 4 实测修正登记的 P-3 已知接受项） | 低 | P-3.2 处理 |
| `service/dramaclip/api/export.py` | P-2 从中拆出 `export.submit` | P-3.3 加 `set_cover`/`delete`/`rename` | **同文件 → 会撞** | P-3.3 的服务侧开发排在 P-2 合并之后 |
| `service/dramaclip/api/narration.py`、`engines/narration/*`、`infra/storage/repos/plans.py`、`infra/config.py`、`migrations/` | P-2 主战场 | P-3 各片都不改 | 无 | **P-3.1 完全不碰 `service/`，与 P-2 零冲突** |
| `desktop/src/features/settings/sections.ts` | P-2 可能加 K 默认键 | P-3.2 加「生产线默认值」「字幕」两分区 | 同文件 | P-3.2 在 P-2 之后 |
| `desktop/src/features/analysis/*` | P-2 不碰 | **P-3 任何切片都不主动改**（属 OCR 字幕通道另一位工程师） | — | P-3.2 要动 `StepsNav`/`WorkbenchHeader`/`WorkbenchPage` 时**必须先与属主协调**；这是本拆分里唯一一处跨所有权依赖 |

**从核对结果得到的一条排期结论**：P-3.1 与 P-2 的真实碰撞面只有 **3 个文件**（`protocol/ts/index.ts` 类型区、`desktop/src/services/client.ts`、以及 `produce` 词表的语义冲突），且 P-3.1 的插入点都刻意避开了 P-2 的整块替换区。**P-3.1 可以与 P-2 真并行**，前提是 P-3.1 先合。P-3.3 与 P-2 的碰撞面则大得多（`api/export.py` + `export.json` + `client.ts`），必须串行。

---

## 8. 规格问题清单（本轮读代码读出来的，需所有者裁决或修规格）

1. **§4.6 的「输出四键接线前标注『当前未生效：成片固定 1080×1920』」已过期。** correctness 计划 `:1722` 已把 C4 判为**作废**，理由是 `export.width/height` 已被 `_output_size` 接线（`service/dramaclip/api/export.py:188-189` 读 `config.get_int`），而另两键 `export.encoder`/`bitrate_kbps` 属死配置、已按"不考虑向后兼容"直接从 `config.DEFAULTS` 删除（实测 `infra/config.py:19-44` 已无这两键）。**所以今天不存在"输出四键"，也不存在需要标注未生效的输出键。** §4.6 该句应删。
2. **§5 行 12 把 `prescreen_score`/`recommended`/`planned_coverage` 三个字段都标为「新」，前两个其实已经交付。** `service/dramaclip/api/analysis.py:308-309` 已返回 `prescreen_score` 与 `recommended`；只有 `planned_coverage` 缺。真正缺的反而是**协议侧类型**：`protocol/ts/index.ts:151-156` 的 `AnalysisResults` 没有 `prescreen` 字段，`EpisodeAnalysisResult` 也没有这两个字段。
3. **§2.1 序 7 与 §4.6 描述的「设置」职责（生产线默认值 / 分析 / 字幕 / 输出 / 存储 / 代理）有四个分区不存在，其中两个连设置键都没有。** 实测 `desktop/src/features/settings/sections.ts:131-138` 只有 出片/分析/下载/硬件 四区；`config.py:19-44` 的 `DEFAULTS` 里没有存储、代理相关任何键，也没有 K 默认键。「字幕」的键存在（`subtitle.default_preset`/`subtitle.smart_match`）但没有分区——**这是"文档记为完成、界面恒不可达"的老毛病的又一例**。「代理」若真要做，需要新设置键 + HTTP 层真消费，**它不在 §6 的 29 处缺口清单里，是漏项**。建议：字幕分区归 P-3.2；存储与「关于 → 本地数据」重复，应合并到 P-3.6；代理需先立项再排期。
4. **§4.5 的「单片 → 预览」与所有者的既定「不做预览」直接冲突，而今天的代码里就有一个预览面。** `desktop/src/features/works/WorksPage.tsx:105-110` 是 `<video src={mediaUrl(work.output_path)} controls autoPlay>`，`:245-247` 的封面区还写着「点击预览」。§7 非目标列的是「生成前预览」，字面上不覆盖"播放已渲染的成片"，但所有者把「不做预览」列为长期决定。**需裁决**：是删掉这个 `<video>` 弹层（改为"打开所在文件夹"/"用系统播放器打开"），还是承认"成片回放"与"生成前预览"是两件事。P-3.3 开工前必须定，否则它会在两个方向上各做一半。
5. **§4.2 与 §4.1 对「快速上手」的处置互相矛盾。** §4.1 把「快速上手」列为工作台右栏三块之一；§4.2 却说「旧的"快速上手"假文案正在被删除，删完必须补上真引导」。实测 `EnvPanel.tsx:155-158` 的两条 tips **今天都是真的**（「分析页点对白流直接改，改完重跑语义」对应 `analysis.update_asr`+`resync_semantic`，均 ✓；「九种模式支持一键全部生成」对应 `ProductionPage.tsx:137-148` 的全选+开始出片，✓）。**P-3.1 的处置：保留但逐条核真，删除那个假的「工具箱」面板**；若所有者本意是整块删掉，请明示，P-3.1 会照改。
6. **§4.1 的三条"删除的假文案"里，两条已经删过了。** 「短剧素材也可以拖进来」与「AI 自动预筛与全量分析」在 correctness 计划 Phase C 已改口（实测 `desktop/src` grep `拖进来`/`自动预筛` 均 0 命中；`HomePage.tsx:104` 现为「选择一个方式开始，或选择素材所在文件夹」，`StartCards.tsx:25` 现为「逐集转写与冲突分析」）。**但 §4.1 没提的第三类假话还在，而且更严重**：三处"未配 LLM 会关键词降级"（`useTodos.ts:32`、`LlmTab.tsx:13`、`OverviewTab.tsx:74`）。P-1.5 之后解说文案无模板兜底、未配置即抛错（P-1.5 计划 Task 5），这三句话会让操盘手以为提交后总能出片，实际是七个解说模式逐条失败。P-3.1 把这条修掉并钉成永久门禁。
7. **§3.4 的 `<data>/.trash/<日期>/` 在服务侧零实现**，且 §6 的 29 处缺口清单里**没有"回收站"这一项**——它只出现在 `export.delete` 的语义里。P-3.3 必须把它当作一个显式交付物（含"清空回收"的二次量化确认与「关于 → 本地数据」的可达入口），否则 §3.4 第 2 条落不了地。
8. **§9.7 的规模实测没有手段。** 规格自己写「必须在 P-3 前跑一次」，但仓内没有造 50 剧 / 500 成品 / 单剧 100 集的脚本。**这是 P-3 的一个未登记前置项**，建议作为 P-3.2 的 Task 0（它是三处性能风险里两处的归属页）。
9. **§2.1 的高亮规则只点了剧空间，实际 `/engines/:tab` 深链今天也全线失高亮**（`AppLayout.tsx:60` 精确等值比较 vs `EnvPanel.tsx:37,43,47`、`OverviewTab.tsx:94,103,111` 六处跳 `/engines/<tab>`）。P-3.1 一并修，规格可补一句。

---

## 9. 各切片的规格覆盖对照（确认没有内容掉在刀口外）

| 规格条目 | 归属 |
|---|---|
| §2.1 导轨 8 项分两组 + 分隔线 | P-3.1（结构与 5 项）+ P-3.4（工具箱）+ P-3.6（关于）+ P-2.5（队列）+ P-3.2（剧库改名） |
| §2.1 高亮规则 | P-3.1（前缀匹配，含 `/engines/:tab`）+ P-3.2（剧空间保持剧库高亮 + PageHeader 显剧名） |
| §2.2 路由表与废弃项 | `/models` 已关闭；`TimelineEditor` 已关闭；`/projects`→`/dramas` 与 `/projects/:id/*`→`/drama/:id/*` 归 P-3.2；`../../works` 已关闭（`StepsNav.tsx:15` 现为绝对路径） |
| §2.3 剧空间四阶段骨架 | P-3.2 |
| §3.1 阶段条四态 | P-3.2 |
| §3.2 色彩纪律 | 全片继承（`styles/theme.ts` 已是 DSS 唯一真相源）；P-3.2 负责角度名固定用 `status/warning` |
| §3.3 静默禁止清单五行 | 行1 LLM 成稿失败→P-3.2；行2 覆盖度→P-3.2；行3 参数未生效→P-3.2；行4 单集失败→P-3.2；行5 字幕位置未检测→P-3.2（按 §10.4 回退并标注） |
| §3.3.1 降级裁决表 | P-1.5 已定案；界面可见性归 §3.3 |
| §3.4 危险操作四条 | P-3.3（批量删成品、回收站）+ P-3.2（删剧单独措辞）+ P-3.4（清空工具箱产物） |
| §4.1 工作台 | P-3.1（除钩帧缩略）；钩帧缩略→P-3.3 |
| §4.2 剧库 | P-3.2 |
| §4.3 剧空间 | P-3.2 |
| §4.4 队列 | **P-2.5**（不属 P-3） |
| §4.5 成品 | P-3.3（除角度名/跳回方案，那两项等 P-2 的 `get_plan`） |
| §4.6 引擎 / 设置 | 引擎页沿用既有；设置页「生产线默认值」+「字幕」→P-3.2；「存储」→并入 P-3.6；「代理」→**需先立项**（见 §8.3） |
| §4.7 工具箱 | P-3.4（六件）+ P-3.5（图片生成与 AI 标识） |
| §4.8 关于 | P-3.6 |
| §5 映射表 47 行 | 逐行归属见 §3 各片；行 23-26（队列）属 P-2.5 |
| §7 非目标 | 全片继承；P-3.2 负责"阶段条内不放任何编辑器" |
| §8 待否决假设 | 行 5（图片生成取舍）阻塞 P-3.5；行 6（导轨分组）已由 §2.1 按 B 定案；其余不阻塞 |
| §9 验收 7 条 | 见本文件 §6 |
| §10 画面通道 | 属批次 2，不属 P-3；P-3.2 只负责"探测器缺席时按 §10.4 显式标注" |
| §11 服务对接清单 | 行 7（vision）属批次 2；行 8（图像）→P-3.5；行 14（更新检查器）→P-3.6；其余已归属或已完成 |
| §12 批次顺序 | 本文件即 P-3 的展开 |
