/** 三统计芯片派生（规格 §4.1）。
 *
 * ETA 是线性外推的量级提示、不是承诺——所以每个退化边界（进度 0、进度 100、
 * 无在跑、elapsed=0、时钟回拨）都要有明确行为，绝不输出 NaN / Infinity / 负数。
 */
import { describe, expect, it } from 'vitest';
import type { WorkItem } from '@dramaclip/protocol';
import { MIN_ETA_PROGRESS, WORKS_SCAN_LIMIT, buildStats, etaLabel, type StatsInput } from '../stats';

const NOW = 1_760_000_000_000;
const MINUTE = 60_000;
const DAY = 86_400_000;

function work(id: string, completedAt: number | undefined): WorkItem {
  return {
    id,
    project_id: 'p1',
    project_name: 'A',
    output_path: `/o/${id}.mp4`,
    completed_at: completedAt,
  };
}

function input(over: Partial<StatsInput> = {}): StatsInput {
  return { dramaCount: 0, running: [], serverTimeMs: NOW, works: [], ...over };
}

describe('etaLabel', () => {
  it('无在跑任务返回空串（视图层据此不渲染那一行）', () => {
    expect(etaLabel([], NOW)).toBe('');
  });

  it('进度低于阈值不外推，直说预计中', () => {
    expect(MIN_ETA_PROGRESS).toBe(5);
    expect(etaLabel([{ id: 'j', progress: 4, createdAtMs: NOW - 10 * MINUTE }], NOW)).toBe('预计中…');
  });

  it('刚入队（elapsed=0）不得输出"预计还需 0 分"这种假精确值', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW }], NOW)).toBe('预计中…');
  });

  it('线性外推：跑了一半、已用 10 分钟 → 还需 10 分钟', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW - 10 * MINUTE }], NOW)).toBe('预计还需 10 分');
  });

  it('多条在跑取最慢的一条', () => {
    const label = etaLabel(
      [
        { id: 'a', progress: 90, createdAtMs: NOW - 10 * MINUTE },
        { id: 'b', progress: 10, createdAtMs: NOW - 10 * MINUTE },
      ],
      NOW,
    );
    expect(label).toBe('预计还需 1 小时 30 分');
  });

  it('混着一条已跑满的残留行不影响其余任务的外推', () => {
    const label = etaLabel(
      [
        { id: 'done', progress: 100, createdAtMs: NOW - 5 * MINUTE },
        { id: 'live', progress: 50, createdAtMs: NOW - 10 * MINUTE },
      ],
      NOW,
    );
    expect(label).toBe('预计还需 10 分');
  });

  it('超过一小时换成小时+分', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW - 90 * MINUTE }], NOW)).toBe(
      '预计还需 1 小时 30 分',
    );
  });

  it('整小时不带"0 分"尾巴', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW - 120 * MINUTE }], NOW)).toBe('预计还需 2 小时');
  });

  it('时钟回拨（server 时间早于 created_at）按 0 处理，不输出负 ETA', () => {
    expect(etaLabel([{ id: 'j', progress: 50, createdAtMs: NOW + 10 * MINUTE }], NOW)).toBe('预计中…');
  });
});

describe('buildStats', () => {
  it('剧数与在跑条数直取，ETA 随行', () => {
    const stats = buildStats(
      input({ dramaCount: 12, running: [{ id: 'j', progress: 50, createdAtMs: NOW - MINUTE }] }),
    );
    expect(stats.dramaCount).toBe(12);
    expect(stats.runningCount).toBe(1);
    expect(stats.runningEtaLabel).toBe('预计还需 1 分');
  });

  it('成品数 = 传入的成片段数', () => {
    expect(buildStats(input({ works: [work('w1', NOW), work('w2', NOW - DAY)] })).workCount).toBe(2);
  });

  it('周增只数近 7 天完成的', () => {
    const works = [work('w1', NOW - DAY), work('w2', NOW - 8 * DAY), work('w3', undefined)];
    const stats = buildStats(input({ works }));
    expect(stats.workCount).toBe(3);
    expect(stats.workWeekDelta).toBe(1);
  });

  it('completed_at 缺失的片不计入周增，但计入总数', () => {
    const stats = buildStats(input({ works: [work('w1', undefined)] }));
    expect(stats.workCount).toBe(1);
    expect(stats.workWeekDelta).toBe(0);
  });

  it('条数触到扫描上限即判溢出：总数标 N+，周增判为不可用', () => {
    const works = Array.from({ length: WORKS_SCAN_LIMIT }, (_, index) => work(`w${String(index)}`, NOW));
    const stats = buildStats(input({ works }));
    expect(stats.workCountOverflow).toBe(true);
    expect(stats.workCount).toBe(WORKS_SCAN_LIMIT);
    expect(stats.workWeekDelta).toBeNull();
  });

  it('差一条到上限不算溢出', () => {
    const works = Array.from({ length: WORKS_SCAN_LIMIT - 1 }, (_, index) => work(`w${String(index)}`, NOW));
    const stats = buildStats(input({ works }));
    expect(stats.workCountOverflow).toBe(false);
    expect(stats.workWeekDelta).toBe(WORKS_SCAN_LIMIT - 1);
  });
});
