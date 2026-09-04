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
