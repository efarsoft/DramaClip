// @vitest-environment node
/**
 * 文案真值门禁（规格 §9.5）+ 合规红线，四个扫描面各自一条红线词表：
 *   界面面 = 渲染层源码里的用户可见文案；
 *   门面面 = README 与安装包/应用元数据，外界看到的产品长相；
 *   文档面 = docs/ 工程文档；
 *   源码面 = 后端与脚本的 docstring/注释（仓库公开，注释同样面向读者）。
 * 带日期的决策留档 docs/superpowers/** 不在扫描面内——那里记录的是裁决本身，
 * 禁了它就等于把"为什么不许这样写"的证据一起删掉。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, describe, expect, it } from 'vitest';

const SRC_DIR = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const ROOT_DIR = path.resolve(SRC_DIR, '../..');

interface Phrase {
  readonly phrase: string;
  readonly reason: string;
}

/** 用户可见文案：不许有假承诺，也不许有合规红线词。 */
const UI_BANNED: readonly Phrase[] = [
  { phrase: '关键词降级', reason: '解说文案不降级；未配置编剧模型即逐条失败' },
  { phrase: '降级为关键词', reason: '同上' },
  { phrase: '自动降级', reason: '同上' },
  { phrase: '拖进来', reason: '拖放导入不存在' },
  { phrase: '拖拽导入', reason: '拖放导入不存在' },
  { phrase: '拖动文件', reason: '拖放导入不存在' },
  { phrase: '消重', reason: '合规红线：不得出现在用户可见文案里' },
  { phrase: '抗比对', reason: '合规红线：不得出现在用户可见文案里' },
  { phrase: '去重', reason: '合规红线：同上' },
  { phrase: '绕过平台', reason: '合规红线' },
  { phrase: '即将支持', reason: '未兑现承诺不得上界面' },
  { phrase: '敬请期待', reason: '同上' },
  { phrase: '后续版本', reason: '同上' },
];

/**
 * 门面是外界看到的唯一长相。185 万判例在前，"把轻微画面/音频处理说成
 * 对抗平台判定"和"承诺界面里根本没有的开关"都不许出现在这里。
 */
const MARKETING_BANNED: readonly Phrase[] = [
  { phrase: '消重', reason: '合规红线：不得作为卖点表述' },
  { phrase: '抗比对', reason: '合规红线：同上' },
  { phrase: '去重', reason: '合规红线：同上' },
  { phrase: '绕过平台', reason: '合规红线：同上' },
  { phrase: '同质化', reason: '合规红线：不得声称针对平台的重复判定起作用' },
  { phrase: '哈希', reason: '合规红线：指纹破坏类表述' },
  { phrase: '指纹', reason: '合规红线：同上' },
  { phrase: '排重', reason: '合规红线：同上' },
  { phrase: '特征向量', reason: '合规红线：特征破坏类表述' },
  { phrase: '可关闭', reason: '实测四项处理在 encoder 无条件注入，无开关可承诺' },
];

/** 文档与源码注释面：允许给子系统起名字（`消重` 是内部模块名），但不许写成"目的是对抗平台判定"。 */
const PURPOSE_BANNED: readonly Phrase[] = [
  { phrase: '像素哈希', reason: '反检测目的性表述：改成中性的处理事实' },
  { phrase: '色域哈希', reason: '同上' },
  { phrase: '指纹', reason: '同上' },
  { phrase: '特征向量', reason: '同上' },
  { phrase: '同质化', reason: '同上' },
  { phrase: '排重', reason: '同上' },
  { phrase: '抗比对', reason: '合规红线：任何面向读者的表述都不得出现' },
  { phrase: '绕过平台', reason: '合规红线：同上' },
  { phrase: '消重失效', reason: '合规红线：把对抗平台写成产品前提' },
];

const MARKETING_FILES = [
  'README.md',
  'service/README.md',
  'package.json',
  'desktop/package.json',
  'desktop/electron-builder.yml',
];

/** 第三方产物与只读封存目录不进任何扫描面。 */
const SKIP_DIRS = ['__pycache__', 'node_modules', '.venv', 'build', 'dist'];

function walkTree(dir: string, exts: readonly string[], extraSkip: readonly string[]): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.includes(entry) || extraSkip.includes(entry)) continue;
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walkTree(full, exts, extraSkip));
      continue;
    }
    if (exts.some((ext) => entry.endsWith(ext))) out.push(full);
  }
  return out;
}

function walkMarkdown(): string[] {
  // docs/superpowers/** 是带日期的计划与规格留档：里面记录着"为什么禁"，删不得
  return walkTree(path.join(ROOT_DIR, 'docs'), ['.md'], ['superpowers']);
}

function walkRenderer(): string[] {
  return walkTree(SRC_DIR, ['.ts', '.tsx'], ['__tests__']).filter(
    (file) => !/\.test\.tsx?$/.test(file),
  );
}

function walkCodeComments(): string[] {
  return [
    ...walkTree(path.join(ROOT_DIR, 'service'), ['.py'], []),
    ...walkTree(path.join(ROOT_DIR, 'desktop', 'main'), ['.ts'], []),
    ...walkTree(path.join(ROOT_DIR, 'scripts'), ['.mjs'], []),
  ];
}

interface Surface {
  readonly label: string;
  readonly files: () => string[];
  readonly base: string;
  readonly probe: string;
  readonly minFiles: number;
  readonly minPhrases: number;
  readonly banned: readonly Phrase[];
}

const SURFACES: readonly Surface[] = [
  {
    label: '界面文案',
    files: walkRenderer,
    base: SRC_DIR,
    probe: 'HomePage.tsx',
    minFiles: 20,
    minPhrases: 13,
    banned: UI_BANNED,
  },
  {
    label: '门面文案',
    files: () => MARKETING_FILES.map((rel) => path.join(ROOT_DIR, rel)),
    base: ROOT_DIR,
    probe: 'README.md',
    minFiles: 5,
    minPhrases: 10,
    banned: MARKETING_BANNED,
  },
  {
    label: '工程文档',
    files: walkMarkdown,
    base: ROOT_DIR,
    probe: '01-技术方案-原案.md',
    minFiles: 15,
    minPhrases: 9,
    banned: PURPOSE_BANNED,
  },
  {
    label: '源码注释',
    files: walkCodeComments,
    base: ROOT_DIR,
    probe: 'params.py',
    minFiles: 100,
    minPhrases: 9,
    banned: PURPOSE_BANNED,
  },
];

/** 一个扫描面只走盘一次、每个文件只读一次，所有红线词在同一趟里配好命中。
 *  原写法是「每条红线 × 全仓重扫」：源码注释面 300+ 文件 × 9 条 = 2700+ 次读盘。
 *  ⚠️ 但真正的红因不是重复遍历而是**冷盘首扫**——快照 `git archive` 全绿后重跑，
 *  第一个用例读满 300+ 文件花了 7.9s，直接顶穿 vitest 5s 默认超时（同一条用例
 *  热盘只要 40ms）。所以两条都要：单趟扫描把总量压到 1×，冷盘那一次由 SCAN_TIMEOUT
 *  兜住。二者缺一仍会红，afterAll 只兜得住前一条。 */
interface Scan {
  readonly files: readonly string[];
  readonly hits: ReadonlyMap<string, string[]>;
}

const SCAN_TIMEOUT_MS = 60_000;
const scans = new Map<string, Scan>();
const walkCounts = new Map<string, number>();
const readCounts = new Map<string, number>();

function scanOf(surface: Surface): Scan {
  const cached = scans.get(surface.label);
  if (cached !== undefined) return cached;
  walkCounts.set(surface.label, (walkCounts.get(surface.label) ?? 0) + 1);
  const files = surface.files();
  const hits = new Map<string, string[]>(surface.banned.map(({ phrase }) => [phrase, []]));
  for (const file of files) {
    readCounts.set(surface.label, (readCounts.get(surface.label) ?? 0) + 1);
    const rel = path.relative(surface.base, file);
    // 整档抹一遍空白，所有红线词共用这份正文——每词重抹一次会让读盘次数对不上文件数
    // 整档抹一遍空白，所有红线词共用这份正文——每词重抹一次会让读盘次数对不上文件数。
    // 判据必须是 phraseLines 那一套（夹具「句中折行探针」把它经 scanOf 再跑一遍真实文件）：
    // 换成逐行 includes 会让折行的红线词静默判绿，而语料本身零命中，从结果上看不出来。
    const body = compactText(readFileSync(file, 'utf8'));
    for (const { phrase } of surface.banned) {
      const list = hits.get(phrase);
      if (list === undefined) continue;
      for (const line of matchLines(body, phrase)) list.push(`${rel}:${String(line)}`);
    }
  }
  const scan: Scan = { files, hits };
  scans.set(surface.label, scan);
  return scan;
}

/**
 * 判据的单位是**整档正文**，不是行。中文可以在任意字符处断行：按列硬折的 markdown 会把
 * 一个红线词劈成两段，渲染出来照旧是那个词，逐行 `includes` 却一个字也看不见
 * （实测口径：docs/ 里有 6 处「跨行才拼得出六字纯中文串、任一行都不成立」的句中折行，
 * 这条路不需要刻意规避就能走到）。
 * 只抹空白，别的字符照旧是屏障：`# 绕` 换行 `# 过平台` 拼不成「绕过平台」，注释符挡在中间。
 * ⚠️ 因此红线词表里的词必须**不含空白**（含空白的词在抹掉空白的正文里永远配不上，
 * 会变成一条看不见的假绿）——本 describe 第二条用例钉着这条。
 * 下面三枚是这套判据的全部构件：Body = 抹掉空白后的正文 + 每个保留字符在原文里的偏移。
 */
interface Body {
  readonly text: string;
  readonly starts: readonly number[];
  readonly src: string;
}

function compactText(src: string): Body {
  const starts: number[] = [];
  let text = '';
  src.replace(/\S/g, (ch: string, offset: number) => {
    text += ch;
    starts.push(offset);
    return ch;
  });
  return { text, starts, src };
}

/** 命中按紧凑正文下标回查原文偏移，行号指得改的那一行（折行时是首字所在行）。 */
function matchLines(body: Body, phrase: string): number[] {
  const out: number[] = [];
  for (let from = 0; ; ) {
    const at = body.text.indexOf(phrase, from);
    if (at < 0) return out;
    out.push(lineAt(body.src, body.starts[at] ?? 0));
    from = at + phrase.length;
  }
}

/** 单档单词的入口，只有口径夹具走它；scanOf 为了「每文件只抹一次」自己串这两枚构件。 */
function phraseLines(src: string, phrase: string): number[] {
  return matchLines(compactText(src), phrase);
}

/** 数换行换算行号：整档匹配只有偏移，报告要指得改的那一行。 */
function lineAt(src: string, offset: number): number {
  let line = 1;
  for (let i = 0; i < offset; i += 1) if (src.charCodeAt(i) === 10) line += 1;
  return line;
}

describe('判据的单位是整档正文，不是行', () => {
  it('中文按列硬折不得把红线词劈成看不见的一段，行号按命中首字换算', () => {
    // 逐行 includes 的旧写法对第一段判绿：渲染出来仍是「绕过平台」，门禁却一个字也看不见。
    expect(phraseLines('本产品的目的是\n绕\n过平台的重复判定', '绕过平台')).toEqual([2]);
    expect(phraseLines('绕过平台', '绕过平台')).toEqual([1]);
    expect(phraseLines('绕过平台\n别的\n再绕\n过平台一次', '绕过平台')).toEqual([1, 3]);
    // 只抹空白，别的字符照旧挡在中间：两行各是各的注释，拼不成一个词
    expect(phraseLines('# 绕\n# 过平台', '绕过平台')).toEqual([]);
    expect(phraseLines("{ a: '绕',\n  b: '过平台' }", '绕过平台')).toEqual([]);
    expect(phraseLines('这一段是中性表述', '绕过平台')).toEqual([]);
    // 同一行两处各计一次：命中表要数得出位点，不是数行
    expect(phraseLines('绕过平台，以及绕过平台', '绕过平台')).toEqual([1, 1]);
  });

  it('红线词表不得含空白：抹掉空白的正文里带空白的词永远配不上，那是条静默假绿', () => {
    const spaced = SURFACES.flatMap((surface) =>
      surface.banned.filter(({ phrase }) => /\s/.test(phrase)).map(({ phrase }) => `${surface.label}·${phrase}`),
    );
    expect(spaced, `含空白的红线词在本判据下不可能命中：${spaced.join(', ')}`).toEqual([]);
  });

  it('句中折行探针走的是 scanOf 本身：换回逐行匹配即红', () => {
    // 上面两条只测得到 phraseLines——scanOf 若被改回 split('\n')，夹具照样绿、
    // 真扫描照样瞎（语料零命中，从结果上看不出任何异样）。这条把跨行词经生产路径跑一遍。
    const probe: Surface = {
      label: '折行探针',
      files: () => [path.join(SRC_DIR, '__tests__', 'fixtures', 'wrapped-copy.md')],
      base: SRC_DIR,
      probe: 'wrapped-copy.md',
      minFiles: 1,
      minPhrases: 1,
      banned: [{ phrase: '绕过平台', reason: '夹具专用：只以跨行形态在场' }],
    };
    const expected = `${path.join('__tests__', 'fixtures', 'wrapped-copy.md')}:8`;
    const hits = [...scanOf(probe).hits.values()].flat();
    expect(hits, `折行的红线词没被扫出来（命中行应为 ${expected}）：${hits.join(', ')}`).toEqual([expected]);
  });
});

describe('文案真值门禁', () => {
  for (const surface of SURFACES) {
    describe(surface.label, () => {
      // 自证下限：扫描面被悄悄删窄、红线词被摘掉，都要当场响，不能只少跑几个用例。
      // 超时同样要给这条：每个面都是它先跑，冷盘那一次全量扫描落在它头上——
      // 只给红线词用例抬超时，快照 `git archive` 干净检出下这条先顶穿 5s（实测 7.3s）。
      it('扫描面与红线词表不得缩水', () => {
        const files = scanOf(surface).files;
        expect(files.length, `${surface.label} 只扫到 ${String(files.length)} 个文件`).toBeGreaterThanOrEqual(surface.minFiles);
        expect(files.some((file) => file.endsWith(surface.probe)), `扫描面里没有 ${surface.probe}`).toBe(true);
        expect(surface.banned.length, `${surface.label} 红线词表缩水`).toBeGreaterThanOrEqual(surface.minPhrases);
      }, SCAN_TIMEOUT_MS);

      for (const { phrase, reason } of surface.banned) {
        it(`不得出现「${phrase}」`, () => {
          const hits = scanOf(surface).hits.get(phrase);
          expect(hits, `${phrase} —— ${reason}。命中：${(hits ?? []).join(', ')}`).toEqual([]);
        }, SCAN_TIMEOUT_MS);
      }
    });
  }

  it('免责声明原文保留——合规靠改文案，不靠删声明', () => {
    const readme = readFileSync(path.join(ROOT_DIR, 'README.md'), 'utf8');
    expect(readme).toContain('不提供规避原创性检测的功能');
  });

  afterAll(() => {
    // 三条各自挡一种退化：重复走盘（缓存被拆）、逐条重读（单趟被打回 per-phrase）、
    // 命中表与词表脱钩（加了红线词却没进扫描）。
    for (const surface of SURFACES) {
      const scan = scans.get(surface.label);
      expect(scan, `${surface.label} 从未被扫描——用例面被删窄`).toBeDefined();
      expect(walkCounts.get(surface.label), `${surface.label} 重复走盘`).toBe(1);
      expect(readCounts.get(surface.label), `${surface.label} 读盘次数不等于文件数：退化成逐条重扫`)
        .toBe(scan?.files.length);
      expect([...(scan?.hits.keys() ?? [])].sort(), `${surface.label} 命中表与红线词表脱钩`).toEqual(
        surface.banned.map(({ phrase }) => phrase).sort(),
      );
    }
  });
});
