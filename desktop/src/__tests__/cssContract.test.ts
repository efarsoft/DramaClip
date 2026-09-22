// @vitest-environment node
/**
 * 字体随包与 CSS 单一真相门禁（规格 §7.1、§7.2、§8.3）。
 * 三条各自对应一种「写了但没人用 / 声明了但没随包」的失败形状：
 *   ① global.css 里的色值只准是 var(--dc-*)，值本身由 theme.ts 单点导出；
 *   ② @font-face 指到的字节必须真在仓库里（声明了字面却没随包 = 换台机器就回到系统字面）；
 *   ③ 分发含字体，许可文本与关于页清单必须各就各位（OFL 1.1 要求许可随包）。
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { cssVars, tokens } from '../styles/theme';
import { OPEN_SOURCE } from '../features/about/openSource';

const SRC_DIR = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const CSS_PATH = path.join(SRC_DIR, 'styles', 'global.css');
const FONTS_DIR = path.join(SRC_DIR, 'assets', 'fonts');
const css = readFileSync(CSS_PATH, 'utf8');

/** @font-face 里 url() 指到的相对路径，按 global.css 所在目录解析。 */
function faceFontFiles(): string[] {
  const faces = css.match(/@font-face\s*\{[^}]*\}/g) ?? [];
  const urls = faces.flatMap((face) => [...face.matchAll(/url\(['"]?([^'")]+?)['"]?\)/g)].map((m) => m[1] ?? ''));
  return urls.filter((u) => !u.startsWith('data:')).map((u) => path.resolve(path.dirname(CSS_PATH), u));
}

/** electron-builder `files:` 段的列表项（注释行不算条目）。 */
function builderFileEntries(config: string): string[] {
  // 换行先归一：Windows 干净检出就是 CRLF，按 \n 锚定的话整段读空，门禁在
  // 新检出的机器上直接红（快照 git archive + tar 实测过这一次）。
  const normalized = config.replace(/\r\n/g, '\n');
  // 只取 files: 到下一个顶格键之间的那一段（extraResources 走的是 ../resources，两码事）
  const filesBlock = /^files:\n([\s\S]*?)(?=^[^\s#])/m.exec(normalized)?.[1] ?? '';
  return [...filesBlock.matchAll(/^[ \t]+-[ \t]+(\S+)/gm)].map((m) => m[1] ?? '');
}

describe('§7.1 global.css 不得是第二处色值真相', () => {
  it('global.css 里零裸色值（hex / rgb() / rgba()）', () => {
    const offenders: string[] = [];
    css.split('\n').forEach((line, index) => {
      const t = line.trimStart();
      if (t.startsWith('/*') || t.startsWith('*') || t.startsWith('//')) return;
      if (/#[0-9A-Fa-f]{3,8}\b/.test(line) || /\brgba?\(/.test(line)) {
        offenders.push(`:${String(index + 1)} ${t}`);
      }
    });
    expect(offenders, `色值只准出现在 theme.ts：\n${offenders.join('\n')}`).toEqual([]);
  });

  it('用到的每个 --dc-* 变量都有声明（悬空 var 会静默变成无样式）', () => {
    const used = [...new Set([...css.matchAll(/var\((--dc-[a-z0-9-]+)/g)].map((m) => m[1] ?? ''))];
    expect(used.length).toBeGreaterThanOrEqual(6);
    const missing = used.filter((name) => !(name.slice(2) in cssVars));
    expect(missing, `global.css 用了未导出的变量：${missing.join(', ')}`).toEqual([]);
  });

  it('cssVars 的每个值都直接取自 tokens（派生表不得自己藏值）', () => {
    const tokenValues = new Set(
      Object.values(tokens).flatMap((v) =>
        typeof v === 'string' ? [v] : typeof v === 'object' ? Object.values(v).filter((x): x is string => typeof x === 'string') : [],
      ),
    );
    const orphans = Object.entries(cssVars).filter(([, value]) => !tokenValues.has(value));
    expect(orphans.length, `cssVars 里这些值不是从 tokens 取的：${JSON.stringify(orphans)}`).toBe(0);
  });

  it('变量必须真的注进 :root——写了不注入等于没写', () => {
    expect(readFileSync(path.join(SRC_DIR, 'main.tsx'), 'utf8')).toContain('applyCssVars()');
  });
});

describe('§7.1 界面字面随包', () => {
  it('@font-face 指到的字体文件真实在场且非空壳', () => {
    const files = faceFontFiles();
    expect(files.length).toBeGreaterThanOrEqual(4);
    const absent = files.filter((f) => !existsSync(f));
    expect(absent, `声明了但没随包：${absent.join(', ')}`).toEqual([]);
    for (const f of files) expect(statSync(f).size, `${f} 太小，像是占位`).toBeGreaterThan(40000);
  });

  it('字面栈首位是随包字面，系统字面只作兜底', () => {
    expect(tokens.fontFamilyUi).toContain('Inter');
    expect(tokens.fontFamilyUi).toContain("'DramaClip SC'");
    const families = cssVars['dc-font-ui'].split(',').map((f) => f.trim().replace(/'/g, ''));
    expect(families.slice(0, 2)).toEqual(['Inter', 'DramaClip SC']);
    // 界面字体栈必须经变量落到 CSS：写死在 CSS 里就是第二处真相
    expect(/font-family:\s*var\(--dc-font-ui\)/.test(css)).toBe(true);
  });

  it('思源带足三档字重——§1.1 要 600，缺档等于让 Chromium 合成假粗', () => {
    const weights = readdirSync(FONTS_DIR)
      .filter((f) => f.startsWith('NotoSansSC-') && f.endsWith('.woff2'))
      .map((f) => /-(\d+)\.woff2$/.exec(f)?.[1] ?? '')
      .sort();
    expect(weights).toEqual(['400', '500', '600']);
    // 每一档都得真被 @font-face 引到，否则文件在场却不生效
    for (const w of weights) {
      expect(new RegExp(`font-weight:\\s*${w}\\b`).test(css), `${w} 档没有 @font-face`).toBe(true);
    }
  });
});

describe('§7.2 许可随包与关于页清单', () => {
  it('两种字面各一份 OFL 文本——一份许可覆盖两种字面不成立', () => {
    const licences = readdirSync(FONTS_DIR).filter((f) => /^OFL-.*\.txt$/.test(f)).sort();
    expect(licences).toEqual(['OFL-Inter.txt', 'OFL-NotoSansSC.txt']);
    for (const name of licences) {
      const text = readFileSync(path.join(FONTS_DIR, name), 'utf8');
      expect(text).toContain('SIL OPEN FONT LICENSE Version 1.1');
    }
  });

  it('许可文本必须真的进包——不被代码引用的文件 Vite 不会带进 dist', () => {
    const config = readFileSync(path.resolve(SRC_DIR, '..', 'electron-builder.yml'), 'utf8');
    const entries = builderFileEntries(config);
    expect(entries.length, '没读到 electron-builder 的 files 段').toBeGreaterThanOrEqual(2);
    expect(
      entries.some((entry) => entry.includes('OFL')),
      `字体随包而许可文本不在 files 段：${entries.join(', ')}`,
    ).toBe(true);
  });

  it('files 段解析对 CRLF 检出有效——Windows 干净检出就是 \\r\\n', () => {
    const fixture = [
      'productName: DramaClip',
      'files:',
      '  - dist/**',
      '  # - 注释里提 OFL 不算条目',
      '  - src/assets/fonts/OFL-*.txt',
      'extraResources:',
      '  - from: ../resources',
      '',
    ].join('\r\n');
    expect(builderFileEntries(fixture)).toEqual(['dist/**', 'src/assets/fonts/OFL-*.txt']);
  });

  it('关于页开源清单含两种字面，且逐条标注 OFL', () => {
    expect(OPEN_SOURCE.length, '清单缩水').toBeGreaterThanOrEqual(11);
    for (const family of ['Inter', 'Noto Sans SC']) {
      const entry = OPEN_SOURCE.find((item) => item.includes(family));
      expect(entry, `清单缺 ${family}`).toBeDefined();
      // 只验「整份清单里有 OFL」挡不住「另一种字面漏标」——必须逐条
      expect(entry, `${family} 条目未标注 OFL`).toContain('OFL');
    }
  });
});
