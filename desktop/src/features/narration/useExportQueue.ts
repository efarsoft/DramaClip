/** 阶段④「渲染」：export.submit 排队所选方案，轮询到全部终态再刷新记录。 */
import { useCallback, useRef, useState } from 'react';
import type { ExportRejection } from '@dramaclip/protocol';
import { exportApi, jobsApi } from '../../services/client';
import { POLL_INTERVAL_MS, isTerminal, reasonOr, sleep } from './poll';

export interface ExportQueue {
  running: boolean;
  percent: number;
  stageText: string;
  rejected: ExportRejection[];
  error: string;
  run: (planIds: string[]) => Promise<void>;
  cancel: () => Promise<void>;
}

export function useExportQueue(projectId: string, onDone: () => Promise<void>): ExportQueue {
  const [running, setRunning] = useState(false);
  const [percent, setPercent] = useState(0);
  const [stageText, setStageText] = useState('');
  const [rejected, setRejected] = useState<ExportRejection[]>([]);
  const [error, setError] = useState('');
  const jobIdsRef = useRef<string[]>([]);

  const cancel = useCallback(async (): Promise<void> => {
    await Promise.all(jobIdsRef.current.map((jobId) => jobsApi.cancel(jobId)));
  }, []);

  const run = useCallback(
    async (planIds: string[]): Promise<void> => {
      if (planIds.length === 0 || running) return;
      setRunning(true);
      setRejected([]);
      setError('');
      setPercent(0);
      setStageText('提交出片任务');
      try {
        const result = await exportApi.submit(planIds);
        setRejected([...result.rejected]);
        const queued = result.exports.map((item) => item.export_id);
        jobIdsRef.current = result.exports.map((item) => item.job_id);
        if (queued.length === 0) {
          return;
        }
        for (;;) {
          const jobs = await exportApi.list(projectId);
          const tracked = jobs.filter((job) => queued.includes(job.id));
          const missing = queued.filter((id) => !tracked.some((job) => job.id === id));
          if (tracked.length === 0) {
            setError(`查不到这批导出记录: ${missing.join(', ')}`);
            return;
          }
          setPercent(tracked.reduce((sum, job) => sum + job.progress, 0) / tracked.length);
          setStageText(`出片中 ${String(tracked.length)} 条`);
          if (tracked.every((job) => isTerminal(job.status))) {
            const failed = tracked.filter((job) => job.status === 'failed');
            if (failed.length > 0) {
              setError(`${String(failed.length)} 条出片失败: ${failed.map((job) => reasonOr(job.error, job.id)).join('；')}`);
            }
            await onDone();
            return;
          }
          await sleep(POLL_INTERVAL_MS);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        jobIdsRef.current = [];
        setRunning(false);
        setStageText('');
      }
    },
    [onDone, projectId, running],
  );

  return { running, percent, stageText, rejected, error, run, cancel };
}
