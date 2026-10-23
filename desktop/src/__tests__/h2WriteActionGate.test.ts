// @vitest-environment node
/** H2 门禁 1（规格 §4.1）：`services/client.ts` 导出的每个**写动作**必须有渲染层调用方。
 *
 * 「有入口才有按钮」的反面就是这种账：客户端把 RPC 包成方法、渲染层从不调用，界面
 * 上留着的相关控件于是成了假动作（候选标题的星标正是这一条抓到——点了只改本地
 * `useState`，刷新即丢）。同族先例＝W1 的 G3 留痕消费门禁。
 *
 * 扫描面复用 `scanSurface.rendererFiles()`（与 W1/W3 门禁同一份定义），不另起扫描器：
 * 两处「扫不到」会长成两份不同的假绿。
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { SRC_DIR, rendererFiles, sourceText } from './scanSurface';

/** 写动作的判据是动词，不是「RPC 方法名里有动词」：读动作（list/get/status）不在本条管辖。 */
const WRITE_VERBS = new Set([
  'update',
  'retry',
  'cancel',
  'save',
  'install',
  'remove',
  'delete',
  'submit',
  'create',
  'enable',
  'reset',
]);

/** 从 client.ts 抽出 `export const xxxApi = { method: … }` 的方法名。 */
function writeActions(): string[] {
  const lines = readFileSync(path.join(SRC_DIR, 'services', 'client.ts'), 'utf8').split(/\r?\n/);
  const out: string[] = [];
  let current: string | null = null;
  for (const line of lines) {
    const owner = /^export const (\w+) = \{/.exec(line)?.[1];
    if (owner !== undefined) {
      current = owner;
      continue;
    }
    if (current !== null && line.startsWith('}')) {
      current = null;
      continue;
    }
    const method = /^ {2}(\w+):/.exec(line)?.[1];
    if (current === null || method === undefined) continue;
    if (WRITE_VERBS.has(method)) out.push(`${current}.${method}`);
  }
  return out;
}

describe('H2 门禁 1：写动作零调用方（2026-10-22 规格 §4.1）', () => {
  it('每个写动作都能在渲染层找到调用点', () => {
    const client = path.join(SRC_DIR, 'services', 'client.ts');
    const callers = rendererFiles()
      .filter((file) => file !== client)
      .map((file) => sourceText(file));
    const orphans = writeActions().filter((action) => {
      const [owner, method] = action.split('.');
      if (owner === undefined || method === undefined) return true;
      // 链式调用会被 prettier 折行（`exportApi` 换行 `.retry(`），所以判据跨空白匹配
      const called = new RegExp(`${owner}\\s*\\.\\s*${method}\\b`);
      return !callers.some((text) => called.test(text));
    });
    expect(orphans).toEqual([]);
  });
});
