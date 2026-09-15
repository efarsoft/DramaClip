import { describe, expect, it } from 'vitest';
import { NAV_GROUPS, NAV_ITEMS, isNavActive, navByGroup } from '../navItems';

describe('导轨清单', () => {
  it('分两组', () => {
    expect(NAV_GROUPS).toEqual(['loop', 'config']);
    expect(navByGroup('loop').map((item) => item.label)).toEqual(['工作台', '项目', '成品']);
    expect(navByGroup('config').map((item) => item.label)).toEqual(['引擎', '设置', '关于']);
  });

  it('上组全部排在下组之前', () => {
    const groups = NAV_ITEMS.map((item) => item.group);
    expect(groups.lastIndexOf('loop')).toBeLessThan(groups.indexOf('config'));
  });

  it('路径唯一、标签唯一、每项都有图标', () => {
    const paths = NAV_ITEMS.map((item) => item.path);
    expect(new Set(paths).size).toBe(paths.length);
    const labels = NAV_ITEMS.map((item) => item.label);
    expect(new Set(labels).size).toBe(labels.length);
    for (const item of NAV_ITEMS) {
      expect(item.icon, `${item.label} 缺图标`).toBeDefined();
    }
  });

  it('标签不超过三个字', () => {
    for (const item of NAV_ITEMS) {
      expect(item.label).not.toMatch(/[/／·、]/);
      expect(item.label.length).toBeLessThanOrEqual(3);
    }
  });
});

describe('命中判定', () => {
  const byPath = (path: string) => {
    const item = NAV_ITEMS.find((c) => c.path === path);
    if (item === undefined) throw new Error(`清单里没有 ${path}`);
    return item;
  };

  it('根路径只精确命中', () => {
    const home = byPath('/');
    expect(isNavActive(home, '/')).toBe(true);
    expect(isNavActive(home, '/works')).toBe(false);
    expect(isNavActive(home, '/settings')).toBe(false);
  });

  it('引擎深链保持高亮', () => {
    const engines = byPath('/engines');
    expect(isNavActive(engines, '/engines')).toBe(true);
    expect(isNavActive(engines, '/engines/llm')).toBe(true);
    expect(isNavActive(engines, '/engines/asr')).toBe(true);
  });

  it('进单剧详情保持「项目」高亮', () => {
    const projects = byPath('/projects');
    expect(isNavActive(projects, '/projects/abc123/analysis')).toBe(true);
    expect(isNavActive(projects, '/projects/abc123/produce')).toBe(true);
  });

  it('前缀按路径段边界匹配', () => {
    const works = byPath('/works');
    expect(isNavActive(works, '/works-archive')).toBe(false);
    expect(isNavActive(works, '/works/anything')).toBe(true);
  });

  it('任一时刻至多一项命中', () => {
    const paths = ['/', '/projects', '/projects/a/analysis', '/works', '/engines/llm', '/settings'];
    for (const pathname of paths) {
      const hits = NAV_ITEMS.filter((item) => isNavActive(item, pathname));
      expect(hits.length, `${pathname} 命中 ${String(hits.length)} 项`).toBe(1);
    }
  });
});
