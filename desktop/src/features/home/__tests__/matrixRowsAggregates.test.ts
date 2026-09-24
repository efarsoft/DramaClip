/** buildMatrixRows × 阶段聚合接线：project 行的 analyzed_count/plan_count 进 deriveStages。
 * 聚合供数后 ②③ 灯从降级灰升级为真绿（卷三意见 03 的「聚合落地后启用绿灯」半句）。 */
import { describe, expect, it } from 'vitest';
import type { Project } from '@dramaclip/protocol';
import { buildMatrixRows } from '../matrixRows';

const NOW = 1_758_600_000_000;

function project(partial: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '千金归来',
    source_path: 'D:/dramas/p1',
    status: 'ready',
    created_at: NOW - 86_400_000,
    episode_count: 6,
    settings: {},
    ...partial,
  };
}

describe('buildMatrixRows 聚合供数', () => {
  it('analyzed_count 齐 + plan_count>0：②③ 点真绿，④ 无成品仍灰不假绿', () => {
    const rows = buildMatrixRows(
      [project({ analyzed_count: 6, plan_count: 2 })],
      [],
      [],
      NOW,
    );
    const stages = rows[0]?.stages;
    expect(stages?.analysis).toBe('done');
    expect(stages?.planning).toBe('done');
    expect(stages?.export).toBe('idle');
  });

  it('analyzed_count 部分：② 是 active（分析中）不是 done', () => {
    const rows = buildMatrixRows([project({ analyzed_count: 2 })], [], [], NOW);
    expect(rows[0]?.stages.analysis).toBe('active');
  });

  it('字段缺省（旧服务）：② 保持 unknown——宁灰勿假绿的降级路径没被接线破坏', () => {
    const rows = buildMatrixRows([project()], [], [], NOW);
    expect(rows[0]?.stages.analysis).toBe('unknown');
  });
});
