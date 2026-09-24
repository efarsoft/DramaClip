// @vitest-environment jsdom
/** 剧库密度档偏好：默认海报墙、只认 'list' 字面量、写读回环。 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { readDensity, writeDensity } from '../libraryDensity';

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe('libraryDensity', () => {
  it('无记录：默认海报墙', () => {
    expect(readDensity()).toBe('grid');
  });

  it('写读回环：list 记住，grid 回落', () => {
    writeDensity('list');
    expect(readDensity()).toBe('list');
    writeDensity('grid');
    expect(readDensity()).toBe('grid');
  });

  it('损坏值/旧值：一律回落海报墙，不猜', () => {
    window.localStorage.setItem('dramaclip.library-density', 'table');
    expect(readDensity()).toBe('grid');
    window.localStorage.setItem('dramaclip.library-density', '');
    expect(readDensity()).toBe('grid');
  });
});
