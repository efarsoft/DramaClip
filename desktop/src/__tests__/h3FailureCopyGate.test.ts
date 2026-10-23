// @vitest-environment node
/** H3 门禁 3（规格 §4.3）：行级失败原因必须在可见文本里；`…` 只准出现在还活着的过程里。
 *
 * 两条都是「同一个记号同时表示两种终态」的复发面：
 * ① 失败原因只在 `Tooltip`/`title` 里、可见文本只剩「原因」两个字——不点上去就没有账
 *    （出片行 2026-10-22 前就是这个形状，档1 规格 §3.3 判过违规却没拦住）；
 * ② `…` 既当「还在测」又当「测不到」——catch 吞掉之后页面永远挂着省略号，
 *    用户读到「马上就出」，真相是「这一屏答不上来」。
 *
 * 判据是清单式穷举（不是通配正则）：新增一处失败态或占位符，必须先在账本里登记
 * 「它在可见文本里说什么」「它凭什么算还在测」，扫描面复用 `scanSurface.rendererFiles()`。
 */
import { describe, expect, it } from 'vitest';
import { relPath, rendererFiles, sourceText } from './scanSurface';

/** 失败原因位点账本：`visible` 必须命中「原因文本作为 JSX 子节点」的写法。 */
const REASON_LEDGER: readonly { readonly file: string; readonly visible: RegExp; readonly why: string }[] = [
  {
    file: 'features/analysis/EpisodeListRow.tsx',
    visible: /失败原因：\$\{error\}/,
    why: '集行的失败原因原文（库里没记也要说出来）',
  },
  {
    file: 'features/engines/AssetRow.tsx',
    visible: /\{failed\}/,
    why: '资产行的下载失败原话',
  },
  {
    file: 'features/engines/AsrTab.tsx',
    visible: /cardStateNote\(state, report, download\)/,
    why: '活动卡状态位复用同一条下载失败原话',
  },
  {
    file: 'features/engines/TtsTab.tsx',
    visible: /cardStateNote\(state, report, download\)/,
    why: '活动卡状态位复用同一条下载失败原话',
  },
  {
    file: 'features/engines/VisionTab.tsx',
    visible: /cardStateNote\(state, report, download\)/,
    why: '活动卡状态位复用同一条下载失败原话',
  },
  {
    file: 'features/engines/LocalRuntimeSlot.tsx',
    visible: /\{state\.installProblem\}/,
    why: '运行环境槽的安装失败原话常驻',
  },
  {
    file: 'features/engines/LocalRuntimeSlot.tsx',
    visible: /探测失败（\$\{state\.probeProblem\}）/,
    why: '探测取不到要说「状态未知 + 原话」',
  },
  {
    file: 'features/narration/ExportsCard.tsx',
    visible: /\{failureNote\}/,
    why: '出片行（含重试再失败）的原因常驻',
  },
  {
    file: 'features/settings/SettingsPage.tsx',
    visible: /\{spec\.problem\.text\}/,
    why: '目录类选项取不到时的故障行',
  },
  {
    file: 'features/engines/MachinePanel.tsx',
    visible: /本机信息取不到：\$\{healthProblem\}/,
    why: 'health 取不到时的原因行',
  },
  {
    file: 'features/about/AboutPage.tsx',
    visible: /取不到：\$\{problem\}/,
    why: '版本行取不到时的原因（同处给重试）',
  },
  {
    file: 'features/home/EnvPanel.tsx',
    visible: /探测失败：\$\{runtime\.problem\}/,
    why: '环境行的探测失败原话',
  },
  {
    file: 'features/home/TodoList.tsx',
    visible: /\{detail\}/,
    why: '待办的作业失败原因原文常驻第二行',
  },
];

/** `…` 账本：每处占位符都要说得出「它凭什么还算还在测」。 */
const ELLIPSIS_LEDGER: readonly { readonly file: string; readonly count: number; readonly guards: readonly RegExp[] }[] = [
  { file: 'features/about/AboutPage.tsx', count: 1, guards: [/problem === ''/] },
  { file: 'features/analysis/WorkbenchHeader.tsx', count: 1, guards: [/project\?\.name \?\?/] },
  { file: 'features/engines/MachinePanel.tsx', count: 2, guards: [/probing/] },
  {
    file: 'features/home/EnvPanel.tsx',
    count: 2,
    guards: [/models === null/, /runtime\.ok === null/],
  },
  { file: 'features/narration/ProductionPage.tsx', count: 1, guards: [/projectName \?\?/] },
  { file: 'features/works/useWorkDetail.ts', count: 1, guards: [/useState\('…'\)/] },
  { file: 'features/works/WorksDetailPage.tsx', count: 1, guards: [/detail\.job === null/] },
];

function byFile(): Map<string, string> {
  const out = new Map<string, string>();
  for (const file of rendererFiles()) out.set(relPath(file), sourceText(file));
  return out;
}

describe('H3 门禁 3a：失败原因必须在可见文本（规格 §4.3）', () => {
  const texts = byFile();

  it('账本里每一处的原话都渲染成 JSX 子节点', () => {
    const missing = REASON_LEDGER.filter((site) => {
      const text = texts.get(site.file);
      return text === undefined || !site.visible.test(text);
    }).map((site) => `${site.file}：${site.why}`);
    expect(missing, `失败原因不在可见文本里（进了 Tooltip 就等于没写）：\n${missing.join('\n')}`).toEqual([]);
  });

  it('全站不许再出现「原因」二字当独立标签的占位写法', () => {
    const hits: string[] = [];
    for (const [rel, text] of texts) {
      // 原话进 Tooltip、可见文本只留「原因」，就是出片行改前的形状
      for (const line of text.split('\n')) {
        if (/>\s*原因\s*</.test(line)) hits.push(`${rel}: ${line.trim()}`);
      }
    }
    expect(hits, `可见文本又把原话咽回 Tooltip：\n${hits.join('\n')}`).toEqual([]);
  });
});

describe('H3 门禁 3b：省略号只准表示还在测（规格 §3.3）', () => {
  const texts = byFile();

  it('每一处 `' + "'…'" + '` 都在账本里，且数量不多不少', () => {
    const found = new Map<string, number>();
    for (const [rel, text] of texts) {
      const n = (text.match(/'…'/g) ?? []).length;
      if (n > 0) found.set(rel, n);
    }
    const expected = new Map(ELLIPSIS_LEDGER.map((site) => [site.file, site.count]));
    for (const [rel, n] of found) {
      expect(expected.get(rel) ?? 0, `${rel} 出现 ${String(n)} 处 '…'，账本里没有这一处或数量不符`).toBe(n);
    }
    for (const [rel, n] of expected) {
      expect(found.get(rel) ?? 0, `${rel} 账本登记 ${String(n)} 处 '…'，实得不同`).toBe(n);
    }
  });

  it('每一处 `' + "'…'" + '` 都由在飞条件守着（终局无数必须换 —）', () => {
    const bad: string[] = [];
    for (const site of ELLIPSIS_LEDGER) {
      const text = texts.get(site.file);
      if (text === undefined) {
        bad.push(`${site.file}：文件不见了`);
        continue;
      }
      const lines = text.split('\n');
      lines.forEach((line, index) => {
        if (!line.includes("'…'")) return;
        const window = lines.slice(Math.max(0, index - 2), index + 1).join('\n');
        if (!site.guards.some((guard) => guard.test(window))) {
          bad.push(`${site.file}:${String(index + 1)} ${line.trim()}`);
        }
      });
    }
    expect(bad, `这些 '…' 已经没有「还在测」的条件守着：\n${bad.join('\n')}`).toEqual([]);
  });
});
