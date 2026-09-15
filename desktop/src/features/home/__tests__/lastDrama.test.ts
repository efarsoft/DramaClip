/** 「继续上次」的本地偏好：坏数据必须退化成"没有记录"，不得拼出 undefined 路径。 */
import { beforeEach, describe, expect, it } from 'vitest';
import { clearLastDrama, readLastDrama, rememberDrama } from '../../../stores/lastDrama';

const KEY = 'dramaclip.last-drama';

beforeEach(() => {
  window.localStorage.clear();
});

describe('lastDrama', () => {
  it('没写过就是 null', () => {
    expect(readLastDrama()).toBeNull();
  });

  it('写进去能原样读回来', () => {
    rememberDrama('p1', '逆袭开局');
    const read = readLastDrama();
    expect(read?.id).toBe('p1');
    expect(read?.name).toBe('逆袭开局');
    expect(typeof read?.visitedAtMs).toBe('number');
  });

  it('后写的覆盖先写的', () => {
    rememberDrama('p1', 'A');
    rememberDrama('p2', 'B');
    expect(readLastDrama()?.id).toBe('p2');
  });

  it('clear 之后回到 null', () => {
    rememberDrama('p1', 'A');
    clearLastDrama();
    expect(readLastDrama()).toBeNull();
  });

  it('上一版写的或手工改坏的数据一律当没有记录', () => {
    for (const raw of ['not json', '{}', '{"id":"","name":"A","visitedAtMs":1}', '{"id":"p1"}', 'null', '[]']) {
      window.localStorage.setItem(KEY, raw);
      expect(readLastDrama(), raw).toBeNull();
    }
  });
});
