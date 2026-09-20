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
import { describe, expect, it } from 'vitest';

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

function hitsIn(surface: Surface, phrase: string): string[] {
  const hits: string[] = [];
  for (const file of surface.files()) {
    const lines = readFileSync(file, 'utf8').split('\n');
    lines.forEach((line, index) => {
      if (line.includes(phrase)) hits.push(`${path.relative(surface.base, file)}:${String(index + 1)}`);
    });
  }
  return hits;
}

describe('文案真值门禁', () => {
  for (const surface of SURFACES) {
    describe(surface.label, () => {
      // 自证下限：扫描面被悄悄删窄、红线词被摘掉，都要当场响，不能只少跑几个用例
      it('扫描面与红线词表不得缩水', () => {
        const files = surface.files();
        expect(files.length, `${surface.label} 只扫到 ${String(files.length)} 个文件`).toBeGreaterThanOrEqual(surface.minFiles);
        expect(files.some((file) => file.endsWith(surface.probe)), `扫描面里没有 ${surface.probe}`).toBe(true);
        expect(surface.banned.length, `${surface.label} 红线词表缩水`).toBeGreaterThanOrEqual(surface.minPhrases);
      });

      for (const { phrase, reason } of surface.banned) {
        it(`不得出现「${phrase}」`, () => {
          const hits = hitsIn(surface, phrase);
          expect(hits, `${phrase} —— ${reason}。命中：${hits.join(', ')}`).toEqual([]);
        });
      }
    });
  }

  it('免责声明原文保留——合规靠改文案，不靠删声明', () => {
    const readme = readFileSync(path.join(ROOT_DIR, 'README.md'), 'utf8');
    expect(readme).toContain('不提供规避原创性检测的功能');
  });
});
