import type { ComputeReport, JobInfo } from '@dramaclip/protocol';
import { describe, expect, it } from 'vitest';

describe('ComputeReport 协议类型', () => {
  it('任务可以携带回执数组', () => {
    const report: ComputeReport = {
      component: 'asr.whisper', requested: 'auto', resolved: 'cpu',
      actual: 'cpu', fallback: false, reason: 'CT2 需要 sm_61', device: 'cpu',
    };
    const job = {
      id: 'j1', type: 'analysis', ref_id: null, status: 'completed', progress: 100,
      created_at: 1, updated_at: 2, compute: [report],
    } satisfies JobInfo;
    expect(job.compute[0]?.actual).toBe('cpu');
  });
});
