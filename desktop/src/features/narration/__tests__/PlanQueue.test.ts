/** 规划队列行推导：三路数据（落库方案/失败增量/当前 stage）合成每行状态。
 *  执行全局串行 → 第一个待定行即「生成中」；失败行按「第N条」精确归位、
 *  角度名槽位按序贪心归位；别的批次的方案绝不点亮本批的行。 */
import { describe, expect, it } from 'vitest';
import type { NarrationPlan } from '@dramaclip/protocol';
import { buildQueueRows, parseFailures } from '../PlanQueue';

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

describe('buildQueueRows', () => {
  it('无数据时全部排队，第一个待定行是生成中', () => {
    const rows = buildQueueRows([...MODES], 2, [], 'job-1', '', '剧情解说·第1条 选题中');
    expect(rows).toHaveLength(4);
    expect(rows[0]?.status).toBe('running');
    expect(rows[1]?.status).toBe('pending');
    expect(rows[2]?.status).toBe('pending');
  });

  it('落库方案按 批次+模式+槽位 点亮完成，别批的方案不算数', () => {
    const rows = buildQueueRows(
      [...MODES],
      1,
      [plan('dialogue_narration', 1, 'job-1'), plan('cross_narration', 1, 'other-batch')],
      'job-1',
      '',
      '',
    );
    expect(rows[0]?.status).toBe('done');
    expect(rows[0]?.angle).toBe('角度1');
    expect(rows[1]?.status).toBe('pending');
  });

  it('失败行按「第N条」精确归位并带原因原文', () => {
    const rows = buildQueueRows(
      [...MODES],
      2,
      [],
      'job-1',
      '剧情解说·第2条: LLM 请求失败: read timeout',
      '剧情解说·第1条',
    );
    expect(rows[0]?.status).toBe('running');
    expect(rows[1]?.status).toBe('failed');
    expect(rows[1]?.reason).toContain('read timeout');
  });

  it('角度名槽位（无编号）按序贪心贴到该模式最早的待定行', () => {
    const rows = buildQueueRows(
      [...MODES],
      2,
      [],
      'job-1',
      '交叉解说·复仇洗白视角: 取材重叠超限',
      '交叉解说·第1条',
    );
    const failed = rows.filter((row) => row.status === 'failed');
    expect(failed).toHaveLength(1);
    expect(failed[0]?.label).toBe('交叉解说');
  });

  it('完成行优先于失败解析：同槽位先成功就不许再判失败', () => {
    const rows = buildQueueRows(
      ['dialogue_narration'],
      1,
      [plan('dialogue_narration', 1)],
      'job-1',
      '剧情解说·第1条: 旧失败',
      '',
    );
    expect(rows[0]?.status).toBe('done');
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
