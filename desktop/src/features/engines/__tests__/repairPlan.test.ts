// 修复按钮与体检判据同源（§10.2）：哪个 warn 出哪个动作由判据名推导，
// 不解析 detail 文案——文案会改，判据名是契约；paths 是删除白名单的展示源。
import { describe, expect, it } from 'vitest';
import { repairNeeds } from '../repairPlan';
import { report } from './fixtures';

describe('repairNeeds', () => {
  it('「中断残留」warn → 清理残留动作', () => {
    const needs = repairNeeds(
      report({ checks: [{ name: '中断残留', status: 'warn', detail: '1 个（192MB）' }] }),
    );
    expect(needs.residue).toBe(true);
    expect(needs.migrate).toBe(false);
    expect(needs.orphanPaths).toEqual([]);
  });

  it('「快照提交号」warn（无从对账）→ 就地迁移；fail 不出迁移按钮（那是矛盾，不是退化）', () => {
    expect(
      repairNeeds(report({ checks: [{ name: '快照提交号', status: 'warn', detail: '无从对账' }] }))
        .migrate,
    ).toBe(true);
    expect(
      repairNeeds(report({ ok: false, checks: [{ name: '快照提交号', status: 'fail' }] })).migrate,
    ).toBe(false);
  });

  it('「唯一路径」warn 的结构化 paths 充当副本名单；没有 paths 就不摆按钮', () => {
    const needs = repairNeeds(
      report({
        checks: [{ name: '唯一路径', status: 'warn', detail: '另有 1 处', paths: ['D:\\a', 'D:\\b'] }],
      }),
    );
    expect(needs.orphanPaths).toEqual(['D:\\a', 'D:\\b']);
    expect(
      repairNeeds(report({ checks: [{ name: '唯一路径', status: 'warn' }] })).orphanPaths,
    ).toEqual([]);
  });

  it('体检通过 / 没体检 → 一个修复动作都不摆（按钮必须由判据召唤，不许常驻凑数）', () => {
    const clean = repairNeeds(report());
    expect(clean).toEqual({ residue: false, migrate: false, orphanPaths: [] });
    expect(repairNeeds(undefined)).toEqual({ residue: false, migrate: false, orphanPaths: [] });
  });
});
