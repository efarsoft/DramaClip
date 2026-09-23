/** 阶段④「渲染」提交侧：export.submit 排队所选方案后**展开任务抽屉**看真进度（卷三图4：
 * 不原地假装进度）；守望任务快照，这批全部终态才刷新出片记录，失败原文上屏不截断。 */
import { useCallback, useEffect, useState } from 'react';
import type { ExportRejection } from '@dramaclip/protocol';
import { exportApi } from '../../services/client';
import { isActiveJob, useJobsStore } from '../../stores/jobs';
import { reasonOr } from './poll';

export interface ExportQueue {
  submitting: boolean;
  rejected: ExportRejection[];
  error: string;
  run: (planIds: string[]) => Promise<void>;
}

export function useExportQueue(onDone: () => Promise<void>): ExportQueue {
  const [submitting, setSubmitting] = useState(false);
  const [rejected, setRejected] = useState<ExportRejection[]>([]);
  const [error, setError] = useState('');
  const [tracked, setTracked] = useState<string[]>([]);
  const setDrawerOpen = useJobsStore((state) => state.setDrawerOpen);
  const jobs = useJobsStore((state) => state.jobs);

  const run = useCallback(
    async (planIds: string[]): Promise<void> => {
      if (planIds.length === 0 || submitting) return;
      setSubmitting(true);
      setRejected([]);
      setError('');
      try {
        const result = await exportApi.submit(planIds);
        setRejected([...result.rejected]);
        const jobIds = result.exports.map((item) => item.job_id);
        if (jobIds.length === 0) return; // 全被拒：不开抽屉，拒绝原因留在界面
        setTracked(jobIds);
        setDrawerOpen(true);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setSubmitting(false);
      }
    },
    [submitting, setDrawerOpen],
  );

  // 守望：这批作业都进了快照且都不再活跃 → 刷记录；失败把原文说出来（不当成功报）。
  // 快照还没见到这批作业时不动——取不到 ≠ 已完成。
  useEffect(() => {
    if (tracked.length === 0) return;
    const found = jobs.filter((job) => tracked.includes(job.id));
    if (found.length === 0 || found.some((job) => isActiveJob(job))) return;
    const failed = found.filter((job) => job.status === 'failed');
    if (failed.length > 0) {
      const detail = failed.map((job) => reasonOr(job.error ?? undefined, `作业 ${job.id}`)).join('；');
      setError(`${String(failed.length)} 条出片失败：${detail}`);
    }
    setTracked([]);
    void onDone();
  }, [jobs, tracked, onDone]);

  return { submitting, rejected, error, run };
}
