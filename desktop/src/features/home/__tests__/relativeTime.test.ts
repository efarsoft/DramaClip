import { describe, expect, it } from 'vitest';
import { whenLabel } from '../relativeTime';

const NOW = 1_760_000_000_000;
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe('whenLabel', () => {
  it('不足一分钟说刚刚', () => {
    expect(whenLabel(NOW - 30_000, NOW)).toBe('刚刚');
  });

  it('时钟被往前调过也不输出负数', () => {
    expect(whenLabel(NOW + 5 * MINUTE, NOW)).toBe('刚刚');
  });

  it('分钟、小时、天三档各自成立且边界不重叠', () => {
    expect(whenLabel(NOW - MINUTE, NOW)).toBe('1 分钟前');
    expect(whenLabel(NOW - 59 * MINUTE, NOW)).toBe('59 分钟前');
    expect(whenLabel(NOW - HOUR, NOW)).toBe('1 小时前');
    expect(whenLabel(NOW - 23 * HOUR, NOW)).toBe('23 小时前');
    expect(whenLabel(NOW - DAY, NOW)).toBe('1 天前');
  });
});
