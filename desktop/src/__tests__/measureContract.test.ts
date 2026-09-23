// @vitest-environment node
/**
 * 排版契约门禁·字面量台账与 token 归位（规格 §8.3、§1.3）。
 * 与 styleContract.test.ts 共用 scanSurface.ts 的同一份扫描面：那边管色值只准在 theme.ts，
 * 这边管间距/行高字面量的**逐文件债务对账**，以及 tokens.text.* / tokens.glyph.* 只准落在自己的属性位。
 */
import { describe, expect, it } from 'vitest';
import { forEachHit, isComment, relPath, rendererFiles, sourceText } from './scanSurface';

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

/** 单个文件里的字面量度量位点数。台账与口径夹具共用这份实现，夹具才测得到真判据。 */
function countMeasure(text: string): number {
  let hits = 0;
  forEachHit(text, MEASURE_RE, (m, _line, rawLine) => {
    if (isComment(rawLine)) return;
    if (literalMeasure(m[2]?.trim() ?? '')) hits += 1;
  });
  return hits;
}

function measureDebt(): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const file of rendererFiles()) {
    const rel = relPath(file);
    if (rel.startsWith('styles/')) continue;
    const hits = countMeasure(sourceText(file));
    if (hits > 0) counts[rel] = hits;
  }
  return counts;
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
  'features/narration/ExportsCard.tsx': 1,
  'features/narration/StyleSelectCard.tsx': 1,
  'features/settings/SettingsPage.tsx': 1,
};

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

  it('扫描单位是属性赋值，不是整行：折行的属性名与值同样计位', () => {
    // 值太长时属性名与值会分到两行（这是正常写法，不需要谁刻意规避）。逐行版对第一段判绿：
    // 一条真字面量藏在折行里，棘轮就静默失效了。
    expect(countMeasure("style={{\n  padding:\n    '10px 14px',\n}}")).toBe(1);
    // 一行里两个位点各算一次：台账记的是位点数，不是行数
    expect(countMeasure('{ marginTop: 6, gap: 4 }')).toBe(2);
    // 注释行不计（与 §3.4 同一条豁免）；token 引用折行仍是正解
    expect(countMeasure("// padding: '10px 14px',\n/* gap: 4 */")).toBe(0);
    expect(countMeasure('{\n  padding:\n    tokens.spaceMd,\n}')).toBe(0);
  });

  it('扫描面不得缩水：债务表非空且真扫到已知债文件', () => {
    const found = measureDebt();
    // 下限随合法还债下移（只减不增，§8.3）：P-B2 把 RecentWorks/StatChips/ContinueCard
    // 三块吸收进 DramaMatrix，P-B3 把 ProjectCard 重写成零字面量的 DramaCard，22 → 18；
    // P-D 重写 WorksPage（拆成 worksView/WorkCard 等）与 WorksDetailPage 归零，18 → 16。
    // 它防的是扫描面被删窄，不是禁止还债——逐文件对账在下面那条，才是真棘轮。
    expect(Object.keys(found).length).toBeGreaterThanOrEqual(16);
    expect(found, 'EnvPanel 的 6 处是最密的一屏，扫不到就是扫描面被删窄').toHaveProperty(
      'features/home/EnvPanel.tsx',
      6,
    );
  });

  it('债务逐文件对账——新增字面量、债务不降、迁完仍挂账，三种都算红', () => {
    const found = measureDebt();
    expect(found, `实测：\n${JSON.stringify(found, null, 2)}`).toEqual(MEASURE_DEBT);
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
  // §3.2「当前查看」通道的加粗档（theme.ts text.body/badge 实有字段）：属性位与 weight 同
  weightActive: ['fontWeight'],
};
const GLYPH_PROPS = ['fontSize', 'width', 'height'] as const;
const PLACEMENT_RE = /(?:^|[{,\s])([A-Za-z]+)\s*:\s*tokens\.(text|glyph)\.([A-Za-z]+)(?:\.([A-Za-z]+))?/g;

/** 一个文件里的命名空间串位（§1.3 矩阵）。返回 `行号 原文 —— 说明`，由 placementHits 补文件名。 */
function placementViolations(text: string): string[] {
  const hits: string[] = [];
  forEachHit(text, PLACEMENT_RE, (m, line, rawLine) => {
    if (isComment(rawLine)) return;
    const [, prop, ns, tier, field] = m;
    if (prop === undefined || ns === undefined || tier === undefined) return;
    const allowed = ns === 'glyph' ? (GLYPH_PROPS as readonly string[]) : TEXT_FIELDS[field ?? ''] ?? [];
    if (!allowed.includes(prop)) {
      hits.push(
        `${String(line)} ${rawLine.trim()} —— ${ns}.${tier}${field ? `.${field}` : ''} 不得出现在 ${prop} 上`,
      );
    }
  });
  return hits;
}

function placementHits(): string[] {
  const hits: string[] = [];
  for (const file of rendererFiles()) {
    const rel = relPath(file);
    if (rel.startsWith('styles/')) continue;
    hits.push(...placementViolations(sourceText(file)).map((h) => `${rel}:${h}`));
  }
  return hits;
}

describe('§1.3 命名空间只准出现在自己的属性位', () => {
  it('串位判据的单位是属性赋值：值折行藏不住，token 正确用法不误报', () => {
    expect(placementViolations('{ borderRadius: tokens.text.body.size }')).toHaveLength(1);
    expect(placementViolations('{\n  borderRadius:\n    tokens.text.body.size,\n}')).toHaveLength(1);
    expect(placementViolations('{\n  borderRadius:\n    tokens.radiusControl,\n}')).toHaveLength(0);
    expect(placementViolations('{ fontSize: tokens.glyph.iconLg }')).toHaveLength(0);
  });

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
 * 所以这一条**故意**逐行扫（上面三条的整档扫描器在这里是错的）：判据单位就是「同一行」。
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
    sourceText(file)
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
