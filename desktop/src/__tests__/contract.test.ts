// @vitest-environment node
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';
import { METHOD_NAMES } from '@dramaclip/protocol';

/** 契约同步（docs/04 §3）：TS METHOD_NAMES ↔ schemas x-methods 集合相等。 */
it('METHOD_NAMES 与 protocol/schemas 的 x-methods 一致', () => {
  const schemaDir = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '../../..', 'protocol', 'schemas');
  const names = new Set<string>();
  for (const file of readdirSync(schemaDir)) {
    if (!file.endsWith('.json')) continue;
    const raw = JSON.parse(readFileSync(path.join(schemaDir, file), 'utf8')) as {
      'x-methods'?: { name: string }[];
    };
    for (const method of raw['x-methods'] ?? []) names.add(method.name);
  }
  expect(new Set<string>(METHOD_NAMES)).toEqual(names);
});

/**
 * 契约的第三方：渲染层实际调用的方法名必须都在协议里。
 * 上面那条只比对「TS 声明 ↔ schema 声明」两份名单，谁都不看 client.ts 真正调了什么，
 * 于是 narration.produce 被拆成 plan_variants + export.submit 之后，
 * 「开始出片」按钮照样在，点下去必报「未知 RPC 方法」而两边声明依旧相等、全绿。
 */
it('client.ts 调用的每个方法名都在 METHOD_NAMES 里', () => {
  const clientPath = path.resolve(
    fileURLToPath(new URL('.', import.meta.url)),
    '..',
    'services',
    'client.ts',
  );
  const source = readFileSync(clientPath, 'utf8');
  const called = [...source.matchAll(/'([a-z_]+\.[a-z_]+)'/g)].map((match) => String(match[1]));
  // 自证覆盖：引号风格一改，这条断言就会静默抓到 0 个调用而"通过"
  expect(called.length).toBeGreaterThanOrEqual(40);
  const known = new Set<string>(METHOD_NAMES);
  const unknown = [...new Set(called)].filter((name) => !known.has(name));
  expect(unknown, `渲染层调用了协议里不存在的方法: ${unknown.join(', ')}`).toEqual([]);
});
