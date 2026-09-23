// @vitest-environment node
/** produceView 纯逻辑：磁盘预估系数（实测均值）与覆盖度行的分子分母。 */
import { describe, expect, it } from 'vitest';
import type { ExportJob, NarrationPlan } from '@dramaclip/protocol';
import { avgCompletedBytes, coverageOf, estimateDisk } from '../produceView';

function exportJob(over: Partial<ExportJob> = {}): ExportJob {
  return {
    id: 'x1',
    project_id: 'p1',
    status: 'completed',
    progress: 100,
    created_at: 0,
    size_bytes: 1073741824,
    ...over,
  };
}

function plan(id: string, episodeIds: string[]): NarrationPlan {
  return {
    id,
    project_id: 'p1',
    narration_mode: 'cross_narration',
    episode_ids: episodeIds,
    plan_data: { mode: 'cross_narration', timeline: [], narration_texts: [] },
    status: 'ready',
    created_at: 0,
  };
}

describe('磁盘预估系数（意见08：估字要带得出出处）', () => {
  it('只用已完成且有实测体积的成片算均值', () => {
    expect(
      avgCompletedBytes([
        exportJob({ size_bytes: 1000 }),
        exportJob({ id: 'x2', size_bytes: 3000 }),
        exportJob({ id: 'x3', status: 'failed', size_bytes: 99999 }),
        exportJob({ id: 'x4', status: 'completed', size_bytes: 0 }),
      ]),
    ).toBe(2000);
  });

  it('没有成片 / 列表没取到：null，不编系数', () => {
    expect(avgCompletedBytes([])).toBeNull();
    expect(avgCompletedBytes(null)).toBeNull();
    expect(avgCompletedBytes([exportJob({ status: 'failed' })])).toBeNull();
  });

  it('条数为 0 或无系数：diskGb 为 null（界面显示「—」），source 说明原因', () => {
    expect(estimateDisk(0, 1000).diskGb).toBeNull();
    const none = estimateDisk(2, null);
    expect(none.diskGb).toBeNull();
    expect(none.source).toContain('没有实测均值');
  });

  it('有系数：条数 × 均值，GB 一位小数并写明「估」', () => {
    const estimate = estimateDisk(3, 1073741824);
    expect(estimate.diskGb).toBe('约 3.0 GB（估）');
    expect(estimate.source).toContain('实测均值');
  });
});

describe('覆盖度行（静默清单第 2 条）', () => {
  it('分子是本批方案取材集合并计数（同一集只算一次），分母是全剧集数', () => {
    expect(coverageOf([plan('a', ['e1', 'e2']), plan('b', ['e2', 'e3'])], 10)).toEqual({
      covered: 3,
      total: 10,
    });
  });

  it('没有方案或集数拿不到：null（常驻行不拿 0/0 充数）', () => {
    expect(coverageOf([], 10)).toBeNull();
    expect(coverageOf([plan('a', ['e1'])], 0)).toBeNull();
  });
});
