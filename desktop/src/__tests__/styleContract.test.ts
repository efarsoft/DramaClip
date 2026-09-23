// @vitest-environment node
/**
 * 排版契约门禁·组件层与色值真相（规格 §2、§3.2、§3.4）。
 * token 表的形状在 typeContract.test.ts；这里断言的是 mixins 交给组件的**那份 style 对象**：
 * 行高必须能被内容顶开（固定 height 会裁掉折行的解说文案），三态必须各走各的通道。
 * §3.4 那半是全站源码扫描：色值只准出现在 theme.ts（阴影的唯一实现位在 mixins.ts）。
 * 度量台账与 token 归位在 measureContract.test.ts；两条门禁共用的扫描面在 scanSurface.ts。
 */
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { listRow } from '../styles/mixins';
import { layout, tokens } from '../styles/theme';
import { forEachHit, isComment, rendererFiles, sourceText, SRC_DIR } from './scanSurface';

describe('§2 列表行高统一', () => {
  it('单行档取 36、双行档取 52，且登记进 layout.row', () => {
    expect(listRow().minHeight).toBe(layout.row.single);
    expect(listRow({ rows: 2 }).minHeight).toBe(layout.row.double);
    expect(layout.row).toMatchObject({ single: 36, double: 52 });
  });

  it('纵向不留 padding——留了就顶破固定行高', () => {
    expect(listRow().padding).toBe(`0 ${tokens.spaceMd}`);
  });
});

describe('§3.2 三态分道', () => {
  it('已勾选只铺底，不给竖条', () => {
    const checked = listRow({ checked: true });
    expect(checked.background).toBe(tokens.checkedSoft);
    expect(checked.boxShadow).toBe('none');
  });

  it('当前查看只给竖条，不铺底', () => {
    const active = listRow({ active: true });
    expect(active.boxShadow).toBe(`inset ${String(layout.sectionBar.width)}px 0 0 ${tokens.colorPrimary}`);
    expect(active.background).toBe('transparent');
  });

  it('两态同时在场时两条通道都在（调用方负责别把它们叠给同一行）', () => {
    const both = listRow({ checked: true, active: true });
    expect(both.background).toBe(tokens.checkedSoft);
    expect(both.boxShadow).not.toBe('none');
  });
});

/**
 * §3.4 色值单一真相：四条禁令扫全部渲染层源码。
 * 豁免面只有两个，且都写清理由——theme.ts 是真相源本身；mixins.ts 是状态光晕的
 * 唯一实现位（statusDot），组件里再手抄一遍正是本条要收的东西。
 */
const OWN_TRUTH = ['styles' + path.sep + 'theme.ts', 'styles' + path.sep + 'mixins.ts'];

const COLOUR_BANS: readonly { readonly rule: string; readonly re: RegExp }[] = [
  { rule: 'hex 字面量', re: /#[0-9A-Fa-f]{3,8}\b/g },
  { rule: 'rgb()/rgba() 字面量', re: /\brgba?\(/g },
  { rule: 'token 拼 alpha 的模板串', re: /\$\{tokens\.[A-Za-z]+\}[0-9A-Fa-f]{2}/g },
  // 'none' 是重置不是色板位点（规格 §3.4 明写「写清哪些不算，门禁才不会变成数字游戏」）。
  // \s* 在整档文本里可以跨过换行，所以属性名与值折行也算命中——§8.3 与 §1.3 同理。
  { rule: '组件内手写 boxShadow 字面量', re: /boxShadow:\s*(?!['"`]none['"`])['"`]/g },
];

/** 一个文件里的色值违例（§3.4 四条禁令）。返回 `行号 规则 —— 原文`，由 colourHits 补文件名。 */
function colourBanHits(text: string): string[] {
  const hits: string[] = [];
  for (const { rule, re } of COLOUR_BANS) {
    forEachHit(text, re, (_m, line, rawLine) => {
      if (isComment(rawLine)) return;
      hits.push(`${String(line)} ${rule} —— ${rawLine.trim()}`);
    });
  }
  return hits;
}

function colourHits(): string[] {
  const hits: string[] = [];
  for (const file of rendererFiles()) {
    const rel = path.relative(SRC_DIR, file);
    if (OWN_TRUTH.some((own) => rel.endsWith(own))) continue;
    hits.push(...colourBanHits(sourceText(file)).map((h) => `${rel}:${h}`));
  }
  return hits;
}

describe('§3.4 色值单一真相（扫描面 = 渲染层全部 .ts/.tsx，theme/mixins 除外）', () => {
  it('扫描面不得缩水：至少覆盖全部渲染层且真扫到扫描目标', () => {
    const files = rendererFiles();
    expect(files.length).toBeGreaterThanOrEqual(60);
    expect(files.some((f) => f.endsWith(path.join('features', 'works', 'WorksPage.tsx')))).toBe(true);
    expect(files.some((f) => f.endsWith('machineFit.ts'))).toBe(true);
  });

  it('四条禁令零命中', () => {
    const hits = colourHits();
    expect(hits, `色值散在组件里（应在 theme.ts）：\n${hits.join('\n')}`).toEqual([]);
  });

  it('禁令的单位是属性赋值：值折到下一行照样命中', () => {
    // boxShadow 那条锚在属性名上：名值分行时逐行扫描看不见值，折行即可静默绕过。
    expect(colourBanHits("{ boxShadow: 'inset 0 2px 8px currentColor' }")).toHaveLength(1);
    expect(colourBanHits("{\n  boxShadow:\n    'inset 0 2px 8px currentColor',\n}")).toHaveLength(1);
    // 'none' 是重置不是色板位点，折行不改变这一点
    expect(colourBanHits("{\n  boxShadow:\n    'none',\n}")).toHaveLength(0);
    // 值锚定的三条（hex / rgba / 模板拼 alpha）扫的是值本身，折行藏不住——写成断言防日后改窄
    expect(colourBanHits("{\n  background:\n    'rgba(0,0,0,0.72)',\n}")).toHaveLength(1);
    expect(colourBanHits("{\n  color:\n    '#34D399',\n}")).toHaveLength(1);
  });

  it('…Soft 阶梯三枚齐备，组件侧不得再有第五种 alpha 拼色', () => {
    expect(tokens.successSoft).toBe('rgba(52,211,153,0.12)');
    expect(tokens.warningSoft).toBe('rgba(251,191,36,0.12)');
    expect(tokens.errorSoft).toBe('rgba(248,113,113,0.12)');
    // 软底与本体同色相：换 alpha 前先看 hex 对不对得上，否则 Soft 阶梯是第二套色板
    expect(tokens.successSoft).toContain('52,211,153');
    expect(tokens.colorSuccess).toBe('#34D399');
  });

  it('海报黑底与浮板各一枚，渐变只此一份', () => {
    expect(tokens.posterBase).toBe('#000000');
    expect(tokens.posterScrim).toBe('linear-gradient(180deg, rgba(0,0,0,0) 50%, rgba(0,0,0,0.68) 100%)');
    expect(tokens.posterCaption).toBe('rgba(0,0,0,0.72)');
    expect(tokens.posterPlate).toBe('rgba(0,0,0,0.55)');
  });
});
