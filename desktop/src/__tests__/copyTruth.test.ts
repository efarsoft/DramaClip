// @vitest-environment node
/** 界面文案真值门禁（规格 §9.5）+ 合规红线。 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC_DIR = path.resolve(fileURLToPath(new URL('..', import.meta.url)));

const BANNED: readonly { phrase: string; reason: string }[] = [
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

  it('确实扫到了源文件', () => {
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
