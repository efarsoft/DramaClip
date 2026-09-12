# P-3.1 导航壳与工作台开工页 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把信息架构从散落在 JSX 里的内联数组变成两份可测的数据清单（导轨 + 路由），并按规格 §4.1 把工作台从介绍页改造成开工页——三统计芯片、可执行待办、空态引导——同时把界面上三处"未配 LLM 会关键词降级"的假话清零并钉成永久门禁。

**Architecture:** 三层切分——**IA 数据层**（新增 `app/navItems.ts` 与 `app/routes.ts`，此后每个切片加一页 = 追加一行数据，不再重构 `AppLayout.tsx`/`router.tsx`）、**派生层**（`features/home/todos.ts` 与 `stats.ts` 是不碰 RPC 的纯函数，"哪些状态该变成待办""ETA 怎么外推"这两条业务规则因此可被单测穷举）、**装载与视图层**（`useWorkbench.ts` 一次并发取全，`TodoList`/`StatChips`/`EmptyWorkbench`/`ContinueCard` 只渲染派生结果）。本计划首次消费 P-1 已交付但至今零调用者的 `jobs.list`。

**Tech Stack:** TypeScript 5.9（`strict` + `noUncheckedIndexedAccess` + `verbatimModuleSyntax`）/ React 19 / react-router-dom 7（`HashRouter`）/ AntD 6 / zustand 5（仅经既有 `stores/ui.ts`；「继续上次」刻意**不用** zustand `persist`，改用 `stores/lastDrama.ts` 的三个 localStorage 函数，理由见 Task 7 Step 6 的 docstring）/ vitest 5 + jsdom + `@testing-library/react` 16 / eslint 10（`max-lines: 300`、`max-lines-per-function: 60`、禁裸写 `fontSize`/`borderRadius`）。

规格出处：`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §2.1（导轨与高亮规则）、§2.2（路由表与废弃项）、§3.2（色彩纪律）、§3.3（静默禁止清单）、§4.1（工作台）、§9.1/§9.5（验收）。
拆分依据：`docs/superpowers/plans/2026-09-12-p3-decomposition.md`（本计划是其 P-3.1 切片）。
视觉真相源：`docs/desktop/04-设计系统方案.md`（DSS v1）——本计划不新造视觉规则，一律引用 `desktop/src/styles/theme.ts` 的 token。**唯一的例外**是 Task 7 新增 `tokens.fontEmptyIcon: '48px'`：DSS §3.5 规定空态图标为 48，而现有 token 里没有这一档，同时 `eslint.config.mjs:54` 禁止裸写字号——所以必须落一个有 DSS 出处的 token，而不是写魔法数。

---

## 本片的位置与硬边界

**上一批的既成事实（不得推翻，只能承接）**：P-1.5 之后解说文案**无模板兜底**——LLM 未配置或成稿不合格即抛错，失败粒度是单条方案（P-1.5 计划 Task 3/5/6）。所以"未配 LLM 也能出片"在界面上的任何暗示都是假话，Task 3 专门清这一类。允许级降级只剩分析层（`semantic/conflict.py`、`genre.py` 的关键词打分），它**必须可见**但不得与解说文案混为一谈。

**本计划不动的东西（越界即停）**：

| 不动 | 理由 |
|---|---|
| `service/` 全部 | 本片零后端。所有数据都取自既有方法：`project.list`、`models.list`、`settings.get`、`export.list_works`、`jobs.list` |
| `protocol/schemas/*.json` | 不改契约。Task 4 只把 `jobs.json` 的 `x-models.JobInfo`（**已经定义好了**）同步进 `protocol/ts/index.ts`，**不新增任何 `METHOD_NAMES` 条目** |
| `desktop/src/features/analysis/**` | **属另一位工程师（OCR 字幕通道）**。本片需要单剧入口路径时走 `routes.ts` 的 `dramaEntryPath()`，不去改 `WorkbenchPage.tsx:63,66` / `WorkbenchHeader.tsx:30` |
| `scripts/verify_e2e.mjs`、`scratch/`、`docs/07-*`、`hotwords.py`、`tests/api/test_analysis.py`、`tests/engines/analysis/*` | 同上，属主另有其人 |
| `docs/05-开发路线图.md` | 用户自维护 |
| `/projects` → `/dramas` 路由改名 | 它与 §4.2 剧库页是同一个原子改动，且会波及 `features/analysis/`。归 P-3.2 |
| 「队列」「工具箱」「关于」三个导轨项 | 目的地不存在。§9.5「无任何界面文案描述未实装的能力」——一个点了跳空壳的导轨项就是假文案 |

**缺席而非假控件（本片处理被阻塞部分的统一口径）**：能力没到位就**不渲染那个控件**，绝不渲染一个不能用的控件。具体见 Task 4（待办只收有落点的来源）、Task 5（成品数溢出时显示 `N+` 而非假精确值）、Task 7（最近成品不出缩略图，因为逐片封面不存在）。

**提交纪律**：只 `git add` 显式路径，**禁止 `git add -A` / `.` / `-a`**——同树同分支另有工程师在提交，宽 add 会卷走别人的暂存（沿用 P-1.5 计划的同一纪律）。

**⚠️ 执行时机**：Task 9 的手工浏览器步骤需要起 dev server 与 Python 服务。**本机九模式真机门禁跑完之前不要执行 Task 9**——CPU 争用会让门禁的时序断言失真。Task 1-8 只跑 `vitest` / `tsc` / `eslint`，可以照常执行。

---

## 文件结构

**新建（IA 数据层）**
- `desktop/src/app/navItems.ts` —— 导轨清单：8 项终态里的 5 项、两组、前缀命中判定。全站导航唯一真相源。
- `desktop/src/app/routes.ts` —— 路由清单：顶层路由 / 详情路由 / 旧路径重定向表 / 单剧入口。
- `desktop/src/app/__tests__/navItems.test.ts` —— 清单纯函数测试（分组、唯一性、图标同构、命中判定）。
- `desktop/src/app/__tests__/iaContract.test.ts` —— **三方一致性守卫**：导轨 ↔ 路由清单 ↔ `router.tsx` 的 `path`/`to` 字面量。手法沿用 `desktop/src/__tests__/contract.test.ts`（node 环境读磁盘源文件）。

**新建（假文案门禁）**
- `desktop/src/__tests__/copyTruth.test.ts` —— 扫全 `src/` 的被禁词表。§9.5 与合规红线（消重/抗比对）的永久门禁。

**新建（工作台派生层，纯函数）**
- `desktop/src/features/home/todos.ts` —— `buildTodos` / `buildDramas`：状态 → 可执行待办。
- `desktop/src/features/home/stats.ts` —— `buildStats` / `etaLabel`：三芯片与 ETA 线性外推。
- `desktop/src/features/home/__tests__/todos.test.ts`
- `desktop/src/features/home/__tests__/stats.test.ts`

**新建（工作台视图与装载）**
- `desktop/src/features/home/useWorkbench.ts` —— 一次并发装载全部数据源，服务就绪前不发请求。
- `desktop/src/features/home/TodoList.tsx` —— 取代 `TodoCard.tsx`（AntD `Alert` 只能通知，点不动）。
- `desktop/src/features/home/StatChips.tsx`
- `desktop/src/features/home/EmptyWorkbench.tsx` —— 无剧时的主区引导。
- `desktop/src/features/home/ContinueCard.tsx` —— 继续上次。
- `desktop/src/features/home/createDrama.ts` —— 从 `StartCards.tsx:88-103` 抽出的建剧动作（选目录 → 建项目 → 扫集）。
- `desktop/src/features/home/relativeTime.ts` —— 「继续上次」的相对时间（从 `ContinueCard.tsx` 拆出，避免 `react-refresh/only-export-components` 常驻 warning）。
- `desktop/src/stores/lastDrama.ts` —— 「继续上次」的本地偏好（三个 localStorage 函数，不用 zustand persist；这正是 `docs/desktop/01-渲染层设计.md:29` 早已写下的设计：「localStorage 记忆上次项目与页面，只记位置」）。
- `desktop/src/components/layout/Rail.tsx` —— 导轨渲染，从 `AppLayout.tsx:38-111` 抽出。**抽出的理由是它必须能单独被 RTL 渲染测试**：`AppLayout` 连带 `TitleBar`（要 `window.dramaclip.windowControl`）与 `StatusBar`（要 `systemApi.health`），在 jsdom 里整体渲染必炸。
- `desktop/src/components/layout/__tests__/Rail.test.tsx`
- `desktop/src/features/home/__tests__/TodoList.test.tsx`、`__tests__/StatChips.test.tsx`、`__tests__/createDrama.test.ts`、`__tests__/lastDrama.test.ts`、`__tests__/EmptyWorkbench.test.tsx`、`__tests__/relativeTime.test.ts`

**修改**
- `desktop/src/components/layout/AppLayout.tsx` —— 删内联 `NAV_ITEMS`（`:15-21`）与 `Rail`/`RailButton`（`:38-111`），改为渲染 `<Rail />`。
- `desktop/src/app/router.tsx` —— 重定向表数据化，`LegacyModelTabRedirect` 泛化为 `LegacyParamRedirect`（P-3.2 的两组改名可直接复用同一形状）。
- `desktop/src/services/client.ts` —— 新增 `jobsApi.list`（P-1 交付的 `jobs.list` 的**第一个消费者**）。
- `protocol/ts/index.ts` —— 补 `JobStatus` / `JobInfo` / `JobsListResult` 三个类型（`jobs.json` 已定义，P-1 漏同步）。
- `desktop/src/features/home/HomePage.tsx` —— 按 §4.1 重写：`PageShell` + `PageHeader` + 待办 + 三芯片 + 最近成品 + 继续上次 + 空态。
- `desktop/src/features/home/RecentWorks.tsx` —— 改用 `PageSection`，删本地第三份竖条标题（`:74-88`）。
- `desktop/src/features/home/EnvPanel.tsx` —— 删 `ToolboxPanel`（`:105-153`，名为工具箱而零个工具）。
- `desktop/src/features/engines/LlmTab.tsx:11-14`、`desktop/src/features/engines/OverviewTab.tsx:74` —— 假降级文案改口。
- `desktop/src/features/works/WorksPage.tsx:63,64,72` —— 页头「作品库」→「成品库」，与导轨标签同批改。
- `desktop/src/features/project/ProjectsPage.tsx:44-48`、`desktop/src/features/narration/ProductionPage.tsx:28-36` —— 打开单剧时记录「继续上次」。
- `desktop/src/components/layout/TitleBar.tsx:10,175` —— 搜索结果跳转改走 `dramaEntryPath()`（`:175` 今天硬写 `/projects/${item.id}/analysis`），并记录「继续上次」。
- `desktop/src/styles/theme.ts` —— 字号区新增一行 `fontEmptyIcon: '48px'`（DSS §3.5 的空态图标规格；本计划唯一一处 token 新增，出处见上方「视觉真相源」）。
- `desktop/src/features/home/stats.ts`、`todos.ts`、`useWorkbench.ts`、`StatChips.tsx`、`HomePage.tsx` 与三个对应测试文件 —— Task 9 给它们补 `jobsAvailable`/`jobsError`（本文件新建，Task 9 再改，故在此重列一次以免漏看）。
- `desktop/src/app/__tests__/iaContract.test.ts` —— Task 9 追加分层守卫两条用例。
- `docs/desktop/01-渲染层设计.md:8-29` —— §1 的导航描述与路由表**严重过期**（列了 `/projects/:id/modes`、`/projects/:id/generate`、`/plans/:planId/timeline`、`/projects/:id/export`、`/models` 五条今天不存在的路由，还描述了已废弃的"双层导航"与不存在的侧边栏重启按钮），Task 9 Step 10 整块重写。
- `docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §2.1 —— Task 9 Step 11 补记本轮新发现的第二处高亮缺陷（`/engines/:tab` 深链）。

**删除**
- `desktop/src/features/home/SectionTitle.tsx` —— 竖条标题三份拷贝之一（DSS §6.3 点名要收敛；另两份是 `StartCards.tsx:160 PanelTitle`、`RecentWorks.tsx:74 SectionHeader`）。
- `desktop/src/features/home/StartCards.tsx` —— 三张卡里两张是导轨已有目的地的重复（「继续创作」跳 `/projects`、「引擎中心」跳 `/engines`）；含第二份竖条标题。
- `desktop/src/features/home/RecentProjects.tsx` —— §4.1 的主区结构里没有"最近项目"这一格，功能被「继续上次」与剧库页覆盖。
- `desktop/src/features/home/TodoCard.tsx` —— 被 `TodoList.tsx` 取代。
- `desktop/src/features/home/useTodos.ts` —— 被 `todos.ts`（纯函数）+ `useWorkbench.ts`（装载）取代。

---

## 验证命令（全片通用，实测基线）

三条命令在开工前**已实测全绿**，任何一步之后变红都是本片引入的：

```bash
cd /d/PersonProjects/DramaClip/desktop && npx vitest run
cd /d/PersonProjects/DramaClip/desktop && npm run typecheck
cd /d/PersonProjects/DramaClip/desktop && npm run lint
```

开工前基线实测输出（2026-09-12）：

```
 RUN  v5.0.0 D:/PersonProjects/DramaClip/desktop

 ✓ main/services/ndjson.test.ts (4 tests) 7ms
 ✓ main/services/restart-policy.test.ts (2 tests) 7ms
 ✓ src/__tests__/contract.test.ts (1 test) 9ms
 ✓ main/services/pipe-server.test.ts (3 tests) 195ms
 ✓ main/services/service-manager.test.ts (3 tests) 7ms
 ✓ src/features/analysis/EpisodeListRow.test.tsx (3 tests) 271ms

 Test Files  6 passed (6)
      Tests  16 passed (16)
```

`npm run typecheck` 与 `npm run lint` 均**零输出、退出码 0**（只有 npm 自己的 `npm warn Unknown project config "electron_mirror"` 与 `npm notice run …` 两行噪音）。

vitest 未开 `globals`（`desktop/vitest.config.ts` 无 `globals: true`），所以：**每个测试文件都必须显式 `import { describe, expect, it } from 'vitest'`，且 RTL 的自动 cleanup 不会注册，必须自己 `afterEach(cleanup)`**——先例见 `desktop/src/features/analysis/EpisodeListRow.test.tsx:3,7`。

---

## Task 1: 导轨清单化——两组、分隔线、前缀高亮

修的是既有缺陷：`desktop/src/components/layout/AppLayout.tsx:60` 用 `location.pathname === item.path` 精确等值比较，于是 `/engines/llm`（`EnvPanel.tsx:37` 的「去配置」就跳这里）与 `/projects/:id/analysis` 都会让**整条导轨失去高亮**。规格 §2.1 只点了后者，前者是本轮读代码新发现的同源缺陷。

同批把导轨标签「作品」改为「成品」，并**在同一个提交里**改 `WorksPage` 的页头——标签与页面必须同时改，否则导轨说「成品」而页面说「作品库」，是另一种假话。

「项目」**不改名**为「剧库」：§4.2 的剧库页（四阶段微缩状态条、聚合行、卡片点击直跳当前阶段、首启三步空态）依赖 P-2 的 `project.list` 阶段聚合，只改名不改内容就是标签许诺了页面没有的东西。归 P-3.2。

**Files:**
- Create: `desktop/src/app/navItems.ts`
- Create: `desktop/src/components/layout/Rail.tsx`
- Create: `desktop/src/app/__tests__/navItems.test.ts`
- Create: `desktop/src/components/layout/__tests__/Rail.test.tsx`
- Modify: `desktop/src/components/layout/AppLayout.tsx`（整文件替换）
- Modify: `desktop/src/features/works/WorksPage.tsx:63,64,72`

- [ ] **Step 1: 写失败测试——清单不变量**

`desktop/src/app/__tests__/navItems.test.ts`：

```ts
import { describe, expect, it } from 'vitest';
import { NAV_GROUPS, NAV_ITEMS, isNavActive, navByGroup } from '../navItems';

describe('导轨清单（规格 §2.1）', () => {
  it('分两组，且上组是生产循环、下组不产生内容', () => {
    expect(NAV_GROUPS).toEqual(['loop', 'config']);
    expect(navByGroup('loop').map((item) => item.label)).toEqual(['工作台', '项目', '成品']);
    expect(navByGroup('config').map((item) => item.label)).toEqual(['引擎', '设置']);
  });

  it('数组顺序即渲染顺序：上组全部排在下组之前', () => {
    const groups = NAV_ITEMS.map((item) => item.group);
    expect(groups.lastIndexOf('loop')).toBeLessThan(groups.indexOf('config'));
  });

  it('路径唯一、标签唯一、每项都有图标（并列元素必须同构）', () => {
    const paths = NAV_ITEMS.map((item) => item.path);
    expect(new Set(paths).size).toBe(paths.length);
    const labels = NAV_ITEMS.map((item) => item.label);
    expect(new Set(labels).size).toBe(labels.length);
    for (const item of NAV_ITEMS) {
      expect(item.icon, `${item.label} 缺图标——导轨项要么全带图标要么全不带`).toBeDefined();
    }
  });

  it('标签是一个词，不用斜杠拼复合词', () => {
    for (const item of NAV_ITEMS) {
      expect(item.label).not.toMatch(/[/／·、]/);
      expect(item.label.length).toBeLessThanOrEqual(3);
    }
  });
});

describe('命中判定：进子路径时所属项保持高亮', () => {
  const byPath = (path: string) => {
    const item = NAV_ITEMS.find((candidate) => candidate.path === path);
    if (item === undefined) throw new Error(`清单里没有 ${path}`);
    return item;
  };

  it('根路径只精确命中，不得吞掉全站', () => {
    const home = byPath('/');
    expect(isNavActive(home, '/')).toBe(true);
    expect(isNavActive(home, '/works')).toBe(false);
    expect(isNavActive(home, '/settings')).toBe(false);
  });

  it('引擎深链保持「引擎」高亮（今天这条是坏的）', () => {
    const engines = byPath('/engines');
    expect(isNavActive(engines, '/engines')).toBe(true);
    expect(isNavActive(engines, '/engines/llm')).toBe(true);
    expect(isNavActive(engines, '/engines/asr')).toBe(true);
  });

  it('进单剧详情保持「项目」高亮（规格 §2.1 高亮规则）', () => {
    const projects = byPath('/projects');
    expect(isNavActive(projects, '/projects/abc123/analysis')).toBe(true);
    expect(isNavActive(projects, '/projects/abc123/produce')).toBe(true);
  });

  it('前缀按路径段边界匹配，不得把 /works-archive 判成 /works', () => {
    const works = byPath('/works');
    expect(isNavActive(works, '/works-archive')).toBe(false);
    expect(isNavActive(works, '/works/anything')).toBe(true);
  });

  it('任一时刻至多一项命中', () => {
    const paths = ['/', '/projects', '/projects/a/analysis', '/works', '/engines/llm', '/settings'];
    for (const pathname of paths) {
      const hits = NAV_ITEMS.filter((item) => isNavActive(item, pathname));
      expect(hits.length, `${pathname} 命中 ${String(hits.length)} 项`).toBe(1);
    }
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/app/__tests__/navItems.test.ts`
Expected: FAIL —— 形如 `Error: Failed to load url ../navItems (resolved id: …/src/app/navItems.ts)`，`Test Files  1 failed`。

- [ ] **Step 3: 写 `navItems.ts`**

`desktop/src/app/navItems.ts`：

```ts
/** 导轨清单：全站信息架构的唯一真相源（规格 §2.1）。
 *
 * 为什么单列一个文件而不是留在 AppLayout 里：导轨项、路由表、页面三者必须一致，
 * 而一致性只有在两边都是数据时才测得出来（见 __tests__/iaContract.test.ts）。
 * 新页面接入 = 在此追加一项 + 在 routes.ts 登记路径，不必重构 AppLayout。
 *
 * 终态是 8 项，今天只登记 5 项。缺席的三项各有归属：「队列」属 P-2.5，
 * 「工具箱」属 P-3.4，「关于」属 P-3.6（被两张二维码资产阻塞）。
 * 导轨项不得指向尚不存在的页面——那等同规格 §9.5 要清的假文案。
 */
import type { ComponentType, CSSProperties } from 'react';
import {
  CloudServerOutlined,
  DashboardOutlined,
  FolderOutlined,
  PlaySquareOutlined,
  SettingOutlined,
} from '@ant-design/icons';

/** loop = 生产循环（上组）；config = 配置与元信息（下组）。分组依据见规格 §2.1。 */
export type NavGroup = 'loop' | 'config';

export interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly icon: ComponentType<{ style?: CSSProperties }>;
  readonly group: NavGroup;
}

/** 渲染顺序：两组之间由 Rail 插入一条 border/subtle 分隔线。 */
export const NAV_GROUPS: readonly NavGroup[] = ['loop', 'config'];

export const NAV_ITEMS: readonly NavItem[] = [
  { path: '/', label: '工作台', icon: DashboardOutlined, group: 'loop' },
  { path: '/projects', label: '项目', icon: FolderOutlined, group: 'loop' },
  { path: '/works', label: '成品', icon: PlaySquareOutlined, group: 'loop' },
  { path: '/engines', label: '引擎', icon: CloudServerOutlined, group: 'config' },
  { path: '/settings', label: '设置', icon: SettingOutlined, group: 'config' },
];

export function navByGroup(group: NavGroup): readonly NavItem[] {
  return NAV_ITEMS.filter((item) => item.group === group);
}

/** 命中判定：根路径精确匹配，其余按"自身或子路径"匹配。
 *
 * 根路径若也走前缀匹配，它会同时命中全站每一条路径。
 * 其余项必须按路径段边界匹配（`${path}/`），否则 /works-archive 会被判成 /works。
 */
export function isNavActive(item: NavItem, pathname: string): boolean {
  if (item.path === '/') return pathname === '/';
  return pathname === item.path || pathname.startsWith(`${item.path}/`);
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/app/__tests__/navItems.test.ts`
Expected: PASS —— `✓ src/app/__tests__/navItems.test.ts (9 tests)`，`Tests  9 passed (9)`。

- [ ] **Step 5: 写失败测试——导轨渲染**

`desktop/src/components/layout/__tests__/Rail.test.tsx`：

```tsx
/** 导轨渲染：两组 + 一条分隔线 + 子路径保持高亮（规格 §2.1）。 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { NAV_ITEMS } from '../../../app/navItems';
import { Rail } from '../Rail';

// vitest 未开 globals，RTL 的自动 cleanup 不会注册（先例：EpisodeListRow.test.tsx:7）。
afterEach(cleanup);

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Rail />
    </MemoryRouter>,
  );
}

function buttonLabels(): string[] {
  return screen.queryAllByRole('button').map((button) => (button.textContent ?? '').trim());
}

function activeLabels(): string[] {
  return screen
    .queryAllByRole('button')
    .filter((button) => button.getAttribute('aria-current') === 'page')
    .map((button) => (button.textContent ?? '').trim());
}

describe('Rail', () => {
  it('按清单顺序渲染全部导轨项', () => {
    renderAt('/');
    expect(buttonLabels()).toEqual(NAV_ITEMS.map((item) => item.label));
  });

  it('两组之间有且只有一条分隔线', () => {
    renderAt('/');
    expect(screen.getAllByRole('separator')).toHaveLength(1);
  });

  it('分隔线落在上组末项与下组首项之间', () => {
    const { container } = renderAt('/');
    const nav = container.querySelector('nav');
    expect(nav).not.toBeNull();
    const sequence = Array.from(nav?.children ?? []).map((child) =>
      child.getAttribute('role') === 'separator' ? '|' : (child.textContent ?? '').trim(),
    );
    expect(sequence).toEqual(['工作台', '项目', '成品', '|', '引擎', '设置']);
  });

  it('根路径只高亮工作台', () => {
    renderAt('/');
    expect(activeLabels()).toEqual(['工作台']);
  });

  it('引擎深链保持引擎高亮', () => {
    renderAt('/engines/llm');
    expect(activeLabels()).toEqual(['引擎']);
  });

  it('单剧详情保持项目高亮', () => {
    renderAt('/projects/abc123/analysis');
    expect(activeLabels()).toEqual(['项目']);
  });

  it('分隔线用 border/subtle（#212736），不用更深的 border/strong', () => {
    const { container } = renderAt('/');
    const separator = container.querySelector('[role="separator"]');
    expect((separator as HTMLElement | null)?.style.background).toBe('#212736');
  });
});
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/components/layout/__tests__/Rail.test.tsx`
Expected: FAIL —— 形如 `Error: Failed to load url ../Rail`。

- [ ] **Step 7: 写 `Rail.tsx`**

`desktop/src/components/layout/Rail.tsx`：

```tsx
/** 左导轨：按 navItems 清单渲染，分两组，中间一条 border/subtle 分隔线。
 *
 * 分组不是装饰：上组就是生产循环本身，下组都不产生内容（规格 §2.1 分组规则）。
 * 分隔线用 role="separator" 而非裸 div，选中项加 aria-current="page"——
 * "两组"与"当前在哪"这两件事不该只写在 background 里，对辅助技术与测试都要可读。
 *
 * 从 AppLayout 抽出来的理由是它必须能单独被渲染测试：AppLayout 连带 TitleBar
 * （要 window.dramaclip.windowControl）与 StatusBar（要 systemApi.health），
 * 在 jsdom 里整体渲染会炸在桥接对象缺失上。
 */
import type { ReactElement } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { NAV_GROUPS, isNavActive, navByGroup, type NavItem } from '../../app/navItems';
import { tokens } from '../../styles/theme';

export function Rail(): ReactElement {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <nav
      style={{
        width: tokens.railWidth,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: tokens.spaceSm,
        paddingTop: tokens.spaceMd,
        background: tokens.bgSidebar,
        borderRight: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      {NAV_GROUPS.map((group, index) => (
        <RailGroup
          key={group}
          items={navByGroup(group)}
          pathname={location.pathname}
          dividerBefore={index > 0}
          onPick={(path) => {
            void navigate(path);
          }}
        />
      ))}
    </nav>
  );
}

function RailGroup({
  items,
  pathname,
  dividerBefore,
  onPick,
}: {
  items: readonly NavItem[];
  pathname: string;
  dividerBefore: boolean;
  onPick: (path: string) => void;
}): ReactElement {
  return (
    <>
      {dividerBefore && <GroupDivider />}
      {items.map((item) => (
        <RailButton
          key={item.path}
          item={item}
          active={isNavActive(item, pathname)}
          onClick={() => {
            onPick(item.path);
          }}
        />
      ))}
    </>
  );
}

/** 组间分隔线。用 border/subtle（tokens.borderSecondary）而非 border/strong：
 *  它是分组提示不是内容边界，视觉上必须比卡片描边更轻（规格 §2.1）。 */
function GroupDivider(): ReactElement {
  return (
    <div
      role="separator"
      style={{
        width: 36,
        height: 1,
        flexShrink: 0,
        margin: `${String(tokens.spaceSm)} 0`,
        background: tokens.borderSecondary,
      }}
    />
  );
}

function RailButton({
  item,
  active,
  onClick,
}: {
  item: NavItem;
  active: boolean;
  onClick: () => void;
}): ReactElement {
  const Icon = item.icon;
  return (
    <button
      type="button"
      aria-current={active ? 'page' : undefined}
      onClick={onClick}
      style={{
        width: 54,
        height: 52,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 3,
        borderRadius: tokens.radiusControl,
        border: 'none',
        background: active ? tokens.accentSoft : 'transparent',
        color: active ? tokens.colorPrimary : tokens.textSecondary,
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(event) => {
        if (!active) event.currentTarget.style.background = tokens.bgElevated;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.background = active ? tokens.accentSoft : 'transparent';
      }}
    >
      <Icon style={{ fontSize: tokens.fontHeading }} />
      <span style={{ fontSize: tokens.fontIcon, fontWeight: active ? 600 : 400 }}>{item.label}</span>
    </button>
  );
}
```

> 原 `AppLayout.tsx:93` 的 `borderRadius: tokens.fontIcon` 是把字号 token（`'10px'`）当圆角用——本文件已换成 `tokens.radiusControl`（8）。原 `:49` 的 `gap: 6` 是 DSS §1.2 禁止的非栅格值，换成 `tokens.spaceSm`（8）；`:51` 的 `paddingTop: 12` 换成 `tokens.spaceMd`（12，值不变）。

- [ ] **Step 8: 跑测试确认通过**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/components/layout/__tests__/Rail.test.tsx src/app/__tests__/navItems.test.ts`
Expected: PASS —— `Test Files  2 passed (2)`，`Tests  16 passed (16)`。

- [ ] **Step 9: `AppLayout.tsx` 换成渲染 `<Rail />`**

`desktop/src/components/layout/AppLayout.tsx` 整文件替换为：

```tsx
/** 应用壳：自定义标题栏 + 导轨 + 内容 + 底部状态栏。 */
import { Outlet } from 'react-router-dom';
import { tokens } from '../../styles/theme';
import { Rail } from './Rail';
import { StatusBar } from './StatusBar';
import { TitleBar } from './TitleBar';

export function AppLayout() {
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <TitleBar />
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <Rail />
        <main
          style={{
            flex: 1,
            minWidth: 0,
            overflowY: 'auto',
            padding: `${String(tokens.spaceXl)} ${String(tokens.space2xl)}`,
          }}
        >
          <Outlet />
        </main>
      </div>
      <StatusBar />
    </div>
  );
}
```

> 原 `:29` 的 `padding: '22px 28px'` 是 DSS §1.2 明令禁止的非栅格值（「禁止出现 10/14/18/22 等非栅格值」）。换成最近的栅格值：上下 `tokens.spaceXl`（20）、左右 `tokens.space2xl`（24）。内容区因此左右各窄 4px、上下各窄 2px——这是有意的，DSS 是视觉真相源，本计划不为其开例外。

- [ ] **Step 10: 成品页页头与导轨标签对齐**

`desktop/src/features/works/WorksPage.tsx` 三处（同一个提交里改，标签与页面不得各说各话）：

1. `:63` `title="作品库"` → `title="成品库"`
2. `:64` `` chip={`共 ${String(works?.length ?? 0)} 个`} `` → `` chip={`共 ${String(works?.length ?? 0)} 条`} ``（§4.5 全篇用"条"计成片）
3. `:72` `<Empty description="还没有完成的成片——去项目里生成并导出第一个作品吧" />` → `<Empty description="还没有成片——到项目的出片页提交第一次出片" />`

`:65` 的 `desc="全部项目制作完成的成片；点击卡片可预览"` **本任务不动**：它描述的预览面（`:105-110` 的 `<video controls autoPlay>`）今天真实存在，是否保留属 P-3.3 的待裁决项（拆分文件 §8.4）。

- [ ] **Step 11: 跑三件套**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  8 passed (8)`，`Tests  32 passed (32)`（原 16 + navItems 9 + Rail 7）。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: 零输出、退出码 0。若报 `react-refresh/only-export-components`，说明 `Rail.tsx` 除 `Rail` 外还导出了别的符号——本文件只应导出 `Rail`。

- [ ] **Step 12: 提交**

```bash
cd /d/PersonProjects/DramaClip
git add desktop/src/app/navItems.ts desktop/src/app/__tests__/navItems.test.ts desktop/src/components/layout/Rail.tsx desktop/src/components/layout/__tests__/Rail.test.tsx desktop/src/components/layout/AppLayout.tsx desktop/src/features/works/WorksPage.tsx
git commit -m "feat(nav): 导轨清单化并分两组，修子路径全线失高亮，作品改称成品"
```

---

## Task 2: 路由表清单化 + 三方一致性守卫

规格 §2.2 统计过 `/models` 那次更名有「实测触点 **12 处 / 6 文件**」，还点名两处会**静默**失效（`EnginesPage.tsx:99` 的 pathname 正则、`EnvPanel.tsx:107` 被拼成 URL 的 `key`）。本片不新增改名，但要把"改名再发生一次时不会静默漏"变成机器可查的：导轨清单、路由清单、`router.tsx` 的 `path`/`to` 字面量三方必须一致。

顺手把重定向表数据化，并把 `LegacyModelTabRedirect`（`router.tsx:35-38`）泛化为参数保持型重定向——P-3.2 要加的 `/projects/:id/analysis` → `/drama/:id/analysis` 与 `/projects/:id/produce` → `/drama/:id/produce` 是同一个形状，届时只需往表里追加两行。旧组件同期删除，不留暗的（§2.2「一次性切换」）。

**Files:**
- Create: `desktop/src/app/routes.ts`
- Create: `desktop/src/app/__tests__/iaContract.test.ts`
- Modify: `desktop/src/app/router.tsx`（整文件替换）
- Modify: `desktop/src/components/layout/TitleBar.tsx:10,175`

- [ ] **Step 1: 写失败测试——一致性守卫**

`desktop/src/app/__tests__/iaContract.test.ts`：

```ts
// @vitest-environment node
/** 信息架构一致性守卫：导轨 ↔ 路由清单 ↔ router.tsx 的字面量三方必须一致。
 *
 * 读源文件而不是反射 JSX，是因为 JSX 在测试里无法枚举。手法沿用本仓既有先例
 * src/__tests__/contract.test.ts（读 protocol/schemas/*.json 比对 METHOD_NAMES）。
 *
 * 它拦的是规格 §2.2 吃过的那类亏：改名漏一处触点，界面不报错，只是静默失去
 * 高亮或跳错页（EnginesPage.tsx:99 的 pathname 正则、EnvPanel.tsx:107 被拼成 URL 的 key）。
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { NAV_ITEMS } from '../navItems';
import {
  DETAIL_ROUTES,
  LEGACY_PARAM_REDIRECTS,
  LEGACY_REDIRECTS,
  TOP_LEVEL_ROUTES,
  dramaEntryPath,
  dramaProducePath,
} from '../routes';

const here = fileURLToPath(new URL('.', import.meta.url));
const ROUTER_SOURCE = readFileSync(new URL('../router.tsx', `file://${here}`).pathname.replace(/^\/([A-Za-z]:)/, '$1'), 'utf8');

/** 取出源文件里某个 JSX 属性的全部字面量值。 */
function literalsIn(source: string, attribute: string): string[] {
  const pattern = new RegExp(`${attribute}="([^"]+)"`, 'g');
  return [...source.matchAll(pattern)].map((match) => match[1] ?? '');
}

describe('信息架构一致性', () => {
  it('确实读到了 router.tsx（防止路径解析静默失败导致守卫空转）', () => {
    expect(ROUTER_SOURCE).toContain('HashRouter');
    expect(literalsIn(ROUTER_SOURCE, 'path').length).toBeGreaterThan(5);
  });

  it('导轨项与顶层路由是同一个集合（双向）', () => {
    expect(new Set(NAV_ITEMS.map((item) => item.path))).toEqual(new Set(TOP_LEVEL_ROUTES));
  });

  it('router.tsx 的每个 path 字面量都已登记', () => {
    const known = new Set<string>([...TOP_LEVEL_ROUTES, ...DETAIL_ROUTES, '*']);
    for (const literal of literalsIn(ROUTER_SOURCE, 'path')) {
      expect(known.has(literal), `router.tsx 有未登记的路由：${literal}`).toBe(true);
    }
  });

  it('router.tsx 的每个 to 字面量都是顶层路由', () => {
    const known = new Set<string>(TOP_LEVEL_ROUTES);
    for (const literal of literalsIn(ROUTER_SOURCE, 'to')) {
      expect(known.has(literal), `router.tsx 重定向到未登记的路由：${literal}`).toBe(true);
    }
  });

  it('静态重定向表的目标都存在，且不是自己指自己', () => {
    const known = new Set<string>(TOP_LEVEL_ROUTES);
    expect(Object.keys(LEGACY_REDIRECTS).length).toBeGreaterThan(0);
    for (const [from, to] of Object.entries(LEGACY_REDIRECTS)) {
      expect(known.has(to), `${from} → ${to}：目标不是顶层路由`).toBe(true);
      expect(from).not.toBe(to);
    }
  });

  it('保参重定向表的目标存在，且参数名逐一对应', () => {
    const known = new Set<string>(TOP_LEVEL_ROUTES);
    for (const entry of LEGACY_PARAM_REDIRECTS) {
      const base = entry.to.replace(/\/:\w+$/, '');
      expect(known.has(base), `${entry.from} → ${entry.to}：目标基路径不是顶层路由`).toBe(true);
      const fromParams = [...entry.from.matchAll(/:(\w+)/g)].map((match) => match[1]);
      const toParams = [...entry.to.matchAll(/:(\w+)/g)].map((match) => match[1]);
      expect(toParams, '保参重定向的参数名必须逐一对应').toEqual(fromParams);
      expect(fromParams.length).toBeGreaterThan(0);
    }
  });

  it('单剧入口与出片页都指向已登记的详情路由', () => {
    const sample = dramaEntryPath('abc123');
    expect(sample).toBe('/projects/abc123/analysis');
    expect(dramaProducePath('abc123')).toBe('/projects/abc123/produce');
    for (const path of [sample, dramaProducePath('abc123')]) {
      expect(DETAIL_ROUTES.some((route) => route.endsWith(path.slice(path.lastIndexOf('/'))))).toBe(true);
    }
  });

  it('三份清单内部都没有重复', () => {
    expect(new Set(TOP_LEVEL_ROUTES).size).toBe(TOP_LEVEL_ROUTES.length);
    expect(new Set(DETAIL_ROUTES).size).toBe(DETAIL_ROUTES.length);
    const froms = LEGACY_PARAM_REDIRECTS.map((entry) => entry.from);
    expect(new Set(froms).size).toBe(froms.length);
  });
});
```

> `ROUTER_SOURCE` 那行的路径拼接在 Windows 上很脆（`URL.pathname` 会给出 `/D:/…`）。**落地时改用与 `src/__tests__/contract.test.ts:10` 完全相同的既有写法**，那是本仓已经跑通的形式：
>
> ```ts
> import path from 'node:path';
> const ROUTER_SOURCE = readFileSync(
>   path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', 'router.tsx'),
>   'utf8',
> );
> ```
>
> 并在 import 区补 `import path from 'node:path';`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/app/__tests__/iaContract.test.ts`
Expected: FAIL —— 形如 `Error: Failed to load url ../routes`。

- [ ] **Step 3: 写 `routes.ts`**

`desktop/src/app/routes.ts`：

```ts
/** 路由清单：与 navItems.ts 一起构成信息架构的两份数据真相源。
 *
 * router.tsx 的 JSX 保持字面量（可读性优先），一致性由 __tests__/iaContract.test.ts
 * 扫源文件保证。重定向表则真的被 router.tsx 消费——加一条旧路径 = 追加一行数据。
 *
 * 一次性切换，不做新旧并存灰度（规格 §2.2）：重定向只留一跳，旧组件同期删除，
 * 不留"看起来做了其实没做"的暗组件。
 */

/** 顶层路由：每条都必须有一个导轨项，反之亦然。 */
export const TOP_LEVEL_ROUTES = ['/', '/projects', '/works', '/engines', '/settings'] as const;

/** 详情路由：从属于某个顶层路由，不单独出现在导轨上，但导轨高亮要覆盖它们。 */
export const DETAIL_ROUTES = [
  '/projects/:projectId/analysis',
  '/projects/:projectId/produce',
  '/engines/:tab',
] as const;

/** 旧路径 → 新路径（无参数，静态一跳）。 */
export const LEGACY_REDIRECTS: Readonly<Record<string, string>> = {
  '/models': '/engines',
};

/** 旧路径 → 新路径（需保住路径参数，由 LegacyParamRedirect 逐段代入）。
 *
 * P-3.2 合并剧空间时往这里追加两行即可：
 *   { from: '/projects/:projectId/analysis', to: '/drama/:projectId/analysis' }
 *   { from: '/projects/:projectId/produce',  to: '/drama/:projectId/produce' }
 * 形状与 /models/:tab 完全一致，所以本片就把它泛化掉，不留第二个专用组件。
 */
export const LEGACY_PARAM_REDIRECTS: readonly { from: string; to: string }[] = [
  { from: '/models/:tab', to: '/engines/:tab' },
];

/** 单剧入口。今天进分析页；P-3.2 合并为剧空间后只改这一处。
 *
 * 集中在本模块而不是各处硬写，一是因为改名时能一次改完，
 * 二是因为 features/analysis/ 属另一位工程师，本片无权改它内部的 navigate 调用。
 */
export function dramaEntryPath(projectId: string): string {
  return `/projects/${projectId}/analysis`;
}

/** 单剧出片页。 */
export function dramaProducePath(projectId: string): string {
  return `/projects/${projectId}/produce`;
}
```

- [ ] **Step 4: `router.tsx` 消费重定向表**

`desktop/src/app/router.tsx` 整文件替换为：

```tsx
import { HashRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import { App } from './App';
import { HomePage } from '../features/home/HomePage';
import { ProjectsPage } from '../features/project/ProjectsPage';
import { WorkbenchPage } from '../features/analysis/WorkbenchPage';
import { ProductionPage } from '../features/narration/ProductionPage';
import { EnginesPage } from '../features/engines/EnginesPage';
import { SettingsPage } from '../features/settings/SettingsPage';
import { WorksPage } from '../features/works/WorksPage';
import { LEGACY_PARAM_REDIRECTS, LEGACY_REDIRECTS } from './routes';

/** 路由表（docs/desktop/01 §1、规格 §2.2）。
 *
 * 这里的 path/to 字面量必须在 routes.ts 登记，否则 __tests__/iaContract.test.ts 会红。
 * 这道守卫拦的是"改名漏一处触点、界面不报错只是静默跳错"这一类缺陷
 * （规格 §2.2 实测过一次：12 处触点 / 6 文件，其中两处漏了不会报错只会静默失效）。
 * 重定向由 routes.ts 的表驱动，加一条旧路径不必改本文件。
 */
export function Router() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/works" element={<WorksPage />} />
          <Route path="/engines" element={<EnginesPage />} />
          <Route path="/engines/:tab" element={<EnginesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/projects/:projectId/analysis" element={<WorkbenchPage />} />
          <Route path="/projects/:projectId/produce" element={<ProductionPage />} />
          {Object.entries(LEGACY_REDIRECTS).map(([from, to]) => (
            <Route key={from} path={from} element={<Navigate to={to} replace />} />
          ))}
          {LEGACY_PARAM_REDIRECTS.map((entry) => (
            <Route
              key={entry.from}
              path={entry.from}
              element={<LegacyParamRedirect to={entry.to} />}
            />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

/** 旧版深链保住路径参数后转新路由（规格 §2.2：含 :tab 深链保住 tab）。
 *
 * 缺参不可能发生——React Router 只在 :tab 真有值时才匹配到本路由。真缺了就退化成
 * 不含该段的路径，绝不把 ":tab" 原样拼进 URL（那会变成一个 404 的字面量地址）。
 */
function LegacyParamRedirect({ to }: { to: string }) {
  const params = useParams();
  const filled = to.replace(/:(\w+)/g, (_match, name: string) => params[name] ?? '');
  const clean = filled.endsWith('/') ? filled.slice(0, -1) : filled;
  return <Navigate to={clean === '' ? '/' : clean} replace />;
}
```

- [ ] **Step 5: `TitleBar.tsx` 的搜索结果改走 `dramaEntryPath`**

`desktop/src/components/layout/TitleBar.tsx`：

1. import 区加 `import { dramaEntryPath } from '../../app/routes';`
2. `:175` 的 `onPick(`/projects/${item.id}/analysis`);` → `onPick(dramaEntryPath(item.id));`
3. `:10` 的 `const onProjectArea = location.pathname.startsWith('/projects');` **保持不变**——`/projects` 前缀今天仍是单剧详情的真实前缀；P-3.2 改名时这一行与 `routes.ts` 一起改。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/app/__tests__/iaContract.test.ts`
Expected: PASS —— `✓ src/app/__tests__/iaContract.test.ts (8 tests)`，`Tests  8 passed (8)`。

- [ ] **Step 7: 变异检查（守卫最怕永远绿）**

逐条手工破坏、跑测试必须变红、按字节改回后绿：

1. `routes.ts` 的 `TOP_LEVEL_ROUTES` 里 `'/works'` 改成 `'/films'` → 用例「导轨项与顶层路由是同一个集合」必须红。
2. `router.tsx` 临时加一行 `<Route path="/ghost" element={<WorksPage />} />` → 用例「router.tsx 的每个 path 字面量都已登记」必须红，报错文本含 `未登记的路由：/ghost`。
3. `LEGACY_REDIRECTS` 改成 `{ '/models': '/engine' }`（少一个 s）→ 用例「静态重定向表的目标都存在」必须红。
4. `LEGACY_PARAM_REDIRECTS` 改成 `[{ from: '/models/:tab', to: '/engines/:id' }]` → 用例「保参重定向表的目标存在，且参数名逐一对应」必须红。
5. `dramaEntryPath` 的返回改成 `'/nope/' + projectId` → 用例「单剧入口与出片页都指向已登记的详情路由」必须红。
6. 把 `iaContract.test.ts` 里的 `ROUTER_SOURCE` 指向一个不存在的文件 → 用例「确实读到了 router.tsx」必须红（这条用例存在的唯一目的就是防路径解析静默失败）。

Run（每轮）: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/app/__tests__/iaContract.test.ts`

- [ ] **Step 8: 跑三件套**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  9 passed (9)`，`Tests  40 passed (40)`。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: 零输出、退出码 0。

- [ ] **Step 9: 提交**

```bash
cd /d/PersonProjects/DramaClip
git add desktop/src/app/routes.ts desktop/src/app/__tests__/iaContract.test.ts desktop/src/app/router.tsx desktop/src/components/layout/TitleBar.tsx
git commit -m "feat(routes): 路由表清单化，重定向表驱动，加三方一致性守卫"
```

---

## Task 3: 假文案清零 + 永久门禁

界面上今天有**三处**承诺 P-1.5 已经取消的降级：

| 位置 | 原文 | 为什么是假话 |
|---|---|---|
| `desktop/src/features/home/useTodos.ts:32` | `LLM 未配置：文案将使用关键词降级（引擎中心可配置端点）` | P-1.5 之后解说文案**无模板兜底**，未配置即抛 `LlmUnavailable`（P-1.5 计划 Task 3 Step 4、Task 5 Step 4）。操盘手照这句话提交，得到的是七个解说模式**逐条失败**，不是一版能看的片 |
| `desktop/src/features/engines/LlmTab.tsx:13` | `未配置时剧情与文案生成自动降级为关键词模式。` | 同上。且它把**分析层**（`semantic/conflict.py`、`genre.py` 的关键词打分，§3.3.1 允许级、必须可见）与**解说文案**（禁止级、抛错）混成一句话——这正是 §3.3 要拆开的两件事 |
| `desktop/src/features/engines/OverviewTab.tsx:74` | `'未配置（关键词降级）'` | 同上 |

规格 §4.1 点名要删的三条（「导入短剧后自动预筛」「短剧素材也可以拖进来」「AI 自动预筛与全量分析」）已在 correctness 计划 Phase C 改口，实测 `desktop/src` grep `拖进来` / `自动预筛` 均 **0 命中**（`HomePage.tsx:104` 现为「选择一个方式开始，或选择素材所在文件夹」，`StartCards.tsx:25` 现为「逐集转写与冲突分析」）。本任务把**这一整类**（未兑现能力 / 已取消的降级 / 合规红线词）钉成源码扫描门禁，此后任何切片再引入都当场红——这是 §9.5「无任何界面文案描述未实装的能力」唯一能自动化的部分。

**Files:**
- Create: `desktop/src/__tests__/copyTruth.test.ts`
- Modify: `desktop/src/features/engines/LlmTab.tsx`（整文件替换）
- Modify: `desktop/src/features/engines/OverviewTab.tsx:70-76`
- Modify: `desktop/src/features/home/useTodos.ts:29-35`

- [ ] **Step 1: 写失败测试——被禁词扫描**

`desktop/src/__tests__/copyTruth.test.ts`：

```ts
// @vitest-environment node
/** 界面文案真值门禁（规格 §9.5「无任何界面文案描述未实装的能力」+ 合规红线）。
 *
 * 扫源码而不是扫渲染结果：文案可能藏在任何分支里，只有全量扫才拦得住；
 * 而且这类缺陷的代价是"操盘手照假话操作、白等一晚"，值得一条永久门禁。
 *
 * 排除测试文件——本文件的 BANNED 列表自己就含这些词，
 * 且测试里的字符串不是界面文案。对测试文件放宽与 eslint.config.mjs:76 同源。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC_DIR = path.resolve(fileURLToPath(new URL('..', import.meta.url)));

const BANNED: readonly { phrase: string; reason: string }[] = [
  // P-1.5 之后解说文案没有模板兜底：未配 LLM 时七个解说模式逐条失败并抛错。
  // 分析层的关键词打分是另一回事（§3.3.1 允许级、界面必须可见），两者不得混为一谈。
  { phrase: '关键词降级', reason: '解说文案不降级；未配置编剧模型即逐条失败' },
  { phrase: '降级为关键词', reason: '同上' },
  { phrase: '自动降级', reason: '同上' },
  // 全库无 dataTransfer，拖放导入从未实现（规格 §4.1「拖放为纯虚构，删」）。
  { phrase: '拖进来', reason: '拖放导入不存在' },
  { phrase: '拖拽导入', reason: '拖放导入不存在' },
  { phrase: '拖动文件', reason: '拖放导入不存在' },
  // 合规红线：185 万判例之下，消重/抗比对绝不得作为用户可见卖点文案。
  { phrase: '消重', reason: '合规红线：不得出现在用户可见文案里' },
  { phrase: '抗比对', reason: '合规红线：不得出现在用户可见文案里' },
  { phrase: '去重', reason: '合规红线：同上' },
  { phrase: '绕过平台', reason: '合规红线：§4.8 要求声明本软件不提供绕过平台原创性检测的能力' },
  // 未兑现的承诺挂在界面上就是长期谎言（correctness 计划 C4 的措辞纪律：
  // 一律用「当前未生效」+ 实际固定值，不得写"即将支持"）。
  { phrase: '即将支持', reason: '未兑现承诺不得上界面；要写就写实际固定值' },
  { phrase: '敬请期待', reason: '同上' },
  { phrase: '后续版本', reason: '同上——LlmTab.tsx:19 今天就有这句，本任务一并改口' },
];

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__') continue;
      out.push(...sourceFiles(full));
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry)) continue;
    if (entry.endsWith('.test.ts') || entry.endsWith('.test.tsx')) continue;
    out.push(full);
  }
  return out;
}

describe('界面文案真值门禁', () => {
  const files = sourceFiles(SRC_DIR);

  it('确实扫到了源文件（防止 glob 静默失配导致门禁空转）', () => {
    expect(files.length).toBeGreaterThan(20);
    expect(files.some((file) => file.endsWith('HomePage.tsx'))).toBe(true);
  });

  for (const { phrase, reason } of BANNED) {
    it(`不得出现「${phrase}」`, () => {
      const hits: string[] = [];
      for (const file of files) {
        const lines = readFileSync(file, 'utf8').split('\n');
        lines.forEach((line, index) => {
          if (line.includes(phrase)) hits.push(`${path.relative(SRC_DIR, file)}:${String(index + 1)}`);
        });
      }
      expect(hits, `${phrase} —— ${reason}。命中：${hits.join(', ')}`).toEqual([]);
    });
  }
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/__tests__/copyTruth.test.ts`
Expected: FAIL —— `Tests  10 passed | 4 failed (14)`。四条红的用例与命中位置：
- `不得出现「关键词降级」` → `features/home/useTodos.ts:32`、`features/engines/OverviewTab.tsx:74`
- `不得出现「降级为关键词」` → `features/engines/LlmTab.tsx:13`
- `不得出现「自动降级」` → `features/engines/LlmTab.tsx:13`
- `不得出现「后续版本」` → `features/engines/LlmTab.tsx:19`

其余 10 条（含「确实扫到了源文件」）PASS。

> 若红的条数或命中位置与上表不符，说明这两个文件已被他人改过。**按当前文件内容重新核对再往下走，不要跳过、也不要照抄本计划的行号。**

- [ ] **Step 3: 改口 `LlmTab.tsx`**

`desktop/src/features/engines/LlmTab.tsx` 整文件替换为：

```tsx
/** LLM 引擎：OpenAI 兼容端点多实例（云端服务或本地 Ollama/LM Studio 同协议），单启用。 */
import { PageSection } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { CloudConfigSection } from './CloudConfigSection';

/** 文案 LLM tab：端点配置列表（启用中的配置镜像至 llm.* 设置，即时生效）。 */
export function LlmTab({ onChanged }: { onChanged: () => void }): React.ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <PageSection title="云端 / 本地端点（OpenAI 兼容）">
        <div
          style={{
            fontSize: tokens.fontCaption,
            color: tokens.textTertiary,
            marginBottom: tokens.spaceMd,
          }}
        >
          可添加多个端点按需启用：云端填 DashScope 等兼容服务；本地 Ollama 填
          http://127.0.0.1:11434/v1、LM Studio 填其服务地址。
        </div>
        <UnconfiguredNotice />
        <CloudConfigSection domain="llm" onChanged={onChanged} />
      </PageSection>
      <PageSection title="本地大模型">
        <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
          不内置本地推理。要跑本地模型，请经 Ollama / LM Studio 的 OpenAI
          兼容端点接入——添加一条配置、填本地服务地址即可。
        </div>
      </PageSection>
    </div>
  );
}

/** 未配置的真实后果（规格 §3.3.1、§4.2 空态第②步）。
 *
 * 这里必须把两层分开说，因为它们的裁决相反：分析层的关键词打分是**允许级**降级
 * （影响选段不影响文案，界面必须可见）；解说文案没有兜底，是**禁止级**——
 * 未配置就抛错，失败粒度是单条方案。混成一句"自动降级"会让操盘手以为总能出片。
 * 颜色用 status/warning（§3.2：注意/降级/过期用金），不用钩子红。
 */
function UnconfiguredNotice(): React.ReactElement {
  return (
    <div
      style={{
        fontSize: tokens.fontCaption,
        lineHeight: '19px',
        color: tokens.colorWarning,
        border: `1px solid ${tokens.colorWarning}66`,
        background: `${tokens.colorWarning}14`,
        borderRadius: tokens.radiusControl,
        padding: `${String(tokens.spaceSm)} ${String(tokens.spaceMd)}`,
        marginBottom: tokens.spaceMd,
      }}
    >
      未配置时：分析（转写、冲突打分）改用关键词打分，仍可跑完；但解说文案必须由编剧模型产出，
      没有兜底——七个解说模式的每条方案都会失败并在任务里说明原因。
      仅「纯原片剪辑」「字幕金句流」不依赖编剧模型。
    </div>
  );
}
```

> 原 `:9` 的 `gap: 14` 与 `:11` 的 `marginBottom: 14` 是 DSS §1.2 禁止的非栅格值，已换成 `tokens.spaceMd`（12）。`lineHeight: '19px'` 沿用本仓既有写法（`EnvPanel.tsx:166` 同值），DSS 未对行高立 token，不在此处新造。

- [ ] **Step 4: 改口 `OverviewTab.tsx`**

`desktop/src/features/engines/OverviewTab.tsx:70-76` 的 LLM 那一格替换为：

```tsx
    {
      name: '文案 LLM',
      tab: 'llm',
      icon: '✍️',
      // 未配置的真实后果是"解说模式不可用"，不是"降级出片"（规格 §3.3.1 禁止级）。
      current: llmReady ? `云端 · ${settings['llm.model'] ?? ''}` : '未配置 · 解说模式不可用',
      ok: llmReady,
    },
```

- [ ] **Step 5: 改口 `useTodos.ts`**

`desktop/src/features/home/useTodos.ts:29-35` 的整块 `if (!llmConfigured) { … }` 替换为：

```ts
    if (!llmConfigured) {
      items.push({
        key: 'llm',
        // P-1.5 之后解说文案无模板兜底：未配置即逐条失败（规格 §3.3.1）。
        // 严重度也从 info 提到 warning——它不再是"少一点智能"，是"七个模式出不了片"。
        text: 'LLM 未配置：七个解说模式不会产出方案（引擎中心可配置端点）',
        severity: 'warning',
      });
    }
```

> 本文件在 Task 7 会被整体删除并由 `todos.ts` 取代。这里先改口是为了让本任务的门禁能**绿着提交**——不留一个红的中间提交。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/__tests__/copyTruth.test.ts`
Expected: PASS —— `✓ src/__tests__/copyTruth.test.ts (14 tests)`，`Tests  14 passed (14)`。

- [ ] **Step 7: 变异检查**

把 `OverviewTab.tsx` 的 `'未配置 · 解说模式不可用'` 临时改回 `'未配置（关键词降级）'`。
Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/__tests__/copyTruth.test.ts`
Expected: FAIL —— `不得出现「关键词降级」` 红，报错文本含 `features/engines/OverviewTab.tsx:74`。改回后重跑至 PASS。

再验一次门禁不是空转：把 `copyTruth.test.ts` 的 `sourceFiles(SRC_DIR)` 改成 `sourceFiles(path.join(SRC_DIR, 'nope'))`。
Run: 同上。Expected: FAIL —— `确实扫到了源文件` 红（`readdirSync` 抛 `ENOENT` 也算红）。改回。

- [ ] **Step 8: 跑三件套**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  10 passed (10)`，`Tests  54 passed (54)`。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: 零输出、退出码 0。

- [ ] **Step 9: 提交**

```bash
cd /d/PersonProjects/DramaClip
git add desktop/src/__tests__/copyTruth.test.ts desktop/src/features/engines/LlmTab.tsx desktop/src/features/engines/OverviewTab.tsx desktop/src/features/home/useTodos.ts
git commit -m "fix(copy): 清掉三处已取消的降级承诺，界面文案真值门禁落地"
```

---

## Task 4: 接通 `jobs.list` + 待办从"通知"变成"可执行动作"

P-1 交付了 `jobs.list/get/cancel`、`export.retry`、`project.update_settings` 五个方法（`protocol/ts/index.ts:338,341-343,320`，服务端 `api/jobs.py:21-24` 已注册），**桌面端至今零消费者**——实测 `desktop/src` grep `jobs\.` 无命中。任务在飞而界面无感，这正是规格 §1 第三条判断（「模型到底看到了什么……不能静默」）要治的病。本片先让它出现在工作台的芯片与待办上；完整的队列页属 P-2.5。

今天的 `useTodos.ts` 只有三个来源，全是"系统就绪度"，**没有一条来自这部剧的实际状态**，而且用 AntD `Alert` 渲染，点不动。§4.1 的要求是「待办必须是可执行动作，不是通知：每条右侧 ghost 链接直达处理位置」。

**`ref_id` 语义异构是本任务的核心约束**（实测 `service/dramaclip/api/*.py` 的 `job_store.create` 调用点）：

| `type` | `ref_id` 指向 | 调用点 |
|---|---|---|
| `prescreen` | project_id | `api/analysis.py:65` |
| `analysis` | project_id | `api/analysis.py:134` |
| `semantic` | **episode_id** | `api/analysis.py:223` |
| `narration` | project_id | `api/narration.py:74` |
| `produce` | project_id | `api/narration.py:327` |
| `export` | **export_id** | `api/export.py:79` |
| `model_download` | **model_id** | `api/models.py:65` |

所以本片只消费 `ref_id` 已知为 project_id 的四类——它们都有可跳的页面。`export`/`model_download`/`semantic` 三类失败**不进待办**：解析 `export_id → project_id` 要额外 RPC，而它们正确的落点是队列页（P-2.5）。这是"缺席而非假控件"。

> **⚠️ 与并行 P-2 的一处已知冲突（读到 `docs/superpowers/plans/2026-09-12-p2-plan-render-split.md` 后登记）**：P-2 的 Step 3 会把 `protocol/schemas/jobs.json` 的 `JobInfo.type` 词表从 `prescreen|analysis|semantic|narration|produce|export|model_download` 改成 **去掉 `produce`**（理由：该 job 类型随 `narration.produce` 一起消失，`plan_variants` 复用既有的 `narration` 类型）。
> 本计划有三处列了 `produce`：`todos.ts` 的 `PROJECT_JOB_TARGETS`、`HomePage.tsx` 的 `PROJECT_JOB_TYPES`、`protocol/ts/index.ts` 里 `JobInfo.type` 的 docstring。
> **处置：三处都照本计划写，保留 `produce`。** 理由是它在今天的服务端真实存在（`api/narration.py:327`），删掉它会让 P-2 落地之前的失败任务失去待办；而 P-2 落地后它退化成一个永不命中的 map 键——**不会造成错误行为，只会多一行死数据**。
> **谁后落地谁负责收口**：P-2 后落地则由 P-2 删掉这三处的 `produce`（P-2 的计划今天没列这三处，需要补）；P-3.1 后落地则本任务直接把三处的 `produce` 去掉。**执行 Task 4 前先 `grep -n "produce" docs/superpowers/plans/2026-09-12-p2-plan-render-split.md` 确认 P-2 是否已合入 `main`/本分支**，并据此二选一，不要两边都留。

**为什么不逐剧调 `analysis.results` 拿失败集号**：它是 N+1，且每次会把该剧**全部 ASR 段**拖回来（`api/analysis.py:288` 每集 `json.loads(record["asr_segments"])`）。50 部剧 × 100 集就是这个页面的首屏代价，而 §9.7 的规模实测**今天连脚本都没有**。改走 `jobs.list` 反而更好：一次 RPC，而且**带 `error` 原文**——`analysis.results` 构造的 entry（`api/analysis.py:301-310`）里根本没有 `error` 键，尽管 `protocol/ts/index.ts:124` 声明了 `error?: string`。集级失败粒度（§3.3 行 4 的「卡在：第 3、17、44 集失败」）归 P-3.2，那时才有阶段聚合可用。

**Files:**
- Modify: `protocol/ts/index.ts`（在 `AnalysisJobStatus`（`:142-149`）之后、`AnalysisResults`（`:151`）之前插入）
- Modify: `desktop/src/services/client.ts`（import 块 + 在 `analysisApi`（`:86-103`）之后插入 `jobsApi`）
- Create: `desktop/src/features/home/todos.ts`
- Create: `desktop/src/features/home/__tests__/todos.test.ts`

- [ ] **Step 1: 写失败测试——待办派生规则**

`desktop/src/features/home/__tests__/todos.test.ts`：

```ts
/** 工作台待办派生规则（规格 §4.1「待办必须是可执行动作，不是通知」）。
 *
 * 纯函数测试：不渲染 React、不发 RPC，所以"哪些状态该变成待办、每条跳哪"
 * 这条业务规则可以被穷举。装载在 useWorkbench.ts。
 */
import { describe, expect, it } from 'vitest';
import type { ModelInfo, Project, WorkItem } from '@dramaclip/protocol';
import { buildDramas, buildTodos, type DramaState, type FailedJob, type TodoInput } from '../todos';

const NOW = 1_760_000_000_000;
const DAY = 86_400_000;

function model(over: Partial<ModelInfo> = {}): ModelInfo {
  return {
    model_id: 'asr-small',
    kind: 'asr',
    engine: 'faster_whisper',
    repo_id: 'Systran/faster-whisper-small',
    name: 'Whisper small',
    required: true,
    status: 'installed',
    ...over,
  };
}

function drama(over: Partial<DramaState> & { id: string }): DramaState {
  return {
    name: `剧${over.id}`,
    episodeCount: 10,
    workCount: 0,
    createdAtMs: NOW - 10 * DAY,
    ...over,
  };
}

function job(over: Partial<FailedJob> = {}): FailedJob {
  return { id: 'j1', type: 'analysis', refId: 'p1', error: 'ffmpeg 退出码 1', ...over };
}

function base(over: Partial<TodoInput> = {}): TodoInput {
  return {
    serviceDown: false,
    models: [model()],
    llmConfigured: true,
    dramas: [],
    failedJobs: [],
    serverTimeMs: NOW,
    ...over,
  };
}

const keys = (input: TodoInput) => buildTodos(input).map((item) => item.key);

describe('buildTodos：全就绪时无待办', () => {
  it('一切正常返回空数组', () => {
    expect(buildTodos(base())).toEqual([]);
  });
});

describe('buildTodos：系统就绪度', () => {
  it('服务不可用给出重启动作，而不是一个跳不动的链接', () => {
    const items = buildTodos(base({ serviceDown: true }));
    expect(items[0]?.severity).toBe('error');
    expect(items[0]?.action).toEqual({ kind: 'restart-service', label: '重启服务' });
  });

  it('缺必需模型 → 去下载 /engines/asr', () => {
    const items = buildTodos(base({ models: [model({ status: 'missing' })] }));
    expect(items[0]?.action).toEqual({ kind: 'navigate', label: '去下载', path: '/engines/asr' });
    expect(items[0]?.text).toContain('Whisper small');
  });

  it('models 为 null（还没取回来）不得谎报缺模型', () => {
    expect(keys(base({ models: null }))).toEqual([]);
  });

  it('未配编剧模型是 error 级，文案不得承诺降级，且说清哪两个模式例外', () => {
    const items = buildTodos(base({ llmConfigured: false }));
    expect(items[0]?.severity).toBe('error');
    expect(items[0]?.text).toContain('七个解说模式不会产出方案');
    expect(items[0]?.detail).toContain('纯原片剪辑');
    expect(items[0]?.detail).toContain('关键词打分');
    expect(items[0]?.action).toEqual({ kind: 'navigate', label: '去配置', path: '/engines/llm' });
  });
});

describe('buildTodos：失败任务（jobs.list，P-1 交付后的第一个消费者）', () => {
  it('analysis 失败 → 跳分析页，error 原文不截断', () => {
    const long = `编剧未产出合格文案（full-1, full-2）：${'x'.repeat(200)}`;
    const items = buildTodos(base({ failedJobs: [job({ error: long })] }));
    expect(items[0]?.action).toEqual({
      kind: 'navigate',
      label: '去处理',
      path: '/projects/p1/analysis',
    });
    expect(items[0]?.detail).toBe(long);
  });

  it('produce 失败 → 跳出片页', () => {
    const items = buildTodos(base({ failedJobs: [job({ id: 'j2', type: 'produce' })] }));
    expect(items[0]?.action).toEqual({
      kind: 'navigate',
      label: '去处理',
      path: '/projects/p1/produce',
    });
  });

  it('带上剧名；ref_id 对不上任何剧时如实说未知，不静默丢掉', () => {
    const items = buildTodos(
      base({
        dramas: [drama({ id: 'p1', name: '逆袭开局', workCount: 2 })],
        failedJobs: [job({ refId: 'p9' })],
      }),
    );
    expect(items[0]?.text).toContain('未知剧');
  });

  it('ref_id 不是 project_id 的三类不进待办（没有落点，宁缺勿假）', () => {
    const items = buildTodos(
      base({
        failedJobs: [
          job({ id: 'a', type: 'export', refId: 'e1' }),
          job({ id: 'b', type: 'model_download', refId: 'm1' }),
          job({ id: 'c', type: 'semantic', refId: 'ep1' }),
        ],
      }),
    );
    expect(items).toEqual([]);
  });

  it('ref_id 为空时不进待办，不拼出 /projects//analysis 这种坏地址', () => {
    expect(buildTodos(base({ failedJobs: [job({ refId: null })] }))).toEqual([]);
    expect(buildTodos(base({ failedJobs: [job({ refId: '' })] }))).toEqual([]);
  });
});

describe('buildTodos：有素材无成品的剧', () => {
  it('素材就位超过阈值天数仍无成品 → 去出片', () => {
    const items = buildTodos(base({ dramas: [drama({ id: 'p1' })] }));
    expect(items[0]?.severity).toBe('info');
    expect(items[0]?.action).toEqual({
      kind: 'navigate',
      label: '去出片',
      path: '/projects/p1/produce',
    });
    expect(items[0]?.text).toContain('10 集已就位');
  });

  it('新建的剧不算停滞：阈值天数内不催', () => {
    expect(buildTodos(base({ dramas: [drama({ id: 'p1', createdAtMs: NOW - DAY })] }))).toEqual([]);
  });

  it('已有成品的剧不催', () => {
    expect(buildTodos(base({ dramas: [drama({ id: 'p1', workCount: 3 })] }))).toEqual([]);
  });

  it('没有集的剧不催（还没投料，不是停滞）', () => {
    expect(buildTodos(base({ dramas: [drama({ id: 'p1', episodeCount: 0 })] }))).toEqual([]);
  });

  it('停滞剧最多列 5 条，最旧优先，余数写进末条文案', () => {
    const dramas = Array.from({ length: 8 }, (_, index) =>
      drama({ id: `p${String(index)}`, createdAtMs: NOW - (20 - index) * DAY }),
    );
    const items = buildTodos(base({ dramas })).filter((item) => item.key.startsWith('stalled-'));
    expect(items).toHaveLength(5);
    expect(items[0]?.key).toBe('stalled-p0');
    expect(items[4]?.text).toContain('另有 3 部');
  });
});

describe('buildTodos：排序与稳定性', () => {
  it('error 在 warning 前、warning 在 info 前', () => {
    const items = buildTodos(
      base({
        llmConfigured: false,
        models: [model({ status: 'missing' })],
        dramas: [drama({ id: 'p1', episodeCount: 5, createdAtMs: NOW - 30 * DAY })],
      }),
    );
    expect(items.map((item) => item.severity)).toEqual(['error', 'warning', 'info']);
  });

  it('同严重度内顺序稳定（不得随对象遍历顺序漂移）', () => {
    const input = base({
      failedJobs: [job({ id: 'j1' }), job({ id: 'j2', type: 'produce' }), job({ id: 'j3' })],
    });
    expect(keys(input)).toEqual(['job-j1', 'job-j2', 'job-j3']);
    expect(keys(input)).toEqual(keys(input));
  });
});

describe('buildDramas：把两个既有接口的返回拼成剧状态', () => {
  it('按 project_id 归集成片数，没有成品的记 0', () => {
    const projects: Project[] = [
      { id: 'p1', name: 'A', source_path: '/a', status: 'ready', created_at: NOW, episode_count: 10, settings: {} },
      { id: 'p2', name: 'B', source_path: '/b', status: 'ready', created_at: NOW, episode_count: 4, settings: {} },
    ];
    const works: WorkItem[] = [
      { id: 'w1', project_id: 'p1', project_name: 'A', output_path: '/o/1.mp4', completed_at: NOW },
      { id: 'w2', project_id: 'p1', project_name: 'A', output_path: '/o/2.mp4', completed_at: NOW },
    ];
    expect(buildDramas(projects, works)).toEqual([
      { id: 'p1', name: 'A', episodeCount: 10, workCount: 2, createdAtMs: NOW },
      { id: 'p2', name: 'B', episodeCount: 4, workCount: 0, createdAtMs: NOW },
    ]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/todos.test.ts`
Expected: FAIL —— 形如 `Error: Failed to load url ../todos`。

- [ ] **Step 3: 同步 `JobInfo` 类型（还 P-1 的欠账）**

`protocol/ts/index.ts`：在 `AnalysisJobStatus`（`:142-149`）之后、`/** ---- narration / export 命名空间（W4）---- */`（`:158`）之前插入：

```ts
/** ---- jobs 命名空间（P-1 地基：任务查询与取消）----
 *
 * 权威源是 protocol/schemas/jobs.json 的 x-models.JobInfo。P-1 只把方法名加进了
 * METHOD_NAMES（见下方 jobs.list / jobs.get / jobs.cancel），类型漏同步——
 * 本块补的是既有契约，不新增任何方法，所以 contract.test.ts 必须照旧绿。
 */

/** jobs.status 的枚举，与 jobs.json 的 enum 逐字一致。 */
export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface JobInfo {
  readonly id: string;
  /** 任务类型。schema 未枚举，实测取值见 service/dramaclip/api/*.py 的 job_store.create：
   *  prescreen | analysis | semantic | narration | produce | export | model_download */
  readonly type: string;
  /** 语义随 type 而变：analysis/prescreen/narration/produce → project_id；
   *  export → export_id；model_download → model_id；semantic → episode_id。
   *  消费前必须先判 type，否则会把 export_id 当成 project_id 拼出跳错剧的地址。 */
  readonly ref_id?: string | null;
  readonly status: JobStatus;
  readonly progress: number;
  /** 人读阶段文案，队列页显示。 */
  readonly label?: string | null;
  readonly error?: string | null;
  /** 毫秒。与 jobs.list 返回的 server_time_ms 同量纲（service 侧一律 _now_ms）。 */
  readonly created_at: number;
  readonly updated_at: number;
}

/** jobs.list 返回体。server_time_ms 用于 ETA 外推——用服务端时钟，避免本机时钟偏移。 */
export interface JobsListResult {
  readonly jobs: JobInfo[];
  readonly server_time_ms: number;
}
```

**不新增 `METHOD_NAMES` 条目**：`jobs.list`/`jobs.get`/`jobs.cancel` 已在 `:341-343`。

- [ ] **Step 4: `client.ts` 加 `jobsApi`**

`desktop/src/services/client.ts`：

1. 顶部 `import type { … } from '@dramaclip/protocol';` 块里加入 `JobsListResult`（按现有字母序插在 `HealthResult` 之后）。
2. 在 `analysisApi`（`:86-103`）之后、`/** 作品库：跨项目已完成成片。 */`（`:105`）之前插入：

```ts
/** 任务查询（P-1 地基）。本文件是 jobs.* 的第一个消费者。
 *
 * 只暴露 list：get/cancel 的落点是队列页（P-2.5），本片没有它们的用武之地。
 * 提前加进来就是无人调用的死导出——见 restartService 的前例（本文件 :34，
 * 至今零消费者；Task 7 给它接上唯一合理的使用者）。
 */
export const jobsApi = {
  /** 一次取回最近 limit 条（含终态），运行中与失败在调用方分流。
   *  schema 的 limit 上限是 200（protocol/schemas/jobs.json），超了服务端钳回来
   *  （api/jobs.py:31 双向钳制）。 */
  list: (limit = 50): Promise<JobsListResult> => rpc<JobsListResult>('jobs.list', { limit }),
} as const;
```

- [ ] **Step 5: 写 `todos.ts`**

`desktop/src/features/home/todos.ts`：

```ts
/** 工作台待办派生（规格 §4.1）：状态 → 可执行动作。
 *
 * 纯函数，不碰 RPC——装载在 useWorkbench.ts。这样"哪些状态该变成待办、每条跳哪"
 * 可以被单测穷举，而不必渲染 React。
 *
 * 三条取舍写在这里，因为它们都是"宁缺勿假"的具体应用：
 * 1. 只收有落点的来源。ref_id 不是 project_id 的失败任务（export / model_download /
 *    semantic）不进待办——它们正确的落点是队列页（P-2.5），今天没有页面可跳。
 * 2. 「已分析未规划」这个来源缺席，它要 project.list 的阶段聚合（P-2）。
 * 3. error 原文一律不截断，放在 detail 里由视图层用 title 呈现——
 *    P-1.5 之后失败原因就是最值钱的信息（规格 §4.4「这页的第一能力不是进度条，
 *    是这条为什么没出片」，工作台先承接一部分）。
 */
import type { ModelInfo, Project, WorkItem } from '@dramaclip/protocol';

export type TodoAction =
  | { readonly kind: 'navigate'; readonly label: string; readonly path: string }
  | { readonly kind: 'restart-service'; readonly label: string };

export interface TodoItem {
  readonly key: string;
  /** 一行结论。 */
  readonly text: string;
  /** 完整原因，可为空串。视图层用 title 呈现，数据层不截断。 */
  readonly detail: string;
  readonly severity: 'error' | 'warning' | 'info';
  readonly action: TodoAction;
}

/** 一部剧的最小状态。全部来自 project.list 与 export.list_works，不需要新接口。 */
export interface DramaState {
  readonly id: string;
  readonly name: string;
  readonly episodeCount: number;
  readonly workCount: number;
  readonly createdAtMs: number;
}

/** jobs.list 里的失败行，已挑出本模块关心的字段。 */
export interface FailedJob {
  readonly id: string;
  readonly type: string;
  readonly refId: string | null;
  readonly error: string;
}

export interface TodoInput {
  readonly serviceDown: boolean;
  /** null = 还没取回来。此时不得报"缺模型"——那会把加载中说成故障。 */
  readonly models: readonly ModelInfo[] | null;
  readonly llmConfigured: boolean;
  readonly dramas: readonly DramaState[];
  readonly failedJobs: readonly FailedJob[];
  /** 服务端时钟（jobs.list 的 server_time_ms）。停滞判定用它而不是 Date.now()。 */
  readonly serverTimeMs: number;
}

const SEVERITY_ORDER: Readonly<Record<TodoItem['severity'], number>> = {
  error: 0,
  warning: 1,
  info: 2,
};

/** ref_id 可直接当 project_id 用的任务类型 → 处理位置。
 *  不在表里的类型（export / model_download / semantic）的 ref_id 指向别的实体，
 *  拼进 /projects/<id>/… 会得到一个跳错剧的地址，所以一律不收。 */
const PROJECT_JOB_TARGETS: Readonly<Record<string, { label: string; suffix: 'analysis' | 'produce' }>> = {
  prescreen: { label: '预筛', suffix: 'analysis' },
  analysis: { label: '分析', suffix: 'analysis' },
  narration: { label: '编排', suffix: 'produce' },
  produce: { label: '出片', suffix: 'produce' },
};

/** 「有素材无成品」的停滞阈值。低于它就只是"刚建的新剧"，催它是噪音。 */
const STALL_THRESHOLD_MS = 3 * 86_400_000;
/** 停滞剧最多列几条。完整视图属剧库页的筛选（规格 §4.2），归 P-3.2。 */
const STALL_MAX = 5;

export function buildDramas(projects: readonly Project[], works: readonly WorkItem[]): DramaState[] {
  const counts = new Map<string, number>();
  for (const work of works) {
    counts.set(work.project_id, (counts.get(work.project_id) ?? 0) + 1);
  }
  return projects.map((project) => ({
    id: project.id,
    name: project.name,
    episodeCount: project.episode_count,
    workCount: counts.get(project.id) ?? 0,
    createdAtMs: project.created_at,
  }));
}

export function buildTodos(input: TodoInput): TodoItem[] {
  const items: TodoItem[] = [];

  if (input.serviceDown) {
    items.push({
      key: 'service-down',
      text: 'Python 服务不可用，所有功能暂停',
      detail: '',
      severity: 'error',
      // 没有页面可跳：重启服务是唯一处理动作。顺带给 client.ts:34 那个
      // 零消费者的 restartService 接上唯一合理的使用者（见 TodoList.tsx）。
      action: { kind: 'restart-service', label: '重启服务' },
    });
  }

  const missing = (input.models ?? []).filter((item) => item.required && item.status !== 'installed');
  if (missing.length > 0) {
    items.push({
      key: 'model-missing',
      text: `必需模型未安装：${missing.map((item) => item.name).join('、')}`,
      detail: '',
      severity: 'warning',
      action: { kind: 'navigate', label: '去下载', path: '/engines/asr' },
    });
  }

  if (!input.llmConfigured) {
    items.push({
      key: 'llm-unconfigured',
      text: '编剧模型未配置：七个解说模式不会产出方案',
      // P-1.5 之后解说文案无模板兜底，未配置即逐条失败（规格 §3.3.1 禁止级）。
      // 分析层的关键词打分是允许级降级、界面必须可见——两者必须分开说，
      // 混成一句"自动降级"就是 Task 3 刚清掉的那句假话。
      detail:
        '分析（转写、冲突打分）仍可运行，改用关键词打分；解说文案必须由编剧模型产出，' +
        '没有兜底，未配置时七个解说模式的每条方案都会失败并在任务里说明原因。' +
        '仅「纯原片剪辑」「字幕金句流」不依赖编剧模型。',
      severity: 'error',
      action: { kind: 'navigate', label: '去配置', path: '/engines/llm' },
    });
  }

  for (const job of input.failedJobs) {
    const target = PROJECT_JOB_TARGETS[job.type];
    if (target === undefined || job.refId === null || job.refId === '') continue;
    const name = input.dramas.find((drama) => drama.id === job.refId)?.name ?? '未知剧';
    items.push({
      key: `job-${job.id}`,
      text: `《${name}》${target.label}任务失败`,
      detail: job.error,
      severity: 'error',
      action: { kind: 'navigate', label: '去处理', path: `/projects/${job.refId}/${target.suffix}` },
    });
  }

  items.push(...stalledDramas(input));

  // 稳定排序：先按严重度，同严重度内保持 push 顺序（Array.prototype.sort 自 ES2019
  // 起保证稳定）。不这么写的话待办顺序会随对象遍历顺序漂移，看起来像随机。
  return items.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
}

/** 有素材、无成品、且已就位超过阈值天数 = 停滞（规格 §4.1 待办来源第四项）。
 *
 * "长期停滞"里的时间维度用 project.created_at 近似：没有阶段聚合（P-2）之前，
 * 这是唯一不需要新接口就能拿到的时间戳。它会把"建了很久但一直没投料"的剧也算进来，
 * 这是已知的近似——P-3.2 拿到 stage 聚合后应改为按阶段时间戳判定。
 */
function stalledDramas(input: TodoInput): TodoItem[] {
  const stalled = input.dramas
    .filter(
      (drama) =>
        drama.episodeCount > 0 &&
        drama.workCount === 0 &&
        input.serverTimeMs - drama.createdAtMs >= STALL_THRESHOLD_MS,
    )
    .sort((a, b) => a.createdAtMs - b.createdAtMs);
  const overflow = stalled.length - STALL_MAX;
  return stalled.slice(0, STALL_MAX).map((drama, index) => ({
    key: `stalled-${drama.id}`,
    text:
      `《${drama.name}》${String(drama.episodeCount)} 集已就位，还没有成品` +
      (overflow > 0 && index === STALL_MAX - 1 ? `（另有 ${String(overflow)} 部同样停滞）` : ''),
    detail: '',
    severity: 'info' as const,
    action: { kind: 'navigate' as const, label: '去出片', path: `/projects/${drama.id}/produce` },
  }));
}
```

> `stalledDramas` 返回类型标成 `TodoItem[]`，所以 `severity` / `action.kind` 上的 `as const` 其实多余（上下文已定型）。**落地时删掉这两个 `as const`**，让 `tsc` 的上下文推断生效；若删掉后报类型错，说明 `stalledDramas` 的返回类型注解漏了，补回去而不是加 `as const`。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/todos.test.ts`
Expected: PASS —— `✓ src/features/home/__tests__/todos.test.ts (18 tests)`，`Tests  18 passed (18)`。

- [ ] **Step 7: 变异检查**

逐条破坏、必须变红、按字节改回后绿：

1. `PROJECT_JOB_TARGETS` 加一行 `export: { label: '导出', suffix: 'produce' }` → 用例「ref_id 不是 project_id 的三类不进待办」必须红。**这条变异正是该用例存在的理由**：`export` 的 `ref_id` 是 export_id，拼进 `/projects/` 会跳错剧。
2. `if (target === undefined || job.refId === null || job.refId === '')` 去掉 `|| job.refId === ''` → 用例「ref_id 为空时不进待办」必须红。
3. `STALL_THRESHOLD_MS` 改成 `0` → 用例「新建的剧不算停滞」必须红。
4. `items.sort(...)` 整行删掉 → 用例「error 在 warning 前」必须红。
5. `stalledDramas` 的 `.slice(0, STALL_MAX)` 删掉 → 用例「停滞剧最多列 5 条」必须红。
6. `(input.models ?? []).filter(...)` 改成 `(input.models ?? [{ required: true, status: 'missing' } as ModelInfo]).filter(...)` → 用例「models 为 null 不得谎报缺模型」必须红（这条守的是"加载中不得说成故障"）。

Run（每轮）: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/todos.test.ts`

- [ ] **Step 8: 跑三件套 + 契约回归**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  11 passed (11)`，`Tests  72 passed (72)`。

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/__tests__/contract.test.ts`
Expected: PASS（1 test）。这条既有契约测试断言 `METHOD_NAMES` 与 `protocol/schemas/*.json` 的 `x-methods` 集合相等。本任务只加 interface 不加方法名，所以它必须照旧绿；**若它红了，说明误改了 `METHOD_NAMES`，回退那一处**。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: 零输出、退出码 0。

- [ ] **Step 9: 提交**

```bash
cd /d/PersonProjects/DramaClip
git add protocol/ts/index.ts desktop/src/services/client.ts desktop/src/features/home/todos.ts desktop/src/features/home/__tests__/todos.test.ts
git commit -m "feat(home): 接通 jobs.list，待办派生成带落点的可执行动作"
```

---

## Task 5: 三统计芯片与 ETA 外推

§4.1 的三芯片是「剧数 / 在跑条数+ETA / 成品数+周增」，取代今天的四芯片（项目/剧集/已分析/已导出，`HomePage.tsx:90-95`）——那四个是数据库计数，回答不了"今天该干什么"。

两个数据真值问题必须在本任务解决，不能带进界面：

1. **`project.dashboard_summary` 的 `export_count` 不是成品数。** `service/dramaclip/infra/storage/repos/projects.py:158` 是 `SELECT COUNT(*) FROM export_jobs`，**不带状态过滤**——失败与 pending 的导出记录都会被算成成品。所以本片的成品数改从 `export.list_works` 计（那条查询带 `WHERE e.status = ? AND e.output_path IS NOT NULL`，`repos/exports.py:145`）。修 `summary()` 要改 `DashboardSummary` 的形状 = 动 `protocol/`，与 P-2 撞车，**已登记给 P-3.3**（拆分文件 §3）。
2. **`list_works` 有扫描上限，超出不得假报精确值。** `service/dramaclip/api/export.py:161` 是 `int(params.get("limit", 60))`，服务端不钳制。本片取 `WORKS_SCAN_LIMIT = 1000`；当返回条数**等于**上限时说明可能被截断，芯片显示 `1000+`、周增显示为不可用（`null`）——一个被截断的样本算出来的"本周 +3"是假数字，而 §9.5 管的不只是能力描述。

**ETA 的口径**：线性外推 `elapsed / progress × (100 − progress)`，取全部在跑任务里最慢的一条（用户问的是"还要等多久全跑完"）。进度不是时间的线性函数（转写慢、拼接快），所以它是**量级提示**——注释与界面措辞都不得把它写成承诺，界面用「预计还需」不用「剩余」。`progress < 5` 时不外推，直接显示「预计中…」，此时外推误差大于信息量。时钟用 `jobs.list` 返回的 `server_time_ms`，不用 `Date.now()`（这正是该字段存在的理由）。

**Files:**
- Create: `desktop/src/features/home/stats.ts`
- Create: `desktop/src/features/home/__tests__/stats.test.ts`

- [ ] **Step 1: 写失败测试**

`desktop/src/features/home/__tests__/stats.test.ts`：

```ts
/** 三统计芯片派生（规格 §4.1）。
 *
 * ETA 是线性外推的量级提示、不是承诺——所以每个退化边界（进度 0、进度 100、
 * 无在跑、elapsed=0、时钟回拨）都要有明确行为，绝不输出 NaN / Infinity / 负数。
 */
import { describe, expect, it } from 'vitest';
import type { WorkItem } from '@dramaclip/protocol';
import { MIN_ETA_PROGRESS, WORKS_SCAN_LIMIT, buildStats, etaLabel, type StatsInput } from '../stats';

const NOW = 1_760_000_000_000;
const MINUTE = 60_000;
const DAY = 86_400_000;

function work(id: string, completedAt: number | undefined): WorkItem {
  return {
    id,
    project_id: 'p1',
    project_name: 'A',
    output_path: `/o/${id}.mp4`,
    completed_at: completedAt,
  };
}

function input(over: Partial<StatsInput> = {}): StatsInput {
  return { dramaCount: 0, running: [], serverTimeMs: NOW, works: [], ...over };
}

describe('etaLabel', () => {
  it('无在跑任务返回空串（视图层据此不渲染那一行）', () => {
    expect(etaLabel([], NOW)).toBe('');
  });

  it('进度低于阈值不外推，直说预计中', () => {
    expect(MIN_ETA_PROGRESS).toBe(5);
    expect(etaLabel([{ id: 'j', progress: 4, createdAtMs: NOW - 10 * MINUTE }], NOW)).toBe('预计中…');
  });

  it('刚入队（elapsed=0）不得输出"预计还需 0 分"这种假精确值', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW }], NOW)).toBe('预计中…');
  });

  it('线性外推：跑了一半、已用 10 分钟 → 还需 10 分钟', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW - 10 * MINUTE }], NOW)).toBe('预计还需 10 分');
  });

  it('多条在跑取最慢的一条', () => {
    const label = etaLabel(
      [
        { id: 'a', progress: 90, createdAtMs: NOW - 10 * MINUTE },
        { id: 'b', progress: 10, createdAtMs: NOW - 10 * MINUTE },
      ],
      NOW,
    );
    expect(label).toBe('预计还需 90 分');
  });

  it('混着一条已跑满的残留行不影响其余任务的外推', () => {
    const label = etaLabel(
      [
        { id: 'done', progress: 100, createdAtMs: NOW - 5 * MINUTE },
        { id: 'live', progress: 50, createdAtMs: NOW - 10 * MINUTE },
      ],
      NOW,
    );
    expect(label).toBe('预计还需 10 分');
  });

  it('超过一小时换成小时+分', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW - 90 * MINUTE }], NOW)).toBe(
      '预计还需 1 小时 30 分',
    );
  });

  it('整小时不带"0 分"尾巴', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW - 120 * MINUTE }], NOW)).toBe('预计还需 2 小时');
  });

  it('时钟回拨（server 时间早于 created_at）按 0 处理，不输出负 ETA', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW + 10 * MINUTE }], NOW)).toBe('预计中…');
  });
});

describe('buildStats', () => {
  it('剧数与在跑条数直取，ETA 随行', () => {
    const stats = buildStats(
      input({ dramaCount: 12, running: [{ id: 'j', progress: 50, createdAtMs: NOW - MINUTE }] }),
    );
    expect(stats.dramaCount).toBe(12);
    expect(stats.runningCount).toBe(1);
    expect(stats.runningEtaLabel).toBe('预计还需 1 分');
  });

  it('成品数 = 传入的成片段数', () => {
    expect(buildStats(input({ works: [work('w1', NOW), work('w2', NOW - DAY)] })).workCount).toBe(2);
  });

  it('周增只数近 7 天完成的', () => {
    const works = [work('w1', NOW - DAY), work('w2', NOW - 8 * DAY), work('w3', undefined)];
    const stats = buildStats(input({ works }));
    expect(stats.workCount).toBe(3);
    expect(stats.workWeekDelta).toBe(1);
  });

  it('completed_at 缺失的片不计入周增，但计入总数', () => {
    const stats = buildStats(input({ works: [work('w1', undefined)] }));
    expect(stats.workCount).toBe(1);
    expect(stats.workWeekDelta).toBe(0);
  });

  it('条数触到扫描上限即判溢出：总数标 N+，周增判为不可用', () => {
    const works = Array.from({ length: WORKS_SCAN_LIMIT }, (_, index) => work(`w${String(index)}`, NOW));
    const stats = buildStats(input({ works }));
    expect(stats.workCountOverflow).toBe(true);
    expect(stats.workCount).toBe(WORKS_SCAN_LIMIT);
    expect(stats.workWeekDelta).toBeNull();
  });

  it('差一条到上限不算溢出', () => {
    const works = Array.from({ length: WORKS_SCAN_LIMIT - 1 }, (_, index) => work(`w${String(index)}`, NOW));
    const stats = buildStats(input({ works }));
    expect(stats.workCountOverflow).toBe(false);
    expect(stats.workWeekDelta).toBe(WORKS_SCAN_LIMIT - 1);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/stats.test.ts`
Expected: FAIL —— 形如 `Error: Failed to load url ../stats`。

- [ ] **Step 3: 写 `stats.ts`**

`desktop/src/features/home/stats.ts`：

```ts
/** 工作台三统计芯片派生（规格 §4.1）：剧数 / 在跑条数+ETA / 成品数+周增。
 *
 * 两处刻意不用现成数据源，理由都是"那个数不是它名字说的东西"：
 * 1. 成品数不用 project.dashboard_summary 的 export_count——那是
 *    `SELECT COUNT(*) FROM export_jobs`（service/…/repos/projects.py:158），不带状态过滤，
 *    失败与 pending 都会被算成成品。改用 export.list_works 的条数，那条查询带
 *    `status='completed' AND output_path IS NOT NULL`。修 summary() 要动 protocol，
 *    已登记给 P-3.3。
 * 2. 周增不用 Date.now()——用 jobs.list 返回的 server_time_ms，同一把尺子量
 *    completed_at（服务端一律 _now_ms，同为毫秒）。
 */
import type { WorkItem } from '@dramaclip/protocol';

/** 低于此进度不外推：此时 elapsed/progress 的误差大于它的信息量。 */
export const MIN_ETA_PROGRESS = 5;

/** 成品扫描上限。触到即判溢出，芯片显示 N+ 而不是假精确值。
 *  服务端不钳制 limit（api/export.py:161 直接 int(params.get("limit", 60))）。 */
export const WORKS_SCAN_LIMIT = 1000;

const MS_PER_MINUTE = 60_000;
const MS_PER_WEEK = 7 * 86_400_000;

export interface RunningJob {
  readonly id: string;
  readonly progress: number;
  readonly createdAtMs: number;
}

export interface StatsInput {
  readonly dramaCount: number;
  readonly running: readonly RunningJob[];
  readonly serverTimeMs: number;
  readonly works: readonly WorkItem[];
}

export interface WorkbenchStats {
  readonly dramaCount: number;
  readonly runningCount: number;
  /** '' = 不显示 ETA 那一行（无在跑任务）。 */
  readonly runningEtaLabel: string;
  readonly workCount: number;
  readonly workCountOverflow: boolean;
  /** null = 样本被截断，算不出可信的周增。视图层显示 '—' 而不是一个假数字。 */
  readonly workWeekDelta: number | null;
}

/** 线性外推的剩余时间文案。
 *
 * 进度不是时间的线性函数（转写慢、拼接快），所以这是量级提示而非承诺——
 * 界面措辞用「预计还需」，不用「剩余」。取最慢的一条，因为用户问的是
 * "还要等多久全跑完"。任何算不出可信值的边界都退回 '预计中…' 或 ''，
 * 绝不输出 NaN / Infinity / 负数 / "0 分"。
 *
 * progress >= 100 的行**跳过**而不是判"预计中"：它可能是尚未被清扫的终态残留
 * （P-1.5 计划 Task 4 实测修正记过这类永生行），拿它把整块 ETA 打成"预计中"
 * 等于让一条死行掩盖其余活行的真实进度。
 */
export function etaLabel(running: readonly RunningJob[], nowMs: number): string {
  let worst: number | null = null;
  for (const job of running) {
    if (job.progress >= 100) continue;
    if (job.progress < MIN_ETA_PROGRESS) return '预计中…';
    const elapsed = Math.max(nowMs - job.createdAtMs, 0);
    if (elapsed === 0) return '预计中…';
    const remain = (elapsed / job.progress) * (100 - job.progress);
    worst = worst === null ? remain : Math.max(worst, remain);
  }
  if (worst === null) return '';
  const minutes = Math.max(Math.round(worst / MS_PER_MINUTE), 1);
  if (minutes < 60) return `预计还需 ${String(minutes)} 分`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `预计还需 ${String(hours)} 小时` : `预计还需 ${String(hours)} 小时 ${String(rest)} 分`;
}

export function buildStats(input: StatsInput): WorkbenchStats {
  const overflow = input.works.length >= WORKS_SCAN_LIMIT;
  const weekStart = input.serverTimeMs - MS_PER_WEEK;
  let weekDelta = 0;
  for (const work of input.works) {
    if (work.completed_at !== undefined && work.completed_at >= weekStart) weekDelta += 1;
  }
  return {
    dramaCount: input.dramaCount,
    runningCount: input.running.length,
    runningEtaLabel: etaLabel(input.running, input.serverTimeMs),
    workCount: input.works.length,
    workCountOverflow: overflow,
    workWeekDelta: overflow ? null : weekDelta,
  };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/stats.test.ts`
Expected: PASS —— `✓ src/features/home/__tests__/stats.test.ts (15 tests)`，`Tests  15 passed (15)`。

- [ ] **Step 5: 变异检查**

1. `WORKS_SCAN_LIMIT` 改成 `10_000` → 用例「条数触到扫描上限即判溢出」必须红（它同时断言常量与实际行为一致）。
2. `buildStats` 里 `overflow ? null : weekDelta` 改成 `weekDelta` → 用例「触到上限时周增判为不可用」必须红。
3. `etaLabel` 的 `Math.max(nowMs - job.createdAtMs, 0)` 去掉 `Math.max` → 用例「时钟回拨」必须红。
4. `etaLabel` 的 `if (worst === null) return ''` 改成 `return '预计中…'` → 用例「无在跑任务返回空串」必须红。
5. `etaLabel` 的 `if (job.progress >= 100) continue;` 改成 `return '预计中…'` → 用例「混着一条已跑满的残留行不影响其余任务的外推」必须红。
6. `Math.max(Math.round(worst / MS_PER_MINUTE), 1)` 去掉 `Math.max` → 用例「线性外推：跑了一半、已用 10 分钟」仍绿，但把该用例的 `createdAtMs` 临时改成 `NOW - 1` 后必须输出 `预计还需 1 分` 而不是 `预计还需 0 分`；改回。

Run（每轮）: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/stats.test.ts`

- [ ] **Step 6: 跑三件套 + 提交**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  12 passed (12)`，`Tests  87 passed (87)`。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: 零输出、退出码 0。

```bash
cd /d/PersonProjects/DramaClip
git add desktop/src/features/home/stats.ts desktop/src/features/home/__tests__/stats.test.ts
git commit -m "feat(home): 三统计芯片派生，ETA 线性外推并守住全部退化边界"
```

---

## Task 6: 装载器与两个视图组件

**Files:**
- Create: `desktop/src/features/home/useWorkbench.ts`
- Create: `desktop/src/features/home/TodoList.tsx`
- Create: `desktop/src/features/home/StatChips.tsx`
- Create: `desktop/src/features/home/__tests__/TodoList.test.tsx`
- Create: `desktop/src/features/home/__tests__/StatChips.test.tsx`

- [ ] **Step 1: 写失败测试——待办列表渲染**

`desktop/src/features/home/__tests__/TodoList.test.tsx`：

```tsx
/** 待办列表：每条必须带一个能点的动作（规格 §4.1「不是通知」）。 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TodoList } from '../TodoList';
import type { TodoItem } from '../todos';

afterEach(cleanup);

function item(over: Partial<TodoItem> = {}): TodoItem {
  return {
    key: 'k1',
    text: '《A》分析任务失败',
    detail: 'ffmpeg 退出码 1',
    severity: 'error',
    action: { kind: 'navigate', label: '去处理', path: '/projects/p1/analysis' },
    ...over,
  };
}

function renderList(items: readonly TodoItem[]) {
  const onNavigate = vi.fn();
  const onRestartService = vi.fn();
  render(
    <MemoryRouter>
      <TodoList items={items} onNavigate={onNavigate} onRestartService={onRestartService} />
    </MemoryRouter>,
  );
  return { onNavigate, onRestartService };
}

function dotBackground(container: HTMLElement): string {
  const dot = container.querySelector('[data-testid="severity-dot"]');
  expect(dot).not.toBeNull();
  return (dot as HTMLElement).style.background;
}

describe('TodoList', () => {
  it('空数组整块不渲染（缺席而非空壳，也不写"暂无待办"）', () => {
    const { container } = renderList([]);
    expect(container.querySelector('section')).toBeNull();
    expect(screen.queryByText('今日待办')).toBeNull();
  });

  it('每条渲染结论文本与动作按钮，并在 extra 里报条数', () => {
    renderList([item(), item({ key: 'k2', text: '第二条' })]);
    expect(screen.getByText('《A》分析任务失败')).toBeTruthy();
    expect(screen.getByText('第二条')).toBeTruthy();
    expect(screen.getByRole('button', { name: '去处理' })).toBeTruthy();
    expect(screen.getByText('2 条')).toBeTruthy();
  });

  it('navigate 动作点下去带着目标路径回调', () => {
    const { onNavigate } = renderList([item()]);
    screen.getByRole('button', { name: '去处理' }).click();
    expect(onNavigate).toHaveBeenCalledWith('/projects/p1/analysis');
  });

  it('restart-service 动作触发重启回调，不试图导航', () => {
    const { onNavigate, onRestartService } = renderList([
      item({ key: 'svc', action: { kind: 'restart-service', label: '重启服务' } }),
    ]);
    screen.getByRole('button', { name: '重启服务' }).click();
    expect(onRestartService).toHaveBeenCalledTimes(1);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it('detail 非空时挂在 title 上，原文不截断', () => {
    const long = 'x'.repeat(300);
    renderList([item({ detail: long })]);
    expect(screen.getByTitle(long)).toBeTruthy();
  });

  it('detail 为空时不挂空 title', () => {
    const { container } = renderList([item({ detail: '' })]);
    expect(container.querySelector('[title=""]')).toBeNull();
  });

  it('error 用 status/error（#F87171），不用钩子红 #FF4D4F', () => {
    const { container } = renderList([item({ severity: 'error' })]);
    expect(dotBackground(container)).toBe('#F87171');
  });

  it('warning 用 status/warning、info 用 status/info（规格 §3.2）', () => {
    const warning = renderList([item({ severity: 'warning' })]);
    expect(dotBackground(warning.container)).toBe('#FBBF24');
    cleanup();
    const info = renderList([item({ severity: 'info' })]);
    expect(dotBackground(info.container)).toBe('#60A5FA');
  });
});
```

- [ ] **Step 2: 写失败测试——芯片渲染**

`desktop/src/features/home/__tests__/StatChips.test.tsx`：

```tsx
/** 三统计芯片（规格 §4.1）。溢出与不可用必须如实显示，不得给假精确值。 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { StatChips } from '../StatChips';
import type { WorkbenchStats } from '../stats';

afterEach(cleanup);

function stats(over: Partial<WorkbenchStats> = {}): WorkbenchStats {
  return {
    dramaCount: 12,
    runningCount: 3,
    runningEtaLabel: '预计还需 8 分',
    workCount: 45,
    workCountOverflow: false,
    workWeekDelta: 6,
    ...over,
  };
}

describe('StatChips', () => {
  it('恰好三个芯片', () => {
    render(<StatChips stats={stats()} />);
    expect(screen.getAllByTestId('stat-chip')).toHaveLength(3);
  });

  it('三块内容各自可读', () => {
    render(<StatChips stats={stats()} />);
    for (const text of ['12', '部剧', '3', '条在跑', '预计还需 8 分', '45', '条成品', '本周 +6']) {
      expect(screen.getByText(text), `缺 ${text}`).toBeTruthy();
    }
  });

  it('无在跑任务时不渲染 ETA 那一行', () => {
    render(<StatChips stats={stats({ runningCount: 0, runningEtaLabel: '' })} />);
    expect(screen.queryByText(/^预计/)).toBeNull();
  });

  it('溢出时总数带 +，周增显示为不可用', () => {
    render(<StatChips stats={stats({ workCount: 1000, workCountOverflow: true, workWeekDelta: null })} />);
    expect(screen.getByText('1000+')).toBeTruthy();
    expect(screen.getByText('本周 —')).toBeTruthy();
  });

  it('本周零增显示 +0，不隐藏（隐藏会让人以为没算）', () => {
    render(<StatChips stats={stats({ workWeekDelta: 0 })} />);
    expect(screen.getByText('本周 +0')).toBeTruthy();
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/TodoList.test.tsx src/features/home/__tests__/StatChips.test.tsx`
Expected: FAIL —— 形如 `Error: Failed to load url ../TodoList` 与 `… ../StatChips`，`Test Files  2 failed`。

- [ ] **Step 4: 写 `useWorkbench.ts`**

`desktop/src/features/home/useWorkbench.ts`：

```ts
/** 工作台数据装载：一次并发取全，服务就绪前不发请求。
 *
 * "就绪前不发"沿用 HomePage 既有的时序修复（原 :45-48 注释：服务就绪前发起的 RPC
 * 会失败）——否则每次冷启都会打出一串红色 message。
 *
 * 五个数据源全部是既有方法，本片零后端：
 *   project.list · models.list · settings.get（只判 llm.base_url 是否为空）·
 *   export.list_works · jobs.list
 *
 * 不调 project.dashboard_summary：它唯一的用处是 project_count，而 projects.length
 * 就是同一个数（repos/projects.py:153 是 `SELECT COUNT(*) FROM projects`）；
 * 它的 export_count 反而不可用（见 stats.ts 顶部注释）。少一次 RPC。
 *
 * 不调 analysis.results：它按剧逐个取，是 N+1，且每次会把该剧全部 ASR 段拖回来
 * （api/analysis.py:288）。失败任务的 error 原文改从 jobs.list 拿——一次 RPC，
 * 而且 jobs 行里有 error，analysis.results 的 entry 里没有（api/analysis.py:301-310）。
 */
import { useCallback, useEffect, useState } from 'react';
import type { JobInfo, ModelInfo, Project, WorkItem } from '@dramaclip/protocol';
import { jobsApi, listWorks, projectApi, rpc } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { WORKS_SCAN_LIMIT } from './stats';

/** jobs 扫描上限。schema 的 maximum 是 200（protocol/schemas/jobs.json），超了服务端钳回来。 */
export const JOBS_SCAN_LIMIT = 200;

export interface WorkbenchData {
  readonly projects: Project[];
  /** null = 还没取回来或取失败。buildTodos 据此区分"加载中"与"缺模型"。 */
  readonly models: ModelInfo[] | null;
  readonly llmConfigured: boolean;
  readonly jobs: JobInfo[];
  readonly serverTimeMs: number;
  readonly works: WorkItem[];
}

const EMPTY: WorkbenchData = {
  projects: [],
  models: null,
  llmConfigured: false,
  jobs: [],
  serverTimeMs: 0,
  works: [],
};

export interface Workbench {
  readonly data: WorkbenchData;
  readonly ready: boolean;
  readonly reload: () => Promise<void>;
}

export function useWorkbench(): Workbench {
  const serviceState = useUiStore((state) => state.serviceState);
  const [data, setData] = useState<WorkbenchData>(EMPTY);

  const reload = useCallback(async () => {
    const [projects, models, settings, works, jobs] = await Promise.all([
      projectApi.list(),
      rpc<ModelInfo[]>('models.list').catch(() => null),
      rpc<Record<string, string>>('settings.get').catch(() => null),
      listWorks(WORKS_SCAN_LIMIT).catch((): WorkItem[] => []),
      jobsApi.list(JOBS_SCAN_LIMIT).catch(() => null),
    ]);
    setData({
      projects,
      models,
      llmConfigured: (settings?.['llm.base_url'] ?? '') !== '',
      jobs: jobs?.jobs ?? [],
      // 服务端时钟优先：ETA 与周增都要与 created_at/completed_at 同量纲同源
      // （service 侧一律 _now_ms，毫秒）。jobs.list 取不到时退回本机时钟——
      // 那是次优，但比拿 0 当"现在"好（0 会把所有任务算成已跑 56 年）。
      serverTimeMs: jobs?.server_time_ms ?? Date.now(),
      works,
    });
  }, []);

  useEffect(() => {
    if (serviceState === 'ready') void reload();
  }, [reload, serviceState]);

  return { data, ready: serviceState === 'ready', reload };
}
```

- [ ] **Step 5: 写 `TodoList.tsx`**

`desktop/src/features/home/TodoList.tsx`：

```tsx
/** 今日待办：每条 = 状态点 + 一行结论 + 右侧 ghost 动作（规格 §4.1、DSS §3.1/§4.3）。
 *
 * 与被它取代的 TodoCard 的区别不是样式：旧版用 AntD Alert，只能"通知"、点不动。
 * 本版每条必须带一个可执行动作——没有落点的状态不进待办（取舍见 todos.ts 顶部注释）。
 *
 * 行结构复用 mixins.listRow，与环境就绪度行、素材列表行同构（DSS §4.3）。
 * 状态点颜色按 §3.2 色彩纪律：失败 status/error、注意 status/warning、进行中 status/info。
 * #FF4D4F 是钩子语义专用色，本页不得出现。
 *
 * 导航由 onNavigate 注入而不是在组件内 useNavigate：这样它能在 MemoryRouter 之外
 * 也被渲染测试，也让"点了跳哪"这条规则在 todos.ts 里可单测。
 */
import type { ReactElement } from 'react';
import { PageSection } from '../../components/layout/PageKit';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import type { TodoItem } from './todos';

const DOT_COLOR: Readonly<Record<TodoItem['severity'], string>> = {
  error: tokens.colorError,
  warning: tokens.colorWarning,
  info: tokens.colorInfo,
};

export function TodoList({
  items,
  onNavigate,
  onRestartService,
}: {
  items: readonly TodoItem[];
  onNavigate: (path: string) => void;
  onRestartService: () => void;
}): ReactElement | null {
  // 空数组整块不渲染：一个写着"暂无待办"的卡片是噪音，不是信息。
  if (items.length === 0) return null;
  return (
    <PageSection title="今日待办" extra={<span style={mixins.chip()}>{`${String(items.length)} 条`}</span>}>
      <div>
        {items.map((item) => (
          <TodoRow key={item.key} item={item} onNavigate={onNavigate} onRestartService={onRestartService} />
        ))}
      </div>
    </PageSection>
  );
}

function TodoRow({
  item,
  onNavigate,
  onRestartService,
}: {
  item: TodoItem;
  onNavigate: (path: string) => void;
  onRestartService: () => void;
}): ReactElement {
  return (
    <div style={{ ...mixins.listRow(), padding: `${String(tokens.spaceMd)} ${String(tokens.spaceLg)}` }}>
      <span data-testid="severity-dot" style={mixins.statusDot(DOT_COLOR[item.severity])} />
      <span
        title={item.detail === '' ? undefined : item.detail}
        style={{
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: tokens.fontBody,
          color: tokens.textPrimary,
        }}
      >
        {item.text}
      </span>
      <GhostAction item={item} onNavigate={onNavigate} onRestartService={onRestartService} />
    </div>
  );
}

/** ghost = 纯文字主色（DSS §3.1）。它不是按钮层级里的 secondary，所以不用 AntD
 *  Button——"每屏 primary 至多 1 个"这条规矩靠视觉权重就能守住，不必靠组件类型。 */
function GhostAction({
  item,
  onNavigate,
  onRestartService,
}: {
  item: TodoItem;
  onNavigate: (path: string) => void;
  onRestartService: () => void;
}): ReactElement {
  const click = (): void => {
    if (item.action.kind === 'navigate') onNavigate(item.action.path);
    else onRestartService();
  };
  return (
    <button
      type="button"
      onClick={click}
      style={{
        marginLeft: 'auto',
        flexShrink: 0,
        background: 'none',
        border: 'none',
        padding: 0,
        color: tokens.colorPrimary,
        fontSize: tokens.fontCaption,
        cursor: 'pointer',
      }}
    >
      {item.action.label}
    </button>
  );
}
```

- [ ] **Step 6: 写 `StatChips.tsx`**

`desktop/src/features/home/StatChips.tsx`：

```tsx
/** 三统计芯片（规格 §4.1）：剧数 / 在跑条数+ETA / 成品数+周增。
 *
 * 取代旧的四芯片（项目/剧集/已分析/已导出，HomePage.tsx:90-95）——那四个是
 * 数据库计数，回答不了"今天该干什么"。
 * ETA 与周增的措辞按 stats.ts 的口径：一个是量级提示（「预计还需」），
 * 一个在样本被截断时如实显示 '—'。
 */
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';
import type { WorkbenchStats } from './stats';

interface Chip {
  readonly key: string;
  readonly value: string;
  readonly label: string;
  readonly note: string;
}

export function StatChips({ stats }: { stats: WorkbenchStats }): ReactElement {
  const chips: Chip[] = [
    { key: 'dramas', value: String(stats.dramaCount), label: '部剧', note: '' },
    { key: 'running', value: String(stats.runningCount), label: '条在跑', note: stats.runningEtaLabel },
    {
      key: 'works',
      value: stats.workCountOverflow ? `${String(stats.workCount)}+` : String(stats.workCount),
      label: '条成品',
      // 周增不可用（成品数触到扫描上限）时显示 '—'：一个被截断的样本算出来的
      // "本周 +3" 是假数字。零增则显示 +0，隐藏它会让人以为没算。
      note: `本周 ${stats.workWeekDelta === null ? '—' : `+${String(stats.workWeekDelta)}`}`,
    },
  ];
  return (
    <div style={{ display: 'flex', gap: tokens.spaceMd }}>
      {chips.map((chip) => (
        <ChipView key={chip.key} chip={chip} />
      ))}
    </div>
  );
}

function ChipView({ chip }: { chip: Chip }): ReactElement {
  return (
    <div
      data-testid="stat-chip"
      style={{
        flex: 1,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        padding: `${String(tokens.spaceSm)} ${String(tokens.spaceLg)}`,
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
      }}
    >
      <span
        style={{
          fontSize: tokens.fontTitleLg,
          fontWeight: 700,
          lineHeight: '26px',
          color: tokens.textPrimary,
          fontFamily: tokens.fontFamilyMono,
        }}
      >
        {chip.value}
      </span>
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>{chip.label}</span>
      {chip.note !== '' && (
        <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{chip.note}</span>
      )}
    </div>
  );
}
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/TodoList.test.tsx src/features/home/__tests__/StatChips.test.tsx`
Expected: PASS —— `Test Files  2 passed (2)`，`Tests  13 passed (13)`（TodoList 8 + StatChips 5）。

- [ ] **Step 8: 跑三件套 + 提交**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  14 passed (14)`，`Tests  100 passed (100)`。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: 零输出、退出码 0。注意 `max-lines-per-function: 60`——`TodoList` 的三个函数都远低于此限，**不要为了省文件数把它们合并成一个超 60 行的函数**。

```bash
cd /d/PersonProjects/DramaClip
git add desktop/src/features/home/useWorkbench.ts desktop/src/features/home/TodoList.tsx desktop/src/features/home/StatChips.tsx desktop/src/features/home/__tests__/TodoList.test.tsx desktop/src/features/home/__tests__/StatChips.test.tsx
git commit -m "feat(home): 工作台装载器与待办/芯片视图，行结构与环境就绪度同构"
```

---

## Task 7: 建剧动作、继续上次、空态引导

三块新代码，都是 Task 8 重写 `HomePage` 的前置件，所以先落地并各自带测试。

**Files:**
- Create: `desktop/src/features/home/createDrama.ts`
- Create: `desktop/src/stores/lastDrama.ts`
- Create: `desktop/src/features/home/EmptyWorkbench.tsx`
- Create: `desktop/src/features/home/ContinueCard.tsx`
- Create: `desktop/src/features/home/__tests__/createDrama.test.ts`
- Create: `desktop/src/features/home/__tests__/lastDrama.test.ts`
- Create: `desktop/src/features/home/__tests__/EmptyWorkbench.test.tsx`

- [ ] **Step 1: 写失败测试——目录名与取消语义**

`desktop/src/features/home/__tests__/createDrama.test.ts`：

```ts
/** 建剧动作：目录名即剧名（规格 §1「剧名直接取文件夹名即与片单天然对齐，无需手输」），
 *  用户取消不是失败。 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/client', () => ({
  pickFolder: vi.fn(),
  projectApi: { create: vi.fn(), scanEpisodes: vi.fn() },
}));

import { pickFolder, projectApi } from '../../../services/client';
import { createDramaFromFolder, folderName } from '../createDrama';

const mockedPick = vi.mocked(pickFolder);
const mockedCreate = vi.mocked(projectApi.create);
const mockedScan = vi.mocked(projectApi.scanEpisodes);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('folderName', () => {
  it('Windows 反斜杠路径取末段', () => {
    expect(folderName('D:\\BaiduNetdiskDownload\\小小球神不好惹')).toBe('小小球神不好惹');
  });

  it('POSIX 正斜杠路径取末段', () => {
    expect(folderName('/media/drama/逆袭开局')).toBe('逆袭开局');
  });

  it('尾部带分隔符时不得返回空串', () => {
    expect(folderName('D:\\drama\\逆袭开局\\')).toBe('逆袭开局');
    expect(folderName('/media/drama/逆袭开局/')).toBe('逆袭开局');
  });

  it('只有根或空串时给一个可用的兜底名', () => {
    expect(folderName('D:\\')).toBe('新剧');
    expect(folderName('')).toBe('新剧');
  });
});

describe('createDramaFromFolder', () => {
  it('用户取消选择返回 null，且不建项目不扫集', async () => {
    mockedPick.mockResolvedValue(null);
    expect(await createDramaFromFolder()).toBeNull();
    expect(mockedCreate).not.toHaveBeenCalled();
    expect(mockedScan).not.toHaveBeenCalled();
  });

  it('选中目录则以目录名建项目、扫集，并回一个可跳的入口路径', async () => {
    mockedPick.mockResolvedValue('D:\\drama\\逆袭开局');
    mockedCreate.mockResolvedValue({
      id: 'p1',
      name: '逆袭开局',
      source_path: 'D:\\drama\\逆袭开局',
      status: 'created',
      created_at: 1,
      episode_count: 0,
      settings: {},
    });
    mockedScan.mockResolvedValue([]);
    const result = await createDramaFromFolder();
    expect(mockedCreate).toHaveBeenCalledWith('逆袭开局', 'D:\\drama\\逆袭开局');
    expect(mockedScan).toHaveBeenCalledWith('p1');
    expect(result).toEqual({
      projectId: 'p1',
      name: '逆袭开局',
      entryPath: '/projects/p1/analysis',
    });
  });
});
```

- [ ] **Step 2: 写失败测试——本地偏好的读写与坏数据**

`desktop/src/features/home/__tests__/lastDrama.test.ts`：

```ts
/** 「继续上次」的本地偏好：坏数据必须退化成"没有记录"，不得拼出 undefined 路径。 */
import { beforeEach, describe, expect, it } from 'vitest';
import { clearLastDrama, readLastDrama, rememberDrama } from '../../../stores/lastDrama';

const KEY = 'dramaclip.last-drama';

beforeEach(() => {
  window.localStorage.clear();
});

describe('lastDrama', () => {
  it('没写过就是 null', () => {
    expect(readLastDrama()).toBeNull();
  });

  it('写进去能原样读回来', () => {
    rememberDrama('p1', '逆袭开局');
    const read = readLastDrama();
    expect(read?.id).toBe('p1');
    expect(read?.name).toBe('逆袭开局');
    expect(typeof read?.visitedAtMs).toBe('number');
  });

  it('后写的覆盖先写的', () => {
    rememberDrama('p1', 'A');
    rememberDrama('p2', 'B');
    expect(readLastDrama()?.id).toBe('p2');
  });

  it('clear 之后回到 null', () => {
    rememberDrama('p1', 'A');
    clearLastDrama();
    expect(readLastDrama()).toBeNull();
  });

  it('上一版写的或手工改坏的数据一律当没有记录', () => {
    for (const raw of ['not json', '{}', '{"id":"","name":"A","visitedAtMs":1}', '{"id":"p1"}', 'null', '[]']) {
      window.localStorage.setItem(KEY, raw);
      expect(readLastDrama(), raw).toBeNull();
    }
  });
});
```

- [ ] **Step 3: 写失败测试——空态渲染**

`desktop/src/features/home/__tests__/EmptyWorkbench.test.tsx`：

```tsx
/** 无剧时的主区引导（规格 §4.1 空态）。它必须给出唯一那个 primary，
 *  因为有剧时 primary 在 PageHeader 上、空态时不在——两处都放会违反
 *  DSS §3.1「每屏 primary 至多 1 个」。 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EmptyWorkbench } from '../EmptyWorkbench';

afterEach(cleanup);

function renderEmpty() {
  const onCreate = vi.fn();
  render(
    <MemoryRouter>
      <EmptyWorkbench creating={false} onCreate={onCreate} />
    </MemoryRouter>,
  );
  return { onCreate };
}

describe('EmptyWorkbench', () => {
  it('一句话说清产品从哪开始（素材已在本地，不做下载）', () => {
    renderEmpty();
    expect(screen.getByText(/素材已在本地/)).toBeTruthy();
  });

  it('给出唯一的主按钮，点下去触发建剧', () => {
    const { onCreate } = renderEmpty();
    const buttons = screen.queryAllByRole('button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0]?.textContent).toContain('新增项目');
    buttons[0]?.click();
    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it('建剧中时按钮进 loading 且不可再点', () => {
    render(
      <MemoryRouter>
        <EmptyWorkbench creating onCreate={vi.fn()} />
      </MemoryRouter>,
    );
    const button = screen.getByRole('button');
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  it('不承诺任何未实装的能力（无拖放、无下载、无网盘）', () => {
    const { container } = renderEmpty();
    const text = container.textContent ?? '';
    for (const banned of ['拖', '下载短剧', '网盘', '授权书', '即将']) {
      expect(text, `空态文案里出现了 ${banned}`).not.toContain(banned);
    }
  });
});
```

- [ ] **Step 4: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/createDrama.test.ts src/features/home/__tests__/lastDrama.test.ts src/features/home/__tests__/EmptyWorkbench.test.tsx`
Expected: FAIL —— 三条 `Error: Failed to load url …`（`../createDrama`、`../../../stores/lastDrama`、`../EmptyWorkbench`），`Test Files  3 failed`。

- [ ] **Step 5: 写 `createDrama.ts`**

`desktop/src/features/home/createDrama.ts`：

```ts
/** 建剧动作：选目录 → 建项目 → 扫集 → 返回新剧的入口路径。
 *
 * 从 StartCards.tsx:88-103 上提，因为「新增项目」要有两个入口（工作台页头的 primary
 * 与空态引导里的那个），两处各写一份必然漂移。顺带把两份各写一遍的目录名解析
 * （StartCards.tsx:96 用 split(/[\\/]/)、ProjectsPage.tsx:207 用 replaceAll 再 split）
 * 收成 folderName 一处。
 *
 * 剧名取文件夹名：规格 §1 已定案「下载后通常按任务名称建文件夹，所以新增项目时
 * 剧名直接取文件夹名即与片单天然对齐，无需导入器、无需任何额外录入」。
 *
 * 一次选多目录的批量建项目要 project.batch_create（P-2），本片仍是单目录——
 * 这是 §4.2 的能力，不是工作台的。
 */
import { dramaEntryPath } from '../../app/routes';
import { pickFolder, projectApi } from '../../services/client';

export interface CreateDramaResult {
  readonly projectId: string;
  readonly name: string;
  readonly entryPath: string;
}

/** 用户取消选择时返回 null——取消不是失败，调用方不得弹错误提示。 */
export async function createDramaFromFolder(): Promise<CreateDramaResult | null> {
  const folder = await pickFolder();
  if (folder === null) return null;
  const name = folderName(folder);
  const project = await projectApi.create(name, folder);
  // 扫集失败不吞：目录里没有视频时服务端会抛（api/project.py:116 的 _ERR_NO_EPISODES），
  // 那句错要原样浮给用户。此时项目已建成，用户可以换个目录重扫，不必重建。
  await projectApi.scanEpisodes(project.id);
  return { projectId: project.id, name, entryPath: dramaEntryPath(project.id) };
}

/** 目录名 = 剧名。同时处理 / 与 \（Windows 原生对话框返回反斜杠），并容忍尾部分隔符。 */
export function folderName(folder: string): string {
  const trimmed = folder.replace(/[\\/]+$/, '');
  const name = trimmed.split(/[\\/]/).pop() ?? '';
  // 空串只可能来自 'D:\' 或 '' 这类根本没有末段的输入。给一个可用兜底而不是让
  // 建剧请求带着空名字去撞服务端的 "name 与 source_path 必填"（api/project.py:44）。
  return name === '' ? '新剧' : name;
}
```

- [ ] **Step 6: 写 `stores/lastDrama.ts`**

`desktop/src/stores/lastDrama.ts`：

```ts
/** 「继续上次」：最近打开过的那部剧。
 *
 * 用 localStorage 而不是 zustand / SQLite：按 ADR-009 的归属原则，它既不是随版本
 * 分发的只读内容（不进 resources/），也不是业务产物（不该与项目表混在 SQLite 里），
 * 而是渲染层的个人偏好——刷新即失、换机即无，都不构成损失。
 * 不用 zustand persist 是因为它带来水合时序，而本页只在挂载时读一次；
 * 三个普通函数更直白，也更便于单测（jsdom 自带 localStorage）。
 */

const STORAGE_KEY = 'dramaclip.last-drama';

export interface LastDrama {
  readonly id: string;
  readonly name: string;
  readonly visitedAtMs: number;
}

export function readLastDrama(): LastDrama | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // localStorage 不可用（隐私模式/被禁用）：当作没有记录。
    // 「继续上次」是便利项不是功能，不值得为它弹错。
    return null;
  }
  if (raw === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // 手写坏数据或上一版遗留的别的形状
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
  const candidate = parsed as Partial<LastDrama>;
  // 只认形状完整的记录：缺 id 的对象拼进路径会得到 /projects/undefined/analysis，
  // 那比"没有继续上次"糟得多。
  if (typeof candidate.id !== 'string' || candidate.id === '') return null;
  if (typeof candidate.name !== 'string') return null;
  if (typeof candidate.visitedAtMs !== 'number') return null;
  return { id: candidate.id, name: candidate.name, visitedAtMs: candidate.visitedAtMs };
}

/** 打开某部剧时调用。调用方手里已经有剧名，所以这里不发任何 RPC。 */
export function rememberDrama(projectId: string, name: string): void {
  if (projectId === '' || name === '') return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ id: projectId, name, visitedAtMs: Date.now() } satisfies LastDrama),
    );
  } catch {
    // 写不进去（配额满）就下次再试，不打扰用户
  }
}

export function clearLastDrama(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 同 readLastDrama：不可用就算了
  }
}
```

- [ ] **Step 7: 写 `EmptyWorkbench.tsx`**

`desktop/src/features/home/EmptyWorkbench.tsx`：

```tsx
/** 无剧时的主区引导（规格 §4.1 空态：「无剧时主区整块替换为「新增项目」引导」）。
 *
 * 两处刻意的取舍：
 * 1. 带完成度的首启三步（装 ASR 模型 / 配 LLM / 新增项目）是 §4.2 **剧库页**的空态，
 *    依赖 project.list 的阶段聚合，归 P-3.2。本组件只做 §4.1 要求的那一件事。
 *    首启信息没有丢：新装机同时缺模型与凭据（§4.2 的前提），此时**今日待办**
 *    恰恰就是首启引导（缺模型→去下载、未配编剧模型→去配置），所以 HomePage
 *    在空态下保留待办、只替换芯片+最近成品+继续上次三块。
 * 2. 本页唯一的 primary 在这里，不在 PageHeader 上——两处都放会违反 DSS §3.1
 *    「每屏 primary 至多 1 个」。HomePage 据此在有剧/无剧之间切换 primary 的落点。
 *
 * 文案纪律：不承诺拖放（全库无 dataTransfer）、不承诺下载与网盘（规格 §1 产品边界：
 * 软件从素材已在本地开始）、不承诺授权留痕（§7 已整体移除）。
 */
import { Button } from 'antd';
import { FolderAddOutlined } from '@ant-design/icons';
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';

export function EmptyWorkbench({
  creating,
  onCreate,
}: {
  creating: boolean;
  onCreate: () => void;
}): ReactElement {
  return (
    <section
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: tokens.spaceLg,
        padding: `${String(tokens.space3xl * 2)} ${String(tokens.space2xl)}`,
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        textAlign: 'center',
      }}
    >
      <FolderAddOutlined
        style={{ fontSize: tokens.fontDisplay, color: tokens.textTertiary, opacity: 0.4 }}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        <div style={{ fontSize: tokens.fontTitle, fontWeight: 600, color: tokens.textPrimary }}>
          还没有剧
        </div>
        <div
          style={{
            fontSize: tokens.fontCaption,
            lineHeight: '20px',
            color: tokens.textTertiary,
            maxWidth: 420,
          }}
        >
          选择素材所在文件夹即可开始——一部剧对应一个文件夹，文件夹名就是剧名。
          素材已在本地，本软件不做下载与网盘对接。
        </div>
      </div>
      <Button type="primary" icon={<FolderAddOutlined />} loading={creating} onClick={onCreate}>
        新增项目
      </Button>
    </section>
  );
}
```

> DSS §3.5 的空态图标规格是「48，tertiary 40% 透明」。`tokens.fontDisplay` 是 `'24px'`，**不是 48**。DSS 没有 48 这一档的 token，而本计划不新造 token。**落地时用 `fontSize: 48` 会撞 eslint 的禁裸写字号规则（`eslint.config.mjs:54`）**，所以正确做法是在 `desktop/src/styles/theme.ts` 的字号区新增一行 token：
>
> ```ts
>   fontEmptyIcon: '48px', // 空态图标（DSS §3.5）
> ```
>
> 然后本组件用 `fontSize: tokens.fontEmptyIcon`。这是本计划**唯一**一处新增 token，且它有明确的 DSS 出处，不是随手造的魔法数。

- [ ] **Step 8: 写 `ContinueCard.tsx`**

`desktop/src/features/home/ContinueCard.tsx`：

```tsx
/** 继续上次：最近打开过的那部剧，一键回到它（规格 §4.1 主区第四块）。
 *
 * 没有记录时整块不渲染——一个写着"还没有最近项目"的卡片是噪音。
 * 路径经 routes.ts 的 dramaEntryPath 生成，P-3.2 合并剧空间时只改那一处；
 * 已存的旧路径届时由 §2.2 的一次性重定向接住（一跳）。
 */
import { RightOutlined } from '@ant-design/icons';
import type { ReactElement } from 'react';
import { dramaEntryPath } from '../../app/routes';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { readLastDrama, type LastDrama } from '../../stores/lastDrama';

/** 相对时间只到"几天前"这一档：更细的精度对"我上次在哪"这个问题没有增益。 */
function whenLabel(visitedAtMs: number, nowMs: number): string {
  const minutes = Math.max(Math.floor((nowMs - visitedAtMs) / 60_000), 0);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${String(minutes)} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${String(hours)} 小时前`;
  return `${String(Math.floor(hours / 24))} 天前`;
}

export function ContinueCard({ nowMs }: { nowMs: number }): ReactElement | null {
  const last: LastDrama | null = readLastDrama();
  if (last === null) return null;
  return (
    <a
      href={`#${dramaEntryPath(last.id)}`}
      style={{
        ...mixins.listRow(),
        borderRadius: tokens.radiusCard,
        border: `1px solid ${tokens.borderSecondary}`,
        background: tokens.bgContainer,
        padding: `${String(tokens.spaceMd)} ${String(tokens.spaceLg)}`,
        textDecoration: 'none',
      }}
    >
      <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0, gap: 2 }}>
        <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>继续上次</span>
        <span
          style={{
            fontSize: tokens.fontBodyLg,
            fontWeight: 600,
            color: tokens.textPrimary,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {last.name}
        </span>
      </span>
      <span
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: tokens.spaceSm,
          flexShrink: 0,
          fontSize: tokens.fontMicro,
          color: tokens.textTertiary,
        }}
      >
        {whenLabel(last.visitedAtMs, nowMs)}
        <RightOutlined style={{ fontSize: tokens.fontIcon }} />
      </span>
    </a>
  );
}

export { whenLabel };
```

> 用 `<a href="#…">` 而不是 `useNavigate`：`HashRouter` 下 hash 链接天然可用，组件因此不需要 Router 上下文，也不必在测试里包 `MemoryRouter`。`export { whenLabel }` 是为了让相对时间的边界可单测——**但它会触发 `react-refresh/only-export-components`（warn 级）**。本仓 lint 追求零输出，一条常驻 warning 会让后来人分不清哪条是新引入的，所以**把它移出去**：`ContinueCard.tsx` 只导出 `ContinueCard`、删掉末尾那行 `export { whenLabel }`，改为 `import { whenLabel } from './relativeTime';`。
>
> 新建 `desktop/src/features/home/relativeTime.ts`：
>
> ```ts
> /** 相对时间：只到"几天前"这一档。
>  *
>  * 更细的精度对"我上次在哪部剧"这个问题没有增益，而"3 天 4 小时 12 分"这种
>  * 精度会让人以为它是实时的——它不是，它只在页面挂载时算一次。
>  * 负差（本机时钟被往前调过）一律收敛成"刚刚"，不输出"-5 分钟前"。
>  */
> export function whenLabel(visitedAtMs: number, nowMs: number): string {
>   const minutes = Math.max(Math.floor((nowMs - visitedAtMs) / 60_000), 0);
>   if (minutes < 1) return '刚刚';
>   if (minutes < 60) return `${String(minutes)} 分钟前`;
>   const hours = Math.floor(minutes / 60);
>   if (hours < 24) return `${String(hours)} 小时前`;
>   return `${String(Math.floor(hours / 24))} 天前`;
> }
> ```
>
> 新建 `desktop/src/features/home/__tests__/relativeTime.test.ts`：
>
> ```ts
> import { describe, expect, it } from 'vitest';
> import { whenLabel } from '../relativeTime';
>
> const NOW = 1_760_000_000_000;
> const MINUTE = 60_000;
> const HOUR = 60 * MINUTE;
> const DAY = 24 * HOUR;
>
> describe('whenLabel', () => {
>   it('不足一分钟说刚刚', () => {
>     expect(whenLabel(NOW - 30_000, NOW)).toBe('刚刚');
>   });
>
>   it('时钟被往前调过也不输出负数', () => {
>     expect(whenLabel(NOW + 5 * MINUTE, NOW)).toBe('刚刚');
>   });
>
>   it('分钟、小时、天三档各自成立且边界不重叠', () => {
>     expect(whenLabel(NOW - MINUTE, NOW)).toBe('1 分钟前');
>     expect(whenLabel(NOW - 59 * MINUTE, NOW)).toBe('59 分钟前');
>     expect(whenLabel(NOW - HOUR, NOW)).toBe('1 小时前');
>     expect(whenLabel(NOW - 23 * HOUR, NOW)).toBe('23 小时前');
>     expect(whenLabel(NOW - DAY, NOW)).toBe('1 天前');
>   });
> });
> ```
>
> 这两个文件加进 Step 10 的 `git add`（`relativeTime.ts` 已在列表里，补 `__tests__/relativeTime.test.ts`）。加上这 3 条用例后，Step 9 的期望值变为 `Tests  18 passed (18)`，Step 10 的全量期望值变为 `Test Files  18 passed (18)` / `Tests  118 passed (118)`。

- [ ] **Step 9: 跑测试确认通过**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/createDrama.test.ts src/features/home/__tests__/lastDrama.test.ts src/features/home/__tests__/EmptyWorkbench.test.tsx`
Expected: PASS —— `Test Files  3 passed (3)`，`Tests  15 passed (15)`（createDrama 6 + lastDrama 5 + EmptyWorkbench 4）。

- [ ] **Step 10: 跑三件套 + 提交**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  17 passed (17)`，`Tests  115 passed (115)`。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: **零输出、退出码 0**（若出现 `react-refresh/only-export-components`，说明 Step 8 的 `whenLabel` 没有按更正移出去）。

```bash
cd /d/PersonProjects/DramaClip
git add desktop/src/features/home/createDrama.ts desktop/src/features/home/relativeTime.ts desktop/src/features/home/EmptyWorkbench.tsx desktop/src/features/home/ContinueCard.tsx desktop/src/stores/lastDrama.ts desktop/src/styles/theme.ts desktop/src/features/home/__tests__/createDrama.test.ts desktop/src/features/home/__tests__/lastDrama.test.ts desktop/src/features/home/__tests__/EmptyWorkbench.test.tsx
git commit -m "feat(home): 建剧动作上提、继续上次与空态引导"
```

---

## Task 8: 工作台整页重写 + 死组件清扫

规格 §4.1 的结构：**主区** = 今日待办卡（首要）+ 3 统计芯片 + 最近成品 6 条 + 继续上次；**右栏** = 环境就绪度 + 工具箱 + 快速上手。

三处有据的偏离：

1. **右栏「工具箱」缺席**。`EnvPanel.tsx:105-153` 今天那个叫「工具箱」的面板里**一个工具都没有**——`TOOLS` 三项的 `key` 是 `engines`/`settings`/`projects`，`:118` 把 key 拼成 `/${key}` 后跳到三个导轨已有的页面。它是导轨的重复，还占着真工具箱的名字（§2.2 已把 `:107` 那个"被拼成 URL 的 key"标注为隐患）。本任务删除；§4.1 右栏的工具箱槽位由 P-3.4 用六个真工具填。
2. **「最近成品 6 条钩帧缩略」不出缩略图**。逐片封面不存在（`repos/exports.py:142-158` 的 SELECT 里没有 `cover_path`），今天只有项目级封面。拿项目封面冒充逐片封面正是 §4.5 抱怨的"9 条同剧片共用一张封面，视觉上无法分辨"。保留文字行形态，缩略图归 P-3.3。
3. **空态下保留今日待办**（理由见 Task 7 Step 7 的组件 docstring）。

页头改用 `PageKit.tsx` 的 `PageShell` + `PageHeader`——今天 `HomePage.tsx:97-138` 手写了一整套 `<header>`，是 §9.1「页头同构」失败的直接原因之一（另两处在 `ProjectsPage.tsx:78-91` 与 `ProductionPage.tsx:86-102`，随 P-3.2 的页面重写一并收）。

**Files:**
- Modify: `desktop/src/features/home/HomePage.tsx`（整文件替换）
- Modify: `desktop/src/features/home/RecentWorks.tsx`（改用 `PageSection`，删本地第三份竖条标题 `:74-88`）
- Modify: `desktop/src/features/home/EnvPanel.tsx`（删 `:105-153` 的 `TOOLS` 与 `ToolboxPanel`）
- Modify: `desktop/src/features/project/ProjectsPage.tsx`（`:44-48` 记录继续上次 + `:207` 复用 `folderName`）
- Modify: `desktop/src/features/narration/ProductionPage.tsx`（`:30-32` 记录继续上次）
- Modify: `desktop/src/components/layout/TitleBar.tsx`（`:171-176` 搜索结果记录继续上次）
- Delete: `desktop/src/features/home/StartCards.tsx`、`TodoCard.tsx`、`useTodos.ts`、`RecentProjects.tsx`、`SectionTitle.tsx`

- [ ] **Step 1: 重写 `HomePage.tsx`**

`desktop/src/features/home/HomePage.tsx` 整文件替换为：

```tsx
/** 工作台（规格 §4.1）：回答"今天该干什么"。
 *
 * 主区 = 今日待办（首要）+ 3 统计芯片 + 最近成品 6 条 + 继续上次
 * 右栏 = 环境就绪度 + 快速上手
 *
 * 右栏的「工具箱」槽位缺席：今天那个叫工具箱的面板里一个工具都没有，三项全是
 * 导轨已有目的地的重复跳转（原 EnvPanel.tsx:105-153），已随本任务删除。
 * 真工具箱属 P-3.4。缺席而非假控件（规格 §9.5）。
 *
 * 「最近成品」不出缩略图：逐片封面不存在（repos/exports.py:142-158 无 cover_path），
 * 拿项目封面冒充逐片封面正是 §4.5 要治的"同剧 9 条片共用一张封面"。缩略图归 P-3.3。
 */
import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App as AntdApp, Button } from 'antd';
import { FolderAddOutlined } from '@ant-design/icons';
import { PageHeader, PageShell } from '../../components/layout/PageKit';
import { restartService } from '../../services/client';
import { tokens } from '../../styles/theme';
import { ContinueCard } from './ContinueCard';
import { EmptyWorkbench } from './EmptyWorkbench';
import { EnvPanel, TipsPanel } from './EnvPanel';
import { RecentWorks } from './RecentWorks';
import { StatChips } from './StatChips';
import { TodoList } from './TodoList';
import { createDramaFromFolder } from './createDrama';
import { buildStats } from './stats';
import { buildDramas, buildTodos, type FailedJob } from './todos';
import { useWorkbench } from './useWorkbench';

/** 主区最近成品的条数（规格 §4.1：6 条）。 */
const RECENT_WORKS = 6;
/** ref_id 是 project_id 的任务类型——与 todos.ts 的 PROJECT_JOB_TARGETS 同一批。
 *  这里再判一次是因为 ref_id 语义异构（export 的是 export_id、model_download 的是
 *  model_id），把它们的 ref_id 当 project_id 拼路径会跳错剧。 */
const PROJECT_JOB_TYPES = new Set(['prescreen', 'analysis', 'narration', 'produce']);

export function HomePage() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const { data, ready } = useWorkbench();
  const [creating, setCreating] = useState(false);

  const onCreate = useCallback(() => {
    setCreating(true);
    createDramaFromFolder()
      .then((created) => {
        if (created === null) return;
        message.success(`已创建「${created.name}」`);
        void navigate(created.entryPath);
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        setCreating(false);
      });
  }, [message, navigate]);

  const onRestart = useCallback(() => {
    restartService().catch((error: unknown) => {
      message.error(error instanceof Error ? error.message : String(error));
    });
  }, [message]);

  const dramas = buildDramas(data.projects, data.works);
  const todos = buildTodos({
    serviceDown: !ready,
    models: data.models,
    llmConfigured: data.llmConfigured,
    dramas,
    failedJobs: failedJobs(data.jobs),
    serverTimeMs: data.serverTimeMs,
  });
  const stats = buildStats({
    dramaCount: data.projects.length,
    running: data.jobs
      .filter((job) => job.status === 'running' || job.status === 'pending')
      .map((job) => ({ id: job.id, progress: job.progress, createdAtMs: job.created_at })),
    serverTimeMs: data.serverTimeMs,
    works: data.works,
  });
  const hasDramas = data.projects.length > 0;

  return (
    <PageShell>
      <PageHeader
        title="工作台"
        desc={greetingLine()}
        actions={
          // 空态下 primary 归 EmptyWorkbench，这里不给——DSS §3.1「每屏 primary 至多 1 个」
          hasDramas ? (
            <Button type="primary" icon={<FolderAddOutlined />} loading={creating} onClick={onCreate}>
              新增项目
            </Button>
          ) : undefined
        }
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0,1fr) 330px',
          gap: tokens.spaceLg,
          alignItems: 'start',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXl, minWidth: 0 }}>
          <TodoList
            items={todos}
            onNavigate={(path) => {
              void navigate(path);
            }}
            onRestartService={onRestart}
          />
          {hasDramas ? (
            <>
              <StatChips stats={stats} />
              <RecentWorks works={data.works.slice(0, RECENT_WORKS)} />
              <ContinueCard nowMs={data.serverTimeMs} />
            </>
          ) : (
            <EmptyWorkbench creating={creating} onCreate={onCreate} />
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd + 2 }}>
          <EnvPanel models={data.models} llmBaseUrl={data.llmConfigured ? 'set' : ''} ttsEngine="edge" />
          <TipsPanel />
        </div>
      </div>
    </PageShell>
  );
}

function failedJobs(jobs: readonly { id: string; type: string; ref_id?: string | null; error?: string | null }[]): FailedJob[] {
  return jobs
    .filter((job) => job.status === undefined || true)
    .filter((job) => PROJECT_JOB_TYPES.has(job.type))
    .map((job) => ({
      id: job.id,
      type: job.type,
      refId: job.ref_id ?? null,
      error: job.error ?? '',
    }));
}

function greetingLine(): string {
  const now = new Date();
  const week = ['日', '一', '二', '三', '四', '五', '六'][now.getDay()] ?? '';
  const hour = now.getHours();
  const greeting =
    hour < 6 ? '夜深了' : hour < 12 ? '上午好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
  return `${greeting} · ${String(now.getMonth() + 1)}月${String(now.getDate())}日 星期${week}`;
}
```

> 上面有三处**必须按下面更正后再落地**，不要照抄：
>
> 1. `failedJobs` 的形参类型里没写 `status`，函数体却读 `job.status`，而且第一行 `.filter((job) => job.status === undefined || true)` 是恒真的废过滤。**正确写法**是直接收 `JobInfo[]` 并按状态过滤：
>
>    ```ts
>    function failedJobs(jobs: readonly JobInfo[]): FailedJob[] {
>      return jobs
>        .filter((job) => job.status === 'failed' && PROJECT_JOB_TYPES.has(job.type))
>        .map((job) => ({
>          id: job.id,
>          type: job.type,
>          refId: job.ref_id ?? null,
>          error: job.error ?? '',
>        }));
>    }
>    ```
>
>    并在顶部 import 区补 `import type { JobInfo } from '@dramaclip/protocol';`。
> 2. `<EnvPanel … llmBaseUrl={data.llmConfigured ? 'set' : ''} ttsEngine="edge" />` 是**用假值喂真参数**：`EnvPanel` 会把 `llmBaseUrl` 原样显示、把 `ttsEngine` 当成真实引擎判定 Kokoro 是否就绪（`EnvPanel.tsx:44-48`）。**正确做法是继续传真实值**——`useWorkbench` 因此要多返回两个字段。把 `WorkbenchData` 补成：
>
>    ```ts
>      readonly llmBaseUrl: string;
>      readonly ttsEngine: string;
>    ```
>
>    `reload` 里对应写 `llmBaseUrl: settings?.['llm.base_url'] ?? ''`、`ttsEngine: settings?.['tts.engine'] ?? 'edge'`（`llmConfigured` 由 `llmBaseUrl !== ''` 派生，不再单独存），`EMPTY` 补 `llmBaseUrl: ''`、`ttsEngine: 'edge'`。`HomePage` 则写：
>
>    ```tsx
>          <EnvPanel
>            models={data.models}
>            llmBaseUrl={data.llmBaseUrl}
>            ttsEngine={data.ttsEngine}
>          />
>    ```
>
>    **这条更正要回改 Task 6 Step 4 的 `useWorkbench.ts`**（把 `llmConfigured` 换成 `llmBaseUrl` + `ttsEngine` 两个字段），并在同一提交里完成，不留一个类型不自洽的中间态。
> 3. `gap: tokens.spaceMd + 2`（=14）是 DSS §1.2 禁止的非栅格值，落地时写 `gap: tokens.spaceLg`（16）。`gridTemplateColumns` 里的 `330px` 保留——DSS 没有右栏宽度的 token，本计划不新造；它是列宽不是间距，不在 §1.2 的禁令范围内。

- [ ] **Step 2: `RecentWorks.tsx` 收敛竖条标题**

`desktop/src/features/home/RecentWorks.tsx`：

1. 删除 `:74-88` 的本地 `SectionHeader` 函数（这是同一份渐变竖条标题的**第三份**拷贝；另两份是 `SectionTitle.tsx:5` 与 `StartCards.tsx:160`，DSS §6.3 点名要收敛）。
2. `:23` 的 `<SectionHeader>最近成品</SectionHeader>` 与其外层的 `<section>` 一并换成 `PageSection`：

```tsx
import { PageSection } from '../../components/layout/PageKit';

export function RecentWorks({ works }: { works: readonly WorkItem[] }): React.ReactElement {
  const navigate = useNavigate();
  return (
    <PageSection
      title="最近成品"
      extra={
        works.length > 0 ? (
          <GhostLink
            label="查看全部"
            onClick={() => {
              void navigate('/works');
            }}
          />
        ) : undefined
      }
      dense
    >
      {works.length === 0 ? (
        <div
          style={{
            padding: tokens.spaceLg,
            fontSize: tokens.fontCaption,
            color: tokens.textTertiary,
            textAlign: 'center',
          }}
        >
          还没有成片——出片完成后会出现在这里
        </div>
      ) : (
        works.map((work) => (
          <WorkRow
            key={work.id}
            work={work}
            onClick={() => {
              void navigate('/works');
            }}
          />
        ))
      )}
    </PageSection>
  );
}
```

3. 把原来内联在 `works.map` 里的那一大坨 `<div onClick onMouseEnter onMouseLeave>` 抽成 `WorkRow`，把"查看全部"那坨抽成 `GhostLink`（两者都受 `max-lines-per-function: 60` 约束，抽出来才放得下）：

```tsx
function WorkRow({ work, onClick }: { work: WorkItem; onClick: () => void }): React.ReactElement {
  return (
    <div
      onClick={onClick}
      style={{ ...mixins.listRow(), padding: `${String(tokens.spaceMd)} ${String(tokens.spaceLg)}`, cursor: 'pointer' }}
      onMouseEnter={(event) => {
        event.currentTarget.style.background = tokens.bgElevated;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.background = 'transparent';
      }}
    >
      <span
        style={{
          fontSize: tokens.fontCaption,
          color: tokens.textPrimary,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {work.project_name} · {modeLabel(work.narration_mode)}
      </span>
      <span
        style={{
          marginLeft: 'auto',
          flexShrink: 0,
          fontSize: tokens.fontMicro,
          color: tokens.textTertiary,
        }}
      >
        {formatDate(work.completed_at)}
      </span>
    </div>
  );
}

function GhostLink({ label, onClick }: { label: string; onClick: () => void }): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: 'none',
        border: 'none',
        padding: 0,
        color: tokens.colorPrimary,
        fontSize: tokens.fontCaption,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  );
}
```

4. import 区补 `import { mixins } from '../../styles/mixins';`；`modeLabel` 与 `formatDate` 保持原样（`:9-16`、`:21-25`）。

- [ ] **Step 3: `EnvPanel.tsx` 删掉假工具箱**

`desktop/src/features/home/EnvPanel.tsx`：

1. 删除 `:105-109` 的 `TOOLS` 常量与 `:111-153` 的 `ToolboxPanel` 整个函数。
2. 删除随之无用的 import：`CloudServerOutlined`、`FolderOutlined`、`SettingOutlined`（`:7,9,11`）——它们只被 `TOOLS` 用到。保留 `BookOutlined`、`EditOutlined`、`RightOutlined`（`EnvItem` 与 `TipsPanel` 在用）。
3. `EnvPanel` 与 `TipsPanel` 两个导出**保持不动**（HomePage 仍在用）。

> 为什么是删而不是改成真的：§4.1 右栏的「工具箱」指的是 §4.7 那七个单发工具，它们要 6 个新 `tools.*` 方法（P-3.4）。今天这三项跳的是导轨已有的三个页面，留着它就是留一个名不副实的控件。

- [ ] **Step 4: 三个入口记录「继续上次」**

三处调用点手里都已经有剧名，所以不需要额外 RPC。

1. `desktop/src/features/project/ProjectsPage.tsx`
   - import 区加 `import { rememberDrama } from '../../stores/lastDrama';` 与 `import { dramaEntryPath } from '../../app/routes';`
   - `:45-48` 的 `onOpen` 改为：
     ```tsx
         onOpen={(project) => {
           rememberDrama(project.id, project.name);
           void navigate(dramaEntryPath(project.id));
         }}
     ```
   - `:207` 的 `setName(picked.replaceAll('\\', '/').split('/').pop() ?? '');` **保持不动**。它与 `features/home/createDrama.ts` 的 `folderName` 是同一件事的两份实现，本应合并——但 `docs/desktop/01-渲染层设计.md:40` 明写「域内自含，**禁止跨 feature import**」，`features/project` 不能去 import `features/home`。这处重复**登记给 P-3.2**：那时 `ProjectsPage` 会被 §4.2 的批量建项目整页重写，`folderName` 应随之上提到一个非 feature 的共享位置（`app/` 或 `components/`，后者已有 `modeMeta.ts` 这个跨 feature 共享数据模块的先例）。
2. `desktop/src/features/narration/ProductionPage.tsx`
   - import 区加 `import { rememberDrama } from '../../stores/lastDrama';`
   - `:30-32` 的 `.then` 改为：
     ```tsx
         void projectApi.get(projectId).then((detail) => {
           setProject(detail.project);
           rememberDrama(detail.project.id, detail.project.name);
         });
     ```
3. `desktop/src/components/layout/TitleBar.tsx`
   - import 区加 `import { rememberDrama } from '../../stores/lastDrama';`
   - `:149-195` 的 `SearchResults` 的 `onPick` 签名从 `(path: string) => void` 改成 `(item: ProjectOption) => void`，`:174-176` 的 `onMouseDown` 改为：
     ```tsx
           onMouseDown={() => {
             onPick(item);
           }}
     ```
   - `:138-143` 的调用点改为：
     ```tsx
           <SearchResults
             items={items}
             onPick={(picked) => {
               rememberDrama(picked.id, picked.name);
               void navigate(dramaEntryPath(picked.id));
             }}
           />
     ```

> `desktop/src/features/analysis/WorkbenchPage.tsx` 与 `WorkbenchHeader.tsx` **不在此列**——该目录属另一位工程师。分析页的入口全部经上面三处，所以覆盖是完整的。

- [ ] **Step 5: 删除五个死文件**

```bash
cd /d/PersonProjects/DramaClip
git rm desktop/src/features/home/StartCards.tsx desktop/src/features/home/TodoCard.tsx desktop/src/features/home/useTodos.ts desktop/src/features/home/RecentProjects.tsx desktop/src/features/home/SectionTitle.tsx
```

删除依据（逐个 grep 核实过，删除前请再跑一遍确认没有新增引用）：

```bash
cd /d/PersonProjects/DramaClip/desktop/src
grep -rn "StartCards\|TodoCard\|useTodos\|RecentProjects\|SectionTitle" --include=*.ts --include=*.tsx .
```

Expected: **只剩这五个文件自身的定义行**（`StartCards.tsx:44`、`TodoCard.tsx:6`、`useTodos.ts:11`、`RecentProjects.tsx:14`、`SectionTitle.tsx:5`）。若还有别处引用，先改那一处再删——**不要留下删不掉的半死文件**。

- [ ] **Step 6: 跑三件套**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  18 passed (18)`，`Tests  118 passed (118)`（本任务不新增测试文件；Task 7 收在 118）。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。**这一步是本任务的主要安全网**：五个文件删除后若还有残留引用，`tsc` 会逐处点名。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: 零输出、退出码 0。若报 `no-unused-vars`，说明 Step 3 的 import 清理不彻底。

- [ ] **Step 7: 提交**

```bash
cd /d/PersonProjects/DramaClip
git add desktop/src/features/home/HomePage.tsx desktop/src/features/home/RecentWorks.tsx desktop/src/features/home/EnvPanel.tsx desktop/src/features/home/useWorkbench.ts desktop/src/features/project/ProjectsPage.tsx desktop/src/features/narration/ProductionPage.tsx desktop/src/components/layout/TitleBar.tsx
git commit -m "feat(home): 工作台改为开工页，删掉五个死组件与假工具箱面板"
```

> 上面 `git add` 里没有 Step 5 `git rm` 的五个文件——`git rm` 已经把删除暂存了。**不要用 `git add -A` 或 `git add .` 补**，那会卷走同树另一位工程师的暂存。若 `git status --short` 显示还有未暂存的相关改动，逐个显式 `git add <路径>`。

---

## Task 9: 收口——取不到任务状态时不得谎报 0，加分层守卫，清死引用，同步文档

Task 6 的 `useWorkbench` 对 `jobsApi.list` 用了 `.catch(() => null)`，这是沿用 `HomePage.tsx:31-35` 的既有写法。但它有一个 §3.3 级的后果：**`jobs.list` 失败时，在跑芯片会显示「0 条在跑」、失败待办会静默消失，界面看起来一切正常**。"取不到"和"没有"必须可区分——这正是规格 §3.3 静默禁止清单的同一逻辑（「参数未生效 → 改了没反应」那一行）。本任务把它补上，再加两道守卫，最后清引用、同步文档。

**Files:**
- Modify: `desktop/src/features/home/stats.ts`（`StatsInput`/`WorkbenchStats` 增 `jobsAvailable`）
- Modify: `desktop/src/features/home/todos.ts`（`TodoInput` 增 `jobsAvailable`/`jobsError`，新增一条待办）
- Modify: `desktop/src/features/home/useWorkbench.ts`（`WorkbenchData` 增 `jobsAvailable`/`jobsError`）
- Modify: `desktop/src/features/home/StatChips.tsx`（不可用时显示 `—`）
- Modify: `desktop/src/features/home/HomePage.tsx`（透传两个新字段）
- Modify: `desktop/src/features/home/__tests__/stats.test.ts`、`__tests__/todos.test.ts`、`__tests__/StatChips.test.tsx`
- Modify: `desktop/src/app/__tests__/iaContract.test.ts`（加分层守卫）
- Modify: `docs/desktop/01-渲染层设计.md`（§1 的导航与路由表已严重过期）
- Modify: `docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md`（§2.1 补第二处高亮缺陷）

- [ ] **Step 1: 写失败测试——取不到任务状态**

`desktop/src/features/home/__tests__/stats.test.ts` 的 `input()` 助手补一个字段并追加用例：

```ts
function input(over: Partial<StatsInput> = {}): StatsInput {
  return { dramaCount: 0, running: [], serverTimeMs: NOW, works: [], jobsAvailable: true, ...over };
}
```

```ts
describe('buildStats：任务状态取不到', () => {
  it('在跑值显示为不可用，且不显示任何 ETA', () => {
    const stats = buildStats(
      input({ jobsAvailable: false, running: [{ id: 'j', progress: 50, createdAtMs: NOW - MINUTE }] }),
    );
    expect(stats.jobsAvailable).toBe(false);
    expect(stats.runningValue).toBe('—');
    expect(stats.runningEtaLabel).toBe('');
  });

  it('取得到时在跑值就是条数', () => {
    const stats = buildStats(input({ running: [{ id: 'j', progress: 50, createdAtMs: NOW - MINUTE }] }));
    expect(stats.jobsAvailable).toBe(true);
    expect(stats.runningValue).toBe('1');
  });

  it('成品数与周增不受任务状态影响（它们来自 export.list_works）', () => {
    const stats = buildStats(input({ jobsAvailable: false, works: [work('w1', NOW)] }));
    expect(stats.workCount).toBe(1);
    expect(stats.workWeekDelta).toBe(1);
  });
});
```

`desktop/src/features/home/__tests__/todos.test.ts` 的 `base()` 助手补字段并追加用例：

```ts
function base(over: Partial<TodoInput> = {}): TodoInput {
  return {
    serviceDown: false,
    models: [model()],
    llmConfigured: true,
    dramas: [],
    failedJobs: [],
    serverTimeMs: NOW,
    jobsAvailable: true,
    jobsError: null,
    ...over,
  };
}
```

```ts
describe('buildTodos：任务状态取不到', () => {
  it('必须有一条 error 待办说明"在跑与失败待办不可用"，并带上原因原文', () => {
    const items = buildTodos(base({ jobsAvailable: false, jobsError: 'RpcError -32601: 方法未注册' }));
    expect(items[0]?.key).toBe('jobs-unavailable');
    expect(items[0]?.severity).toBe('error');
    expect(items[0]?.detail).toBe('RpcError -32601: 方法未注册');
    expect(items[0]?.action).toEqual({ kind: 'restart-service', label: '重启服务' });
  });

  it('服务本来就不可用时不重复报（那条已经说了重启）', () => {
    const items = buildTodos(base({ serviceDown: true, jobsAvailable: false, jobsError: 'x' }));
    expect(items.map((item) => item.key)).toEqual(['service-down']);
  });

  it('取得到时不出这条', () => {
    expect(keys(base({ jobsAvailable: true }))).toEqual([]);
  });
});
```

`desktop/src/features/home/__tests__/StatChips.test.tsx` 的 `stats()` 助手补字段并追加用例：

```ts
function stats(over: Partial<WorkbenchStats> = {}): WorkbenchStats {
  return {
    dramaCount: 12,
    runningCount: 3,
    runningValue: '3',
    runningEtaLabel: '预计还需 8 分',
    jobsAvailable: true,
    workCount: 45,
    workCountOverflow: false,
    workWeekDelta: 6,
    ...over,
  };
}
```

```tsx
  it('任务状态取不到时在跑显示 —，不显示 0', () => {
    render(<StatChips stats={stats({ jobsAvailable: false, runningCount: 0, runningValue: '—', runningEtaLabel: '' })} />);
    expect(screen.getByText('—')).toBeTruthy();
    expect(screen.queryByText('0')).toBeNull();
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home/__tests__/stats.test.ts src/features/home/__tests__/todos.test.ts src/features/home/__tests__/StatChips.test.tsx`
Expected: FAIL —— `tsc` 层面的类型错先炸（`StatsInput`/`TodoInput`/`WorkbenchStats` 里没有新字段），或断言红：`stats.runningValue` 为 `undefined`、`items[0]?.key` 不是 `'jobs-unavailable'`。

- [ ] **Step 3: `stats.ts` 增 `jobsAvailable`**

`desktop/src/features/home/stats.ts`：

1. `StatsInput` 增一行（放在 `serverTimeMs` 之后）：
   ```ts
     /** jobs.list 是否取到。取不到时"在跑"必须显示不可用——0 是谎报（规格 §3.3 同一逻辑）。 */
     readonly jobsAvailable: boolean;
   ```
2. `WorkbenchStats` 增两行、改一行：
   ```ts
     readonly runningCount: number;
     /** 芯片上直接显示的值：取得到是条数，取不到是 '—'。 */
     readonly runningValue: string;
     readonly jobsAvailable: boolean;
   ```
3. `buildStats` 的返回体改为：
   ```ts
     return {
       dramaCount: input.dramaCount,
       runningCount: input.running.length,
       runningValue: input.jobsAvailable ? String(input.running.length) : '—',
       jobsAvailable: input.jobsAvailable,
       // 取不到任务状态时不给 ETA：一个基于空样本的外推比不给更糟。
       runningEtaLabel: input.jobsAvailable ? etaLabel(input.running, input.serverTimeMs) : '',
       workCount: input.works.length,
       workCountOverflow: overflow,
       workWeekDelta: overflow ? null : weekDelta,
     };
   ```

- [ ] **Step 4: `todos.ts` 增 `jobs-unavailable` 待办**

`desktop/src/features/home/todos.ts`：

1. `TodoInput` 增两行：
   ```ts
     /** jobs.list 是否取到。取不到 = 在跑条数与失败待办双双不可用，必须说出来。 */
     readonly jobsAvailable: boolean;
     /** 取不到时的原因原文，进 detail 不截断。 */
     readonly jobsError: string | null;
   ```
2. `buildTodos` 里，紧跟 `serviceDown` 那个 `if` 之后插入：
   ```ts
     // 服务在跑但 jobs.list 取不到：在跑条数与失败待办都成了盲区。
     // 不报的话界面会显示"0 条在跑、没有失败"，那是把"不知道"说成"没有"（规格 §3.3）。
     // serviceDown 时不重复报——那一条已经给了同一个动作。
     if (!input.serviceDown && !input.jobsAvailable) {
       items.push({
         key: 'jobs-unavailable',
         text: '任务状态取不到：在跑条数与失败待办不可用',
         detail: input.jobsError ?? '',
         severity: 'error',
         action: { kind: 'restart-service', label: '重启服务' },
       });
     }
   ```

- [ ] **Step 5: `useWorkbench.ts` 保留失败原因**

`desktop/src/features/home/useWorkbench.ts`：

1. `WorkbenchData` 增两行、删一行：
   ```ts
     /** jobs.list 是否取到；取不到时 jobsError 是原因原文。 */
     readonly jobsAvailable: boolean;
     readonly jobsError: string | null;
   ```
   （`jobs: JobInfo[]` 保留，取不到时为 `[]`。）
2. `EMPTY` 补 `jobsAvailable: false, jobsError: null`。
3. `reload` 里的 `jobsApi.list(JOBS_SCAN_LIMIT).catch(() => null)` 改为保留错误：
   ```ts
         jobsApi
           .list(JOBS_SCAN_LIMIT)
           .then((result): JobsListResult | Error => result)
           .catch((error: unknown): JobsListResult | Error =>
             error instanceof Error ? error : new Error(String(error)),
           ),
   ```
4. `setData` 里对应三行改为：
   ```ts
         jobs: jobs instanceof Error ? [] : jobs.jobs,
         jobsAvailable: !(jobs instanceof Error),
         jobsError: jobs instanceof Error ? `${jobs.name}: ${jobs.message}` : null,
   ```
   并在 import 区补 `JobsListResult`（`import type { JobInfo, JobsListResult, ModelInfo, Project, WorkItem } from '@dramaclip/protocol';`）。

> `.then((result): JobsListResult | Error => result)` 那一跳是必要的：`Promise.all` 的元素类型要从 then/catch 两个分支推出来，不显式标注的话 `tsc` 会把它推成 `JobsListResult | null`，`instanceof Error` 那一支就永远不成立。

- [ ] **Step 6: `StatChips.tsx` 与 `HomePage.tsx` 透传**

`desktop/src/features/home/StatChips.tsx` 的 `chips` 数组里 `running` 那一项改为：

```tsx
    {
      key: 'running',
      value: stats.runningValue,
      label: stats.jobsAvailable ? '条在跑' : '条在跑 · 状态取不到',
      note: stats.runningEtaLabel,
    },
```

`desktop/src/features/home/HomePage.tsx`：

1. `buildTodos({...})` 的入参补两行 `jobsAvailable: data.jobsAvailable,` 与 `jobsError: data.jobsError,`。
2. `buildStats({...})` 的入参补一行 `jobsAvailable: data.jobsAvailable,`。

- [ ] **Step 7: 加分层守卫**

`desktop/src/app/__tests__/iaContract.test.ts` 末尾追加（并在 import 区补 `navItems.ts` 的路径解析）：

```ts
const NAVITEMS_SOURCE = readFileSync(
  path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', 'navItems.ts'),
  'utf8',
);
const ROUTES_SOURCE = readFileSync(
  path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', 'routes.ts'),
  'utf8',
);

describe('IA 数据层的分层纪律', () => {
  // navItems.ts / routes.ts 被 components/layout、features/*、app/router 三方消费，
  // 所以它们自己绝不能反向 import features 或 components——否则 app→features→app 成环。
  // eslint 只挡了 components/ 反向依赖 features/（eslint.config.mjs:66-72），挡不到这条。
  it('navItems.ts 与 routes.ts 不得 import features 或 components', () => {
    for (const [name, source] of [['navItems.ts', NAVITEMS_SOURCE], ['routes.ts', ROUTES_SOURCE]] as const) {
      const imports = [...source.matchAll(/from\s+'([^']+)'/g)].map((match) => match[1] ?? '');
      for (const specifier of imports) {
        expect(specifier, `${name} 反向依赖了 ${specifier}`).not.toMatch(/features|components/);
      }
    }
  });

  it('routes.ts 完全不依赖任何本地模块（它是叶子）', () => {
    expect(ROUTES_SOURCE).not.toMatch(/^\s*import\s/m);
  });
});
```

- [ ] **Step 8: 跑测试确认通过 + 变异检查**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  18 passed (18)`，`Tests  127 passed (127)`（Task 8 收在 118，本任务 +3 stats +3 todos +1 StatChips +2 分层守卫 = +9）。

变异检查（逐条破坏、必须变红、按字节还原）：
1. `buildStats` 的 `runningValue` 改成 `String(input.running.length)`（丢掉 `jobsAvailable` 分支）→ 用例「在跑值显示为不可用」必须红。
2. `buildTodos` 的 `if (!input.serviceDown && !input.jobsAvailable)` 去掉 `!input.serviceDown` → 用例「服务本来就不可用时不重复报」必须红。
3. `useWorkbench` 的 `jobs instanceof Error ? [] : jobs.jobs` 改回 `jobs?.jobs ?? []` → `typecheck` 必须红（这就是 Step 5 那条类型标注存在的理由）。
4. 在 `routes.ts` 顶部临时加 `import { NAV_ITEMS } from './navItems';` → 用例「routes.ts 完全不依赖任何本地模块」必须红。
5. 在 `navItems.ts` 顶部临时加 `import { tokens } from '../styles/theme';` → 不红（`styles` 不在禁止之列，这是有意的：tokens 是叶子模块）。**这条是阴性对照**，用来证明第 4 条不是永远绿。

Run（每轮）: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run src/features/home src/app`

- [ ] **Step 9: 死引用清扫验证**

```bash
cd /d/PersonProjects/DramaClip/desktop/src
grep -rn "StartCards\|TodoCard\|useTodos\|RecentProjects\|SectionTitle\|ToolboxPanel\|LegacyModelTabRedirect" --include=*.ts --include=*.tsx .
```
Expected: **零输出**。（`LegacyModelTabRedirect` 在 Task 2 被泛化成 `LegacyParamRedirect`，旧名必须一个不剩。）

```bash
cd /d/PersonProjects/DramaClip/desktop/src
grep -rn "dashboardSummary\|dashboard_summary" --include=*.ts --include=*.tsx .
```
Expected: 只剩 `services/client.ts:83` 的 `projectApi.dashboardSummary` 定义行——**渲染层已无调用者**。这是有意的（见 `stats.ts` 顶部注释：它的 `export_count` 不带状态过滤）。该方法本身与 `protocol/` 声明都不动，避免与 P-2 撞车；**这一行登记给 P-3.3**（拆分文件 §3）。

```bash
cd /d/PersonProjects/DramaClip/desktop/src
grep -rn "restartService" --include=*.ts --include=*.tsx .
```
Expected: 三处——`services/client.ts:34,35` 的定义、`features/home/HomePage.tsx` 的 import 与调用。它从"零消费者的死导出"变成有唯一合理使用者（服务不可用待办的「重启服务」）。

```bash
cd /d/PersonProjects/DramaClip/desktop/src
grep -rn "渐变竖条\|gradientAccent" --include=*.tsx .
```
Expected: 只剩 `styles/mixins.ts:52` 的 `sectionBar()` 与 `components/layout/TitleBar.tsx:31` 的 Logo 底色——三份竖条标题拷贝已收敛为 `PageSection` 内置的一份。

- [ ] **Step 10: 同步 `docs/desktop/01-渲染层设计.md` §1**

该文件 `:8-29` 已严重过期：它描述的双层导航（全局组「工作台 · 项目管理 · 模型管理 · 系统设置」+ 项目组「智能分析 · 模式配置 · 生成进度 · 时间线编辑 · 导出管理」）与路由表里的 `/projects/:id/modes`、`/projects/:id/generate`、`/plans/:planId/timeline`、`/projects/:id/export`、`/models` **五条路由今天都不存在**。把 `:8-29` 整块替换为：

```markdown
**单层导轨 + 页面内阶段条**（信息架构以 `docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §2 为准，本节只记结构落地）：

- 导轨清单是唯一真相源：`src/app/navItems.ts`（数据）+ `src/components/layout/Rail.tsx`（渲染）。
  加一页 = 在 `navItems.ts` 追加一项 + 在 `src/app/routes.ts` 登记路径，不改 `AppLayout`。
- 分两组，中间一条 `border/subtle` 分隔线：上组 = 生产循环（工作台 / 项目 / 成品），
  下组 = 配置与元信息（引擎 / 设置）。终态 8 项，「队列」属 P-2.5、「工具箱」属 P-3.4、「关于」属 P-3.6。
- 高亮按前缀匹配（`navItems.ts` 的 `isNavActive`）：根路径精确匹配，其余"自身或子路径"命中，
  所以 `/engines/llm` 保持「引擎」高亮、`/projects/:id/analysis` 保持「项目」高亮。

| 路由 | 页面 | 备注 |
|------|------|------|
| `/` | 工作台：今日待办 / 3 统计芯片 / 最近成品 6 条 / 继续上次 ｜ 右栏 环境就绪度 + 快速上手 | 规格 §4.1 |
| `/projects` | 项目管理：卡片网格 + 新建 + 重命名/复制/删除 | P-3.2 改名 `/dramas` 并按 §4.2 重写 |
| `/projects/:id/analysis` | 智能分析工作台 | P-3.2 合并进剧空间 `/drama/:id` |
| `/projects/:id/produce` | 出片中心：选模式 + 一键出片 + 出片记录 | 同上 |
| `/works` | 成品库：跨项目已完成成片 | P-3.3 按 §4.5 改为按剧分组 + 逐片封面 + 自检徽章 |
| `/engines`、`/engines/:tab` | 引擎中心：总览 / ASR / TTS / LLM | 原 `/models`，P-1 已更名 |
| `/settings` | 偏好设置：出片 / 分析 / 下载 / 硬件 | §4.6 的「生产线默认值」「字幕」分区归 P-3.2 |

- HashRouter（兼容 `file://` 加载）；
- 旧路径重定向表驱动：`routes.ts` 的 `LEGACY_REDIRECTS`（静态一跳）与 `LEGACY_PARAM_REDIRECTS`
  （保住路径参数），由 `router.tsx` 的 `LegacyParamRedirect` 消费。**只留一跳，旧组件同期删除**，
  不留暗组件（规格 §2.2）。
- 一致性由 `src/app/__tests__/iaContract.test.ts` 守卫：导轨 ↔ 路由清单 ↔ `router.tsx` 的
  `path`/`to` 字面量三方必须相符，改名漏一处当场红。
- "继续上次"：`src/stores/lastDrama.ts`，localStorage 记忆上次打开的剧（**只记位置**，
  非 v1 断点续剪，ADR-007 语义不变）。
```

`:13` 那句「侧边栏底部固定：GPU 信息与显存、Python 服务状态圆点 + 重启按钮」也过期了——GPU 与服务状态今天在**底部状态栏**（`components/layout/StatusBar.tsx`），重启按钮至今不存在（`restartService` 的唯一消费者是工作台待办）。把 `:13` 替换为：

```markdown
底部状态栏（`components/layout/StatusBar.tsx`）常驻：Python 服务状态圆点、FFmpeg、GPU、应用版本。导轨不含任何状态信息。
```

- [ ] **Step 11: 给规格 §2.1 补第二处高亮缺陷**

`docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md` §2.1 的「高亮规则（修既有缺陷）」一段末尾追加一句：

```markdown
本轮实施复核另发现同源的第二处：`/engines/:tab` 深链（由工作台环境就绪度的「去配置」与引擎总览的能力卡跳入，共 6 处）同样让「引擎」失去高亮——根因与剧空间那处相同，都是精确等值比较。P-3.1 一并按前缀匹配修掉。
```

- [ ] **Step 12: 跑三件套 + 提交**

Run: `cd /d/PersonProjects/DramaClip/desktop && npx vitest run`
Expected: PASS —— `Test Files  18 passed (18)`，`Tests  127 passed (127)`。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run typecheck`
Expected: 零输出、退出码 0。

Run: `cd /d/PersonProjects/DramaClip/desktop && npm run lint`
Expected: 零输出、退出码 0。

```bash
cd /d/PersonProjects/DramaClip
git add desktop/src/features/home/stats.ts desktop/src/features/home/todos.ts desktop/src/features/home/useWorkbench.ts desktop/src/features/home/StatChips.tsx desktop/src/features/home/HomePage.tsx desktop/src/features/home/__tests__/stats.test.ts desktop/src/features/home/__tests__/todos.test.ts desktop/src/features/home/__tests__/StatChips.test.tsx desktop/src/app/__tests__/iaContract.test.ts docs/desktop/01-渲染层设计.md docs/superpowers/specs/2026-09-10-dramaclip-ui-redesign-design.md
git commit -m "fix(home): 任务状态取不到时不谎报 0；补分层守卫与渲染层设计文档同步"
```

---

## Task 10: 手工验收（P-3.1 出口）与实测记录

不产新代码，只产证据。桌面端**没有任何浏览器自动化或视觉回归基建**（`desktop/package.json:16-46` 逐项核过：无 Playwright、无 Storybook、无快照），所以规格 §9.1 的「任取两页截图并排」只能人做。本任务就是那套人工协议。

**⚠️ 前置**：本任务要起 dev server 与 Python 服务。**本机九模式真机门禁跑完之前不要执行**——CPU 争用会让门禁的时序断言失真，也会让下面的 ETA 观察毫无意义。Task 1-9 只跑 `vitest`/`tsc`/`eslint`，不受此限。

- [ ] **Step 1: 起服务**

Run: `cd /d/PersonProjects/DramaClip && npm run dev`
Expected: Vite 在固定端口 5180 起（`desktop/vite.config.ts` 的 `strictPort: true`），`vite-plugin-electron` 构建主进程与 preload 后自动拉起 Electron 窗口。窗口内底部状态栏应显示「Python 服务 · 运行中」（绿点）。

> 若状态栏是「不可用」（红点），工作台的待办第一条会是「Python 服务不可用」+「重启服务」——**那正好是 M7 的一个真实样本**，先记录再继续排查。

- [ ] **Step 2: M1 导轨形态**

看左侧导轨。
Expected（逐条核）：
1. 5 项，自上而下：`工作台` `项目` `成品` `引擎` `设置`；
2. 每项都是「图标在上、两字标签在下」——**并列元素同构，不存在有图标与无图标混排**；
3. `成品` 与 `引擎` 之间有一条**浅色**横向分隔线（宽 36px、`border/subtle #212736`），比卡片描边更轻；
4. 标签里没有任何一个是「作品」（已改称成品）、没有斜杠拼的复合词；
5. 导轨上**没有**「队列」「工具箱」「关于」三项（目的地不存在，缺席而非假控件）。

- [ ] **Step 3: M2 高亮——引擎深链（这条今天坏，是本片修的）**

1. 点导轨「引擎」→ Expected: 地址栏 `#/engines`，「引擎」项底色变主色 8%、字色变主色、字重变粗。
2. 点左栏「文案 LLM」→ Expected: 地址栏 `#/engines/llm`，**「引擎」仍然高亮**，且页内 LLM tab 选中。
3. 回工作台，点右栏「环境就绪度」里任一条的 ghost 链接（如「去下载」）→ Expected: 落到 `#/engines/asr`，「引擎」高亮。

- [ ] **Step 4: M3 高亮——单剧详情（规格 §2.1 点名的那处）**

1. 点导轨「项目」→ 点任一剧卡。
2. Expected: 地址栏 `#/projects/<id>/analysis`，**「项目」保持高亮**（今天这一步之后 5 项全暗）。

- [ ] **Step 5: M4 旧路径一跳即达**

在地址栏手输 `#/models/llm` 回车。
Expected: 一跳落到 `#/engines/llm`，LLM tab 选中，**浏览器历史里只多一条**（`replace`，不是 push）。再手输 `#/models` → 落 `#/engines` 总览。

- [ ] **Step 6: M5 工作台结构**

点导轨「工作台」。
Expected：
1. 页头 = 标题「工作台」（22px/700）+ 下方一行问候与日期（12px，tertiary）+ 右上**唯一**一个 primary 按钮「新增项目」；
2. 主区自上而下：今日待办（有才出现）→ 三芯片 → 最近成品 → 继续上次；
3. 右栏：环境就绪度、快速上手——**不得再有名为「工具箱」的面板**；
4. 页面上找不到「开始创作」三卡（新建项目 / 继续创作 / 引擎中心）——已删；
5. 页面上找不到「最近项目」列表——已删。

- [ ] **Step 7: M6 三芯片与数据库对账**

Expected: 恰好三个芯片，标签依次是「部剧」「条在跑」「条成品」；「条在跑」下方在有任务时多一行「预计还需 …」或「预计中…」，无任务时无该行；「条成品」下方是「本周 +N」或「本周 —」。

只读对账（**只跑 SELECT，不写库**）：

```bash
cd /d/PersonProjects/DramaClip
./.venv/Scripts/python -c "import sqlite3;c=sqlite3.connect('data/data.db');print('projects',c.execute('select count(*) from projects').fetchone()[0]);print('works',c.execute(\"select count(*) from export_jobs where status='completed' and output_path is not null\").fetchone()[0]);print('export_jobs_all',c.execute('select count(*) from export_jobs').fetchone()[0])"
```

Expected: 芯片「部剧」的数字 = `projects`；芯片「条成品」的数字 = `works`。
**注意 `works` 与 `export_jobs_all` 可能不相等**——不相等恰好证明了为什么不用 `dashboard_summary.export_count`（`repos/projects.py:158` 不带状态过滤）。把两个数都记进 Step 12。
开工时的基线实测（2026-09-12）：`projects 1` / `works 45` / `export_jobs_all 45`（当时全为 completed，所以两数恰好相等）。

- [ ] **Step 8: M7 待办逐条点**

先查有没有现成的失败任务（只读）：

```bash
cd /d/PersonProjects/DramaClip
./.venv/Scripts/python -c "import sqlite3;c=sqlite3.connect('data/data.db');print(c.execute(\"select id,type,ref_id,status,substr(coalesce(error,''),1,80) from jobs where status='failed' order by updated_at desc limit 5\").fetchall())"
```

- **若有 `type` 属 `analysis`/`prescreen`/`narration`/`produce` 的失败行**：Expected 工作台待办里出现「《剧名》<分析|预筛|编排|出片>任务失败」，鼠标悬停在文本上显示 `error` **原文不截断**，右侧 ghost「去处理」点下去落到该剧的 `analysis` 或 `produce` 页。
- **若查询结果为空**：这条在本机**无法手工验证**——照实记进 Step 12（「失败任务待办：本机无失败样本，未验证；逻辑由 `todos.test.ts` 的 5 条用例覆盖」），**不要为了验证去人为制造一次失败**（那要跑 ffmpeg，与门禁抢 CPU）。

无条件可验的两条：
1. 进「引擎」→ Expected 总览页「文案 LLM」卡的当前值**不含**「关键词降级」（已配置时是「云端 · <模型名>」，未配置时是「未配置 · 解说模式不可用」）。
2. 进「引擎 → 文案 LLM」→ Expected 有一段金色描边的说明，逐字为：
   `未配置时：分析（转写、冲突打分）改用关键词打分，仍可跑完；但解说文案必须由编剧模型产出，没有兜底——七个解说模式的每条方案都会失败并在任务里说明原因。仅「纯原片剪辑」「字幕金句流」不依赖编剧模型。`
   这段说明**无论 LLM 是否已配置都常驻**——它描述的是"未配置时"的后果，不是当前状态。

- [ ] **Step 9: M8 继续上次**

1. 点导轨「项目」→ 点一部剧 → 点导轨「工作台」。
2. Expected: 主区底部出现一行「继续上次 / <剧名> / N 分钟前」，右侧一个箭头。
3. 点它 → Expected: 回到该剧的分析页。
4. 开 DevTools → Application → Local Storage → `#/`，Expected 有一条 key `dramaclip.last-drama`，值是含 `id`/`name`/`visitedAtMs` 三键的 JSON。
5. 手工把该值改成 `{"id":"nope"}` 后刷新工作台 → Expected: **不渲染**「继续上次」（形状不完整一律当没有记录），且地址栏不出现 `/projects/undefined/analysis`。

- [ ] **Step 10: M9 空态（有条件）**

空态要求 0 部剧，而删掉本机唯一那部剧会连带丢掉分析记录（§3.4 说这是唯一不可恢复的破坏性动作）。**不要为了验证去删。**
处置：Expected 由 `EmptyWorkbench.test.tsx` 的 4 条用例覆盖（含「不承诺拖放/下载/网盘/授权书/即将」的文案纪律），手工这一步记为「已由自动测试覆盖，未在真机演练（避免破坏性操作）」。
若所有者愿意在**另一个数据目录**上跑（`DRAMACLIP_DATA_DIR` 指向空目录，见 ADR-009），则 Expected：主区整块变成居中的「还没有剧」+ 一句说明 + 唯一 primary「新增项目」，页头右上**不再有** primary，而今日待办仍在（新装机时它就是首启引导）。

- [ ] **Step 11: M10 同构对照（规格 §9.1）与 M11 控制台干净**

1. 依次截四页：工作台 / 成品库 / 引擎中心 / 偏好设置，两两并排。
   Expected（逐项核）：页头都是「22px 标题 + 12px 说明 + 右上动作槽」同一形状；分区标题都是「3px 渐变竖条 + 15px/600」；每屏 primary **至多 1 个**；纵向节奏只出现 20 或 24，不出现 14/18/22。
   > 已知不达标：`ProjectsPage`（页头「项目管理」是手写的，`:78-91`）与 `ProductionPage`（`:86-102`）。这两页归 P-3.2 重写，**本片不动**——照实记进 Step 12，不要为了让截图好看而越界改它们。
2. 打开 DevTools Console，刷一遍五个页面。
   Expected: **零红色报错**。特别地不得出现 `未知 RPC 方法: jobs.list`（那是 `desktop/main/ipc.ts:18` 在 `METHOD_NAMES` 白名单外的拒绝文案，出现即说明协议侧漏登记）。

- [ ] **Step 12: 把实测写回本文件**

在本文档末尾追加 `## Task 10 落地后的实测修正` 小节，逐条记录：
- M6 的三个数（`projects` / `works` / `export_jobs_all`）与芯片读数是否相符；
- M7 的失败任务待办**验到了还是没验到**（没验到要写明"本机无失败样本"）；
- M10 的四页同构对照里**哪几页仍不达标**（预期是 `ProjectsPage` 与 `ProductionPage`）；
- 计划里被证伪的假设（如有）——照 P-1.5 计划的体例，写"计划说 X，实测是 Y，改成了 Z"，不要悄悄改掉正文。

清理：关掉 dev server（`Ctrl+C`），确认没有残留的 Electron 进程。

- [ ] **Step 13: 提交**

```bash
cd /d/PersonProjects/DramaClip
git add docs/superpowers/plans/2026-09-12-p3-1-nav-shell-and-workbench.md
git commit -m "docs(plan): 记录 P-3.1 手工验收实测与偏差"
```

---

## 自查（写完计划后对着规格逐条核，发现的问题已就地修在正文里）

**1. 规格覆盖**——本片认领的条目逐项对照：

| 规格条目 | 落在哪 |
|---|---|
| §2.1 导轨分组 + `border/subtle` 分隔线 | Task 1（`navItems.ts` 的 `group` + `Rail.tsx` 的 `GroupDivider`） |
| §2.1 高亮规则（进单剧保持高亮） | Task 1（`isNavActive` 前缀匹配）+ Task 10 M3 |
| §2.1 高亮规则的第二处（`/engines/:tab`，本轮新发现） | Task 1 同上 + Task 9 Step 11 回写规格 |
| §2.1 的 8 项 | 本片落 5 项；「队列」P-2.5、「工具箱」P-3.4、「关于」P-3.6、「剧库」改名 P-3.2——**理由与归属写在 `navItems.ts` 的 docstring 里，不是漏掉** |
| §2.2 路由表与一次性重定向 | Task 2（表驱动 + `LegacyParamRedirect` 泛化，旧组件同期删除） |
| §2.2 `TimelineEditor` 删除 | 已完成（全库 grep 零命中），本片 Step 9 复验 |
| §3.2 色彩纪律 | `TodoList` 的 `DOT_COLOR` 只用 `status/*` 三色；`#FF4D4F` 全片不出现；Task 6 有断言 |
| §3.3 静默禁止（行 3「参数未生效」的同类逻辑） | Task 9：`jobs.list` 取不到时在跑芯片显示 `—` 且出一条 error 待办，不把"不知道"说成"没有" |
| §3.3.1 降级裁决表的界面可见性 | Task 3（三处假降级改口）+ Task 4（未配编剧模型的待办措辞把允许级与禁止级分开说） |
| §4.1 主区结构 | Task 8（待办 / 三芯片 / 最近成品 6 条 / 继续上次） |
| §4.1 待办是可执行动作 | Task 4（每条带 `action`）+ Task 6（`GhostAction`）+ Task 10 M7 |
| §4.1 空态 | Task 7（`EmptyWorkbench`）+ Task 8（primary 落点切换） |
| §4.1 删除的假文案 | 三条中两条已在 correctness 计划 Phase C 删过（实测 grep 0 命中）；本片删的是**第三类**（降级谎言）并钉成永久门禁（Task 3） |
| §4.1 右栏三块 | 环境就绪度 ✓、快速上手 ✓、**工具箱缺席**（Task 8 Step 3 删假面板，真工具箱属 P-3.4） |
| §9.1 页头同构 | Task 8（`HomePage` 改用 `PageShell`/`PageHeader`）+ Task 10 M10；`ProjectsPage`/`ProductionPage` 的手写页头**归 P-3.2**，已在 M10 记为已知不达标 |
| §9.5 假文案清零 | Task 3 的 `copyTruth.test.ts` 永久门禁（13 个被禁词，含合规红线） |
| DSS §1.2 禁非栅格间距 | Task 1（`22px 28px`→`20/24`、`gap 6`→`8`）、Task 3（`14`→`12`）、Task 8（`14`→`16`） |
| DSS §3.1 每屏 primary ≤1 | Task 7/8（空态与页头之间切换 primary 落点）+ Task 7 Step 3 有断言 |
| DSS §3.5 空态 | Task 7（图标 48 + 一句话 + primary），为此新增 `tokens.fontEmptyIcon` |
| DSS §6.3 `SectionTitle` 三种实现收敛 | Task 8 Step 2（删第三份）+ 删文件（另两份随 `SectionTitle.tsx`/`StartCards.tsx` 一起消失）+ Task 9 Step 9 复验 |

**未覆盖但已明确归属的**：§4.2 剧库（P-3.2）、§4.3 剧空间（P-3.2）、§4.4 队列（P-2.5）、§4.5 成品（P-3.3）、§4.6 设置分区（P-3.2，其中「存储/代理」需先立项）、§4.7 工具箱（P-3.4/P-3.5）、§4.8 关于（P-3.6）、§3.4 危险操作（P-3.2/P-3.3/P-3.4 各按归属）、§10 画面通道（批次 2）。

**2. 占位符扫描**——已就地修掉的三处（都留在正文里作为"不要照抄"的更正块，因为它们的错误形状本身有教学价值）：
- Task 7 Step 8 的 `ContinueCard.tsx` 末尾 `export { whenLabel }` 会触发 lint warning → 更正为移到 `relativeTime.ts`，并补全了该文件与其测试的完整内容。
- Task 8 Step 1 的 `HomePage.tsx` 有三处错：`failedJobs` 的形参类型缺 `status` 且带一个恒真过滤、`EnvPanel` 被喂了假参数、`gap: tokens.spaceMd + 2` 是非栅格值 → 三处都给了字面更正代码。
- Task 7 Step 7 的 `EmptyWorkbench` 用 `tokens.fontDisplay`（24px）冒充 DSS §3.5 要求的 48 → 更正为新增 `tokens.fontEmptyIcon`。

无 TBD、无"适当处理错误"、无"同 Task N"、无 `...（其余不变）...`。每个改代码的步骤都给了字面代码，每条命令都给了完整调用与期望输出。

**3. 类型一致性**——跨任务符号逐个核过：
- `TodoItem` / `TodoAction` / `DramaState` / `FailedJob` / `TodoInput`（Task 4 定义）→ Task 6 的 `TodoList` props、Task 8 的 `HomePage` 调用、Task 9 的 `TodoInput` 扩字段，四处签名一致。
- `WorkbenchStats` / `StatsInput` / `RunningJob`（Task 5 定义）→ Task 6 的 `StatChips` props、Task 8 的 `buildStats` 调用、Task 9 的扩字段，一致。
- `WORKS_SCAN_LIMIT`（Task 5 导出）→ Task 6 的 `useWorkbench` import，一致；`JOBS_SCAN_LIMIT` 只在 `useWorkbench.ts` 内定义与使用。
- `dramaEntryPath` / `dramaProducePath`（Task 2 定义）→ Task 7 的 `createDrama.ts`、Task 8 的 `ProjectsPage`/`TitleBar`、Task 2 的守卫测试，一致。
- `readLastDrama` / `rememberDrama` / `clearLastDrama`（Task 7 定义）→ Task 7 的测试与 `ContinueCard`、Task 8 的三个调用点，一致。
- `whenLabel`（Task 7 定义在 `relativeTime.ts`）→ `ContinueCard.tsx` import，一致。
- `JobInfo` / `JobsListResult`（Task 4 加进 `protocol/ts/index.ts`）→ Task 4 的 `jobsApi`、Task 6 的 `useWorkbench`、Task 8 的 `HomePage`，一致。
- `jobsAvailable` / `jobsError`（Task 9 新增）→ 同任务内 `stats.ts`/`todos.ts`/`useWorkbench.ts`/`StatChips.tsx`/`HomePage.tsx` 与三个测试文件的助手，一致。
- `folderName`（Task 7 定义）→ 只被 `createDrama.ts` 自己与 Task 7 的测试用；`ProjectsPage` **刻意不 import**（跨 feature 禁令，Task 8 Step 4 已说明）。

**4. 一处需要在执行时当场核对的假设**：Task 3 Step 2 期望 `copyTruth.test.ts` 恰好 4 条红。若 `desktop/src` 在本计划写就之后被他人改动，红的条数会变。**遇到不符就按当前文件内容重新核对，不要照抄本计划的行号与条数**（这条纪律来自 P-1.5 计划 Task 8 的实测修正：「凡代表真实工具输出的夹具一律现场捕获，不许从计划里抄」）。

---

## 完成判据（全部满足才算 P-3.1 收口）

1. `cd desktop && npx vitest run` 全绿，`Test Files  18 passed (18)` / `Tests  127 passed (127)`（含既有 16 条，一条不少）。
2. `cd desktop && npm run typecheck` 与 `npm run lint` 均零输出、退出码 0。
3. `cd desktop && npx vitest run src/__tests__/contract.test.ts` 仍绿——**证明本片没有动 `METHOD_NAMES`**。
4. Task 9 Step 9 的四条 grep 全部符合期望（死引用零残留、三份竖条标题收敛为一份、`restartService` 有消费者）。
5. Task 10 的 M1-M11 逐条走完并把读数写回本文件；无法手工验证的项**写明为什么无法验证**，不接受"应该没问题"。
6. `git status --short` 干净，且全程只用过显式路径的 `git add`。

## 已知不做 / 不在本片

- 「队列」「工具箱」「关于」三个导轨项与其页面（分别属 P-2.5、P-3.4、P-3.6）。
- `/projects`→`/dramas` 与 `/projects/:id/*`→`/drama/:id/*` 两组改名（P-3.2；且会波及属他人的 `features/analysis/`）。
- 「项目」标签不改「剧库」（理由见 Task 1 开头：§4.2 的页面内容要 P-2 的阶段聚合，只改名等于标签许诺页面没有的东西）。
- 待办的两个来源：「已分析未规划」（要 `project.list` 阶段聚合，P-2）、「队列失败任务」（`ref_id` 语义异构且落点是队列页，P-2.5）。
- 最近成品的钩帧缩略图（要 `export.set_cover` 与 `list_works` 增 `cover_path`，P-3.3）。
- §4.2 的首启三步空态（属剧库页，P-3.2）。工作台空态只做 §4.1 要求的「新增项目」引导。
- 修 `projects_repo.summary` 的 `export_count` 缺状态过滤（要改 `DashboardSummary` 形状 = 动 `protocol/`，与 P-2 撞车；已登记给 P-3.3）。
- `ProjectsPage`/`ProductionPage` 的手写页头收敛（随 P-3.2 的整页重写）。
- `desktop/src/features/analysis/**` 的任何改动（属另一位工程师）——包括 `StepsNav` 那套与新四阶段不同构的步骤条。
- `ProjectsPage.tsx:207` 与 `createDrama.folderName` 的目录名解析重复（跨 feature 禁令所限，登记给 P-3.2 上提）。
- §9.7 的规模实测：**今天连造数脚本都没有**（`scripts/` 下只有 build-service/dev/make_icon/verify_e2e/verify_modes/verify_sidecar）。建议作为 P-3.2 的 Task 0。
- 给导轨项加运行中条数角标（§4.4）与状态栏角标：落点是队列页，属 P-2.5。本片**不预留 badge 字段**——没有消费者的字段是投机设计。
