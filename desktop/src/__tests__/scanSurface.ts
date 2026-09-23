/**
 * 源码扫描门禁共用的遍历与定位工具（styleContract 的 §3.4、measureContract 的 §8.3 与 §1.3 共用）。
 * 抽出来的直接原因是 docs/04 的单文件 300 行上限；共用一份实现才是目的——
 * 扫描面只有一处定义，「扫不到」不会在两个门禁里长成两份不同的假绿。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const SRC_DIR = path.resolve(fileURLToPath(new URL('..', import.meta.url)));

/** 渲染层全部 .ts/.tsx（测试与替身除外）；这就是两条门禁共同的扫描面。 */
export function rendererFiles(): string[] {
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

export function sourceText(file: string): string {
  return readFileSync(file, 'utf8');
}

/** 报告用相对路径（斜杠分隔，跨平台可 diff）。 */
export function relPath(file: string): string {
  return path.relative(SRC_DIR, file).split(path.sep).join('/');
}

/** 注释行不计位点：禁令原文本身就写在注释里（EpisodeListRow、TodoList 的 #FF4D4F 说明）。 */
export function isComment(line: string): boolean {
  const t = line.trimStart();
  return t.startsWith('//') || t.startsWith('*') || t.startsWith('/*');
}

/**
 * 三处判据共用的扫描器：**整档匹配**，再按命中偏移换算行号。
 * 判据的单位是**属性赋值**而不是整行——值太长时属性名与值会折到两行（`boxShadow:` 换行再跟字面量），
 * 逐行匹配会把这种位点整条放过，棘轮就成了格式化可以静默绕过的装饰。三条判据各有一条折行夹具钉住。
 * 注释豁免按命中所在行判定。re 需带 g（matchAll 要求）；行号随产出顺序单向前推，整档只走一遍。
 */
export function forEachHit(
  text: string,
  re: RegExp,
  cb: (match: RegExpMatchArray, line: number, rawLine: string) => void,
): void {
  const lines = text.split('\n');
  let pos = 0;
  let line = 0;
  for (const m of text.matchAll(re)) {
    while (pos < m.index) {
      if (text.charCodeAt(pos) === 10) line += 1;
      pos += 1;
    }
    cb(m, line + 1, lines[line] ?? '');
  }
}
