// @vitest-environment node
/** 信息架构一致性守卫：导轨 ↔ 路由清单 ↔ router.tsx 三方必须一致。 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { NAV_ITEMS } from '../navItems';
import {
  DETAIL_ROUTES,
  LEGACY_PARAM_REDIRECTS,
  LEGACY_REDIRECTS,
  TOP_LEVEL_ROUTES,
  dramaEntryPath,
  dramaProducePath,
} from '../routes';

const here = path.dirname(fileURLToPath(import.meta.url));
const ROUTER_SOURCE = readFileSync(
  path.resolve(here, '..', 'router.tsx'),
  'utf8',
);

function literalsIn(source: string, attribute: string): string[] {
  const pattern = new RegExp(`${attribute}="([^"]+)"`, 'g');
  return [...source.matchAll(pattern)].map((match) => match[1] ?? '');
}

describe('信息架构一致性', () => {
  it('确实读到了 router.tsx', () => {
    expect(ROUTER_SOURCE).toContain('HashRouter');
    expect(literalsIn(ROUTER_SOURCE, 'path').length).toBeGreaterThan(5);
  });

  it('导轨项与顶层路由是同一个集合（双向）', () => {
    expect(new Set(NAV_ITEMS.map((item) => item.path))).toEqual(new Set(TOP_LEVEL_ROUTES));
  });

  it('router.tsx 的每个 path 字面量都已登记', () => {
    const known = new Set<string>([...TOP_LEVEL_ROUTES, ...DETAIL_ROUTES, '*']);
    for (const literal of literalsIn(ROUTER_SOURCE, 'path')) {
      expect(known.has(literal), `router.tsx 有未登记的路由：${literal}`).toBe(true);
    }
  });

  it('router.tsx 的每个 to 字面量都是顶层路由', () => {
    const known = new Set<string>(TOP_LEVEL_ROUTES);
    for (const literal of literalsIn(ROUTER_SOURCE, 'to')) {
      expect(known.has(literal), `router.tsx 重定向到未登记的路由：${literal}`).toBe(true);
    }
  });

  it('静态重定向表的目标都存在，且不是自己指自己', () => {
    const known = new Set<string>(TOP_LEVEL_ROUTES);
    expect(Object.keys(LEGACY_REDIRECTS).length).toBeGreaterThan(0);
    for (const [from, to] of Object.entries(LEGACY_REDIRECTS)) {
      expect(known.has(to), `${from} → ${to}：目标不是顶层路由`).toBe(true);
      expect(from).not.toBe(to);
    }
  });

  it('保参重定向表的目标存在，且参数名逐一对应', () => {
    const known = new Set<string>(TOP_LEVEL_ROUTES);
    for (const entry of LEGACY_PARAM_REDIRECTS) {
      const base = entry.to.replace(/\/:\w+$/, '');
      expect(known.has(base), `${entry.from} → ${entry.to}：目标基路径不是顶层路由`).toBe(true);
      const fromParams = [...entry.from.matchAll(/:(\w+)/g)].map((match) => match[1]);
      const toParams = [...entry.to.matchAll(/:(\w+)/g)].map((match) => match[1]);
      expect(toParams, '保参重定向的参数名必须逐一对应').toEqual(fromParams);
      expect(fromParams.length).toBeGreaterThan(0);
    }
  });

  it('单剧入口与出片页都指向已登记的详情路由', () => {
    const sample = dramaEntryPath('abc123');
    expect(sample).toBe('/projects/abc123/analysis');
    expect(dramaProducePath('abc123')).toBe('/projects/abc123/produce');
    for (const p of [sample, dramaProducePath('abc123')]) {
      expect(DETAIL_ROUTES.some((route) => route.endsWith(p.slice(p.lastIndexOf('/'))))).toBe(true);
    }
  });

  it('三份清单内部都没有重复', () => {
    expect(new Set(TOP_LEVEL_ROUTES).size).toBe(TOP_LEVEL_ROUTES.length);
    expect(new Set(DETAIL_ROUTES).size).toBe(DETAIL_ROUTES.length);
    const froms = LEGACY_PARAM_REDIRECTS.map((entry) => entry.from);
    expect(new Set(froms).size).toBe(froms.length);
  });
});

const NAVITEMS_SOURCE = readFileSync(
  path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', 'navItems.ts'),
  'utf8',
);
const ROUTES_SOURCE = readFileSync(
  path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', 'routes.ts'),
  'utf8',
);

describe('IA 数据层的分层纪律', () => {
  // navItems.ts / routes.ts 被 components/layout、features/*、app/router 三方消费，
  // 所以它们自己绝不能反向 import features 或 components——否则 app→features→app 成环。
  // eslint 只挡了 components/ 反向依赖 features/，挡不到这条。
  it('navItems.ts 与 routes.ts 不得 import features 或 components', () => {
    for (const [name, source] of [['navItems.ts', NAVITEMS_SOURCE], ['routes.ts', ROUTES_SOURCE]] as const) {
      const imports = [...source.matchAll(/from\s+'([^']+)'/g)].map((match) => match[1] ?? '');
      for (const specifier of imports) {
        expect(specifier, `${name} 反向依赖了 ${specifier}`).not.toMatch(/features|components/);
      }
    }
  });

  it('routes.ts 完全不依赖任何本地模块（它是叶子）', () => {
    expect(ROUTES_SOURCE).not.toMatch(/^\s*import\s/m);
  });
});
