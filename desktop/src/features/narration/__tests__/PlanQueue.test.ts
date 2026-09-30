/** 规划队列行合成：规格骨架 + 三路数据盖章。
 *  spec 缺失退化为汇总形态；别批方案不算数；失败行按「第N条」精确归位。 */
import { describe, expect, it } from 'vitest';
import type { NarrationPlan } from '@dramaclip/protocol';
import { buildQueueRows, parseFailures } from '../PlanQueue';

const MODES = ['dialogue_narration', 'cross_narration'] as const;

function plan(mode: string, index: number, batchId = 'job-1'): NarrationPlan {
  return {
    id: `${mode}-${String(index)}`,
    project_id: 'p1',
    narration_mode: mode as NarrationPlan['narration_mode'],
    episode_ids: [],
    plan_data: { mode, timeline: [], narration_texts: [] },
    status: 'ready',
    created_at: 0,
    angle: `角度${String(index)}`,
    variant_index: index,
    batch_id: batchId,
  } as NarrationPlan;
}

describe('buildQueueRows', () => {
  it('规格骨架先行：全部行初始排队，stage 匹配的第一行是生成中', () => {
    const rows = buildQueueRows(
      { modes: [...MODES], k: 2 },
      [],
      'job-1',
      '',
      '剧情解说·第1条 选题中',
    );
    expect(rows).toHaveLength(4);
    expect(rows[0]?.status).toBe('running');
    expect(rows[1]?.status).toBe('pending');
    expect(rows[3]?.status).toBe('pending');
  });

  it('落库方案按 批次+模式+槽位 点亮完成，别批的方案不算数', () => {
    const rows = buildQueueRows(
      { modes: [...MODES], k: 1 },
      [plan('dialogue_narration', 1, 'job-1'), plan('cross_narration', 1, 'other-batch')],
      'job-1',
      '',
      '',
    );
    expect(rows[0]?.status).toBe('done');
    expect(rows[0]?.plan?.angle).toBe('角度1');
    expect(rows[1]?.status).toBe('pending');
  });

  it('失败行按「第N条」精确归位并带原因原文', () => {
    const rows = buildQueueRows(
      { modes: [...MODES], k: 2 },
      [],
      'job-1',
      '剧情解说·第2条: LLM 请求失败: read timeout',
      '剧情解说·第1条',
    );
    expect(rows[0]?.status).toBe('running');
    expect(rows[1]?.status).toBe('failed');
    expect(rows[1]?.reason).toContain('read timeout');
  });
});

describe('parseFailures', () => {
  it('按「；」分行、首个「·」与「: 」切段', () => {
    const lines = parseFailures('剧情解说·第1条: LLM 403；交叉解说·复仇视角: 重叠 60%');
    expect(lines).toHaveLength(2);
    expect(lines[0]).toEqual({ label: '剧情解说', slot: '第1条', reason: 'LLM 403' });
    expect(lines[1]?.slot).toBe('复仇视角');
  });
});
