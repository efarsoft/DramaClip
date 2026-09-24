// @vitest-environment node
/** 任务展示元数据：类型词 / 路由 / 主体 / 排序 / 时长——真值表钉死，防止路由语义漂移。 */
import { describe, expect, it } from 'vitest';
import type { JobInfo } from '@dramaclip/protocol';
import {
  durationLabel,
  EMPTY_NAMES,
  isActiveJob,
  jobElapsedMs,
  jobRoute,
  jobSubject,
  jobTypeLabel,
  sortJobs,
  summarizeJobs,
} from '../jobMeta';

function job(over: Partial<JobInfo> = {}): JobInfo {
  return {
    id: 'j1',
    type: 'analysis',
    ref_id: 'p1',
    status: 'running',
    progress: 40,
    created_at: 1_000,
    updated_at: 2_000,
    ...over,
  };
}

const NAMES = {
  projects: new Map([['p1', '替嫁新娘']]),
  models: new Map([['whisper-small', 'Whisper Small（均衡）']]),
};

describe('类型词与路由', () => {
  it('九种线上类型都有中文词；未知类型原样透出', () => {
    expect(jobTypeLabel('prescreen')).toBe('预筛');
    expect(jobTypeLabel('indextts_runtime')).toBe('配音环境安装');
    expect(jobTypeLabel('something_new')).toBe('something_new');
  });

  it('项目引用型才路由进项目；export 走成品详情；环境类聚合到引擎；semantic 无处可去', () => {
    expect(jobRoute(job())).toBe('/projects/p1/analysis');
    expect(jobRoute(job({ type: 'narration' }))).toBe('/projects/p1/produce');
    expect(jobRoute(job({ type: 'export', ref_id: 'e9' }))).toBe('/works/e9');
    expect(jobRoute(job({ type: 'model_download', ref_id: 'whisper-small' }))).toBe('/engines');
    expect(jobRoute(job({ type: 'semantic', ref_id: 'ep1' }))).toBeNull();
    expect(jobRoute(job({ ref_id: null }))).toBeNull();
  });
});

describe('主体文案', () => {
  it('名册翻得出就用名字，翻不出用短 id——不编造', () => {
    expect(jobSubject(job(), NAMES)).toBe('替嫁新娘');
    expect(jobSubject(job({ ref_id: 'unknown-project' }), NAMES)).toBe('项目 unknown-');
    expect(jobSubject(job({ type: 'model_download', ref_id: 'whisper-small' }), NAMES)).toBe(
      'Whisper Small（均衡）',
    );
    expect(jobSubject(job({ type: 'cuda_runtime', ref_id: 'cuda-runtime' }), EMPTY_NAMES)).toBe(
      'CUDA 运行环境',
    );
    expect(jobSubject(job({ type: 'semantic', ref_id: 'ep1' }), EMPTY_NAMES)).toBe('单集语义重对齐');
    expect(jobSubject(job({ type: 'export', ref_id: 'export-1234567890' }), EMPTY_NAMES)).toBe(
      'export-1',
    );
  });
});

describe('汇总与排序', () => {
  it('在跑 = pending+running；失败单列；进度取最新启动的在跑 job', () => {
    const jobs = [
      job({ status: 'running' }),
      job({ id: 'j2', status: 'pending' }),
      job({ id: 'j3', status: 'failed' }),
      job({ id: 'j4', status: 'completed' }),
    ];
    expect(summarizeJobs(jobs)).toEqual({ active: 2, failed: 1, runningPercent: 40 });
    expect(isActiveJob(job({ status: 'pending' }))).toBe(true);
    expect(isActiveJob(job({ status: 'cancelled' }))).toBe(false);
  });

  it('状态栏进度跟随最新启动的在跑 job（created_at 新者优先）', () => {
    const jobs = [
      job({ id: 'old', status: 'running', progress: 90, created_at: 1_000 }),
      job({ id: 'new', status: 'running', progress: 12, created_at: 5_000 }),
    ];
    expect(summarizeJobs(jobs).runningPercent).toBe(12);
  });

  it('没有在跑 job 时进度为 null（缺席而非编 0）', () => {
    const jobs = [job({ status: 'failed', progress: 40 }), job({ status: 'completed' })];
    expect(summarizeJobs(jobs)).toEqual({ active: 0, failed: 1, runningPercent: null });
  });

  it('失败优先，其次在跑，终态垫底；同级按最近变更倒序', () => {
    const jobs = [
      job({ id: 'done', status: 'completed', updated_at: 90 }),
      job({ id: 'fail-old', status: 'failed', updated_at: 10 }),
      job({ id: 'run', status: 'running', updated_at: 50 }),
      job({ id: 'fail-new', status: 'failed', updated_at: 80 }),
      job({ id: 'cancel', status: 'cancelled', updated_at: 70 }),
    ];
    expect(sortJobs(jobs).map((item) => item.id)).toEqual([
      'fail-new',
      'fail-old',
      'run',
      'cancel',
      'done',
    ]);
  });
});

describe('时长文本（只用服务端毫秒时钟差）', () => {
  it('秒/分/时/天四档；负数按 0 兜底', () => {
    expect(durationLabel(38_000)).toBe('38秒');
    expect(durationLabel(252_000)).toBe('4分12秒');
    expect(durationLabel(3_900_000)).toBe('1时05分');
    expect(durationLabel(183_600_000)).toBe('2天3时');
    expect(durationLabel(-5_000)).toBe('0秒');
  });

  it('在跑 = server_time_ms − created_at；终态 = updated_at − created_at 定格', () => {
    expect(jobElapsedMs(job({ created_at: 1_000 }), 5_000)).toBe(4_000);
    expect(jobElapsedMs(job({ status: 'failed', created_at: 1_000, updated_at: 3_000 }), 99_000)).toBe(
      2_000,
    );
    expect(jobElapsedMs(job(), null)).toBeNull();
  });
});
