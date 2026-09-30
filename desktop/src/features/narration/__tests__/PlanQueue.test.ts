/** 规划队列行推导：三路数据（落库方案/失败增量/当前 stage）合成每行状态。
 *  执行全局串行 → 第一个待定行即「生成中」；失败行按「第N条」精确归位、
 *  角度名槽位按序贪心归位；别的批次的方案绝不点亮本批的行。 */
import { describe, expect, it } from 'vitest';
import type { NarrationPlan } from '@dramaclip/protocol';
import { buildQueueSummary, parseFailures } from '../PlanQueue';

const MODES = ['dialogue_narration', 'cross_narration'] as const;

function plan(mode: string, index: number, batchId = 'job-1', angle = `角度${String(index)}`): NarrationPlan {
  return {
    id: `${mode}-${String(index)}`,
    project_id: 'p1',
    narration_mode: mode as NarrationPlan['narration_mode'],
    episode_ids: [],
    plan_data: { mode, timeline: [], narration_texts: [] },
    status: 'ready',
    created_at: 0,
    angle,
    variant_index: index,
    batch_id: batchId,
  } as NarrationPlan;
}

describe('buildQueueSummary', () => {
  it('只认本批方案，别批的不计入完成', () => {
    const summary = buildQueueSummary(
      [plan('dialogue_narration', 1, 'job-1'), plan('cross_narration', 1, 'other-batch')],
      'job-1',
      '',
      '',
      50,
    );
    expect(summary.done).toHaveLength(1);
  });

  it('失败行解析自 jobs.error 增量，计入已完成进度', () => {
    const summary = buildQueueSummary([], 'job-1', '剧情解说·第1条: LLM 请求失败: read timeout', '', 50);
    expect(summary.failures).toHaveLength(1);
    expect(summary.failures[0]?.reason).toContain('read timeout');
    expect(summary.pendingCount).toBe(1);
  });

  it('百分比反推排队条数：完成 2 条时 40% → 总数 5、排队 3', () => {
    const summary = buildQueueSummary(
      [plan('dialogue_narration', 1), plan('cross_narration', 1)],
      'job-1',
      '',
      '剧情解说·第1条',
      40,
    );
    expect(summary.pendingCount).toBe(3);
    expect(summary.stageText).toBe('剧情解说·第1条');
  });

  it('终态（100%）不再反推总数，排队归零', () => {
    const summary = buildQueueSummary(
      [plan('dialogue_narration', 1)],
      'job-1',
      '',
      '',
      100,
    );
    expect(summary.pendingCount).toBe(0);
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
