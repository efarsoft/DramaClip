// @vitest-environment node
/**
 * 排版契约门禁·站点层（规格 §2、§3.2、§3.4）。
 * token 表的形状在 typeContract.test.ts；这里断言的是 mixins 交给组件的**那份 style 对象**：
 * 行高必须能被内容顶开（固定 height 会裁掉折行的解说文案），三态必须各走各的通道。
 * §3.4 那半是全站源码扫描：色值只准出现在 theme.ts（阴影的唯一实现位在 mixins.ts）。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { listRow } from '../styles/mixins';
import { layout, tokens } from '../styles/theme';

const SRC_DIR = path.resolve(fileURLToPath(new URL('..', import.meta.url)));

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
 * 注释行不计位点：`#FF4D4F` 的禁令本身就写在注释里（EpisodeListRow、TodoList）。
 */
const OWN_TRUTH = ['styles' + path.sep + 'theme.ts', 'styles' + path.sep + 'mixins.ts'];

const COLOUR_BANS: readonly { readonly rule: string; readonly re: RegExp }[] = [
  { rule: 'hex 字面量', re: /#[0-9A-Fa-f]{3,8}\b/ },
  { rule: 'rgb()/rgba() 字面量', re: /\brgba?\(/ },
  { rule: 'token 拼 alpha 的模板串', re: /\$\{tokens\.[A-Za-z]+\}[0-9A-Fa-f]{2}/ },
  // 'none' 是重置不是色板位点（规格 §3.4 明写「写清哪些不算，门禁才不会变成数字游戏」）
  { rule: '组件内手写 boxShadow 字面量', re: /boxShadow:\s*(?!['"`]none['"`])['"`]/ },
];

function isComment(line: string): boolean {
  const t = line.trimStart();
  return t.startsWith('//') || t.startsWith('*') || t.startsWith('/*');
}

function rendererFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (entry === '__tests__' || entry === 'node_modules') continue;
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (/\.tsx?$/.test(entry) && !entry.includes('.test.')) {
        out.push(full);
      }
    }
  };
  walk(SRC_DIR);
  return out;
}

function colourHits(): string[] {
  const hits: string[] = [];
  for (const file of rendererFiles()) {
    const rel = path.relative(SRC_DIR, file);
    if (OWN_TRUTH.some((own) => rel.endsWith(own))) continue;
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, index) => {
        if (isComment(line)) return;
        for (const { rule, re } of COLOUR_BANS) {
          if (re.test(line)) hits.push(`${rel}:${String(index + 1)} ${rule} —— ${line.trim()}`);
        }
      });
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

/**
 * §8.3 度量字面量。口径写在 literalMeasure 里且**不再改**（§8.2：改口径 = 重测全部基线）：
 * 先把 `${…}` 插值整段抹掉（`` `0 ${tokens.spaceMd}` `` 是拼 token 不是字面尺度），
 * 再抹掉百分比（相对容器，不是尺度）与 0 位（`padding: 0`、`marginLeft: 'auto'` 是重置/推挤），
 * 剩下还有数字的才是违例。属性范围按 §8.3 列举：padding* / margin* / gap / lineHeight，
 * **不含** top/left/right/bottom——定位内缩不是间距档位，纳进来只会逼人造 token 名。
 */
const MEASURE_PROPS = [
  'padding', 'paddingTop', 'paddingBottom', 'paddingLeft', 'paddingRight', 'paddingInline', 'paddingBlock',
  'margin', 'marginTop', 'marginBottom', 'marginLeft', 'marginRight', 'marginInline', 'marginBlock',
  'gap', 'rowGap', 'columnGap', 'lineHeight',
];
const MEASURE_RE = new RegExp(`(?:^|[{,\\s])(${MEASURE_PROPS.join('|')})\\s*:\\s*([^,}]+)`, 'g');

function literalMeasure(raw: string): boolean {
  const rest = raw
    // token 引用先整段抹掉：space2xl / space3xl 这类档名的名字里带数字，不抹就是把档名当字面量
    .replace(/\b(?:tokens|layout)\.[A-Za-z0-9.]+/g, ' ')
    // `\$\{[^}]*` 不要求闭合括号：值里有 `}` 时上面那条捕获会在它前面截断
    .replace(/\$\{[^}]*/g, ' ')
    .replace(/-?\d+(?:\.\d+)?%/g, ' ')
    .replace(/(?<![\d.])0+(?![\d.%])/g, ' ');
  return /\d/.test(rest);
}

function relPath(file: string): string {
  return path.relative(SRC_DIR, file).split(path.sep).join('/');
}

/**
 * 债务表：文件 → 该文件当前的字面量度量处数。逐文件精确对账，不写「至少」——
 * 「至少」让债可以在文件内部涨，也让迁完的文件继续挂在表上冒充还在还债。
 * 还债协议（§8.3「一碰就必须归零」）：动到某个参照页时，把该屏的字面量清干净并从表里
 * 删掉整行；只减不增。值不在阶梯上（2px 微间隙、'1px 6px' 芯片内边距）不是留着字面量的
 * 理由——按 layout.chip 的先例登记成具名值，而不是新造一档。
 */
const MEASURE_DEBT: Readonly<Record<string, number>> = {
  'features/home/EnvPanel.tsx': 6,
  'features/home/RecentWorks.tsx': 3,
  'features/works/WorksPage.tsx': 3,
  'features/analysis/EpisodeListPanel.tsx': 2,
  'features/analysis/StepsNav.tsx': 2,
  'features/analysis/TranscriptCard.tsx': 2,
  'features/engines/CloudConfigSection.tsx': 2,
  'features/analysis/CurveCard.tsx': 1,
  'features/engines/ActiveEngineCard.tsx': 1,
  'features/engines/AssetRow.tsx': 1,
  'features/engines/IndexttsRuntimeSlot.tsx': 1,
  'features/engines/LlmTab.tsx': 1,
  'features/engines/MachinePanel.tsx': 1,
  'features/engines/ReadinessCard.tsx': 1,
  'features/engines/TtsPreviewButton.tsx': 1,
  'features/home/ContinueCard.tsx': 1,
  'features/home/StatChips.tsx': 1,
  'features/narration/ExportsCard.tsx': 1,
  'features/narration/StyleSelectCard.tsx': 1,
  'features/project/ProjectCard.tsx': 1,
  'features/settings/SettingsPage.tsx': 1,
  'features/works/WorksDetailPage.tsx': 1,
};

function measureDebt(): Record<string, number> {
  const counts = new Map<string, number>();
  for (const file of rendererFiles()) {
    const rel = relPath(file);
    if (rel.startsWith('styles/')) continue;
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line) => {
        if (isComment(line)) return;
        for (const m of line.matchAll(MEASURE_RE)) {
          if (!literalMeasure(m[2]?.trim() ?? '')) continue;
          counts.set(rel, (counts.get(rel) ?? 0) + 1);
        }
      });
  }
  return Object.fromEntries(counts);
}

describe('§8.3 度量口径与棘轮', () => {
  // 口径先用例钉住，再用它扫全站：口径若被人顺手放宽，这几条先红
  it('拼 token 的模板串与结构值不算字面量', () => {
    for (const ok of [
      'tokens.space2xl',
      'tokens.spaceXs',
      'layout.chip.paddingBlock',
      '0 ${tokens.spaceMd}',
      '${tokens.spaceMd} ${tokens.spaceLg}',
      '0 -${tokens.space2xl}',
      '${layout.chip.paddingBlock}px ${layout.chip.paddingInline}',
      // `${…}` 里是计算值不是字面量，插值段整体不参与判据（含带数字的表达式）
      '${count}px',
      '${index + 1}px',
      'auto',
      'none',
      '0',
      '50%',
    ]) {
      expect(literalMeasure(ok), `${ok} 被误判为字面量`).toBe(false);
    }
  });

  it('带 px 的简写与裸数值都是字面量', () => {
    for (const bad of ['1px 6px', '10px 0 4px', '0 10px', '2', '7', '1.5']) {
      expect(literalMeasure(bad), `${bad} 被判为结构值`).toBe(true);
    }
  });

  it('扫描面不得缩水：债务表非空且真扫到已知债文件', () => {
    const found = measureDebt();
    expect(Object.keys(found).length).toBeGreaterThanOrEqual(20);
    expect(found, 'EnvPanel 的 6 处是最密的一屏，扫不到就是扫描面被删窄').toHaveProperty(
      'features/home/EnvPanel.tsx',
      6,
    );
  });

  it('债务逐文件对账——新增字面量、债务不降、迁完仍挂账，三种都算红', () => {
    expect(measureDebt(), `实测：\n${JSON.stringify(measureDebt(), null, 2)}`).toEqual(MEASURE_DEBT);
  });
});

/**
 * §1.3 命名空间↔属性位矩阵：字段决定它出现在哪个属性上。
 * text.* 是 {size, leading, weight, weightLatin} 四件套，glyph.* 是图形/图标尺寸标量。
 * styles/ 整层豁免：那一层的工作就是把字阶组合成行高与块尺寸（mixins.ts:45 的
 * minHeight 取 cardTitle.leading 是契约本身，不是串位），与 §3.4 的 OWN_TRUTH 同界。
 */
const TEXT_FIELDS: Readonly<Record<string, readonly string[]>> = {
  size: ['fontSize'],
  leading: ['lineHeight'],
  weight: ['fontWeight'],
  weightLatin: ['fontWeight'],
};
const GLYPH_PROPS = ['fontSize', 'width', 'height'] as const;
const PLACEMENT_RE = /(?:^|[{,\s])([A-Za-z]+)\s*:\s*tokens\.(text|glyph)\.([A-Za-z]+)(?:\.([A-Za-z]+))?/g;

function placementHits(): string[] {
  const hits: string[] = [];
  for (const file of rendererFiles()) {
    const rel = relPath(file);
    if (rel.startsWith('styles/')) continue;
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, index) => {
        if (isComment(line)) return;
        for (const m of line.matchAll(PLACEMENT_RE)) {
          const [, prop, ns, tier, field] = m;
          if (prop === undefined || ns === undefined || tier === undefined) continue;
          const allowed =
            ns === 'glyph'
              ? (GLYPH_PROPS as readonly string[])
              : TEXT_FIELDS[field ?? ''] ?? [];
          if (!allowed.includes(prop)) {
            hits.push(`${rel}:${String(index + 1)} ${line.trim()} —— ${ns}.${tier}${field ? `.${field}` : ''} 不得出现在 ${prop} 上`);
          }
        }
      });
  }
  return hits;
}

describe('§1.3 命名空间只准出现在自己的属性位', () => {
  it('text.* 按字段定位、glyph.* 只当图标与图形尺寸', () => {
    const hits = placementHits();
    expect(hits, `命名空间串位（§8.3 的机检形式）：\n${hits.join('\n')}`).toEqual([]);
  });
});

/**
 * §1.3 反向 mono 判据（规格 §1.3 第 3 条：「span 内含中文则不得带 fontFamilyMono」）。
 * mono 栈无中文字面，整段混排会让中文掉进 Windows 通用等宽映射（宋体一路），比不套更差——
 * 所以口径是「数字与单位单独成 span，中文留在界面字体里」。两点边界必须写明：
 *   ① 只判**同一行内**的字面中文：跨行 JSX 文本与变量内容（`{draft}`、用户提示词正文）
 *      够不着，那是数据不是标签，本就不在判据内；机器判据到不了的地方走 §8.2 成对截图。
 *   ② 只判 style 里出现 fontFamilyMono 的行，与 ① 同才成立。
 */
// 只收 mono 真缺的三段：CJK 标点（U+3000 起）、汉字、全角形式。弯引号与省略号不收——
// JetBrains Mono 有这三枚码位，AboutPage:134 的空值占位 `…` 就是被误判的一条，
// 判据宽过头会逼人绕开门禁。码位写转义不写字面：行首空格写进字符类会被 lint 判违规空白。
const CJK_RE = /[\u3000-\u303F\u4E00-\u9FFF\uFF00-\uFFEF]/;
const MONO_RE = /fontFamily:\s*tokens\.fontFamilyMono/;

function monoHits(): string[] {
  const hits: string[] = [];
  for (const file of rendererFiles()) {
    const rel = relPath(file);
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, index) => {
        if (isComment(line)) return;
        if (MONO_RE.test(line) && CJK_RE.test(line)) hits.push(`${rel}:${String(index + 1)} ${line.trim()}`);
      });
  }
  return hits;
}

describe('§1.3 mono 只包数字（中文标签不得与 fontFamilyMono 同处）', () => {
  it('口径成立：中文单位混排在同一行即为命中', () => {
    expect(CJK_RE.test('共 12 集 · 下载中 45%')).toBe(true);
    expect(CJK_RE.test('1.2 MB')).toBe(false);
    expect(CJK_RE.test('01:23')).toBe(false);
    // 三段各自单独钉一次：只留汉字段时，下面两条会红，范围被顺手收窄就当场响
    expect(CJK_RE.test('《》')).toBe(true);
    expect(CJK_RE.test('：')).toBe(true);
    // 反向：这三枚 JetBrains Mono 有字形，收进来就是逼人和门禁绕着走（AboutPage:134 实测）
    expect(CJK_RE.test('…”“·')).toBe(false);
  });

  it('全站零命中', () => {
    const hits = monoHits();
    expect(hits, `中文与 mono 同处一行（mono 栈无汉字字形）：\n${hits.join('\n')}`).toEqual([]);
  });
});

