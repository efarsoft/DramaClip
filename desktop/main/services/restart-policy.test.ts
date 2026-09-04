// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { RestartPolicy } from './restart-policy';

function fakeClock(startAt = 1_000_000) {
  let current = startAt;
  return {
    now: () => current,
    advance: (ms: number) => {
      current += ms;
    },
  };
}

describe('RestartPolicy', () => {
  it('退避 2s/4s/6s，第 4 次放弃', () => {
    const clock = fakeClock();
    const policy = new RestartPolicy(3, 60_000, 2_000, clock.now);
    policy.recordStart();
    clock.advance(1_000); // 未稳定
    expect(policy.onFailure()).toEqual({ action: 'restart', delayMs: 2_000 });
    expect(policy.onFailure()).toEqual({ action: 'restart', delayMs: 4_000 });
    expect(policy.onFailure()).toEqual({ action: 'restart', delayMs: 6_000 });
    expect(policy.onFailure()).toEqual({ action: 'give-up', delayMs: 0 });
  });

  it('稳定运行 60s 后计数清零', () => {
    const clock = fakeClock();
    const policy = new RestartPolicy(3, 60_000, 2_000, clock.now);
    policy.recordStart();
    clock.advance(1_000);
    expect(policy.onFailure()).toEqual({ action: 'restart', delayMs: 2_000 });

    policy.recordStart();
    clock.advance(61_000); // 稳定运行达标
    expect(policy.onFailure()).toEqual({ action: 'restart', delayMs: 2_000 }); // 重新从 2s 开始
  });
});
