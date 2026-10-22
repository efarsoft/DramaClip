/** 队列页（规格 §3.5）：跨剧作业一览 + 本会话实时留痕。
 *
 * 双读并标来源：任务列表来自 jobs.list 轮询快照（账），底部滚动来自 log.append
 * 实时流（流）——两路各自标明，不混装成一个真相。失败行带原因与重试（仅导出类：
 * export.retry 复用原 export_id 覆盖写；其余类型无幂等重跑语义，不提供）。
 * 取消复用抽屉同款处置（useCancelJob 逻辑同源，规格 §1.3 不新建）。
 */
import { Button } from 'antd';
import { useCallback, useState, type ReactElement } from 'react';
import { PageHeader, PageShell } from '../../components/layout/PageKit';
import { StateBlock } from '../../components/family/StateBlock';
import { exportApi, jobsApi } from '../../services/client';
import { useJobsStore } from '../../stores/jobs';
import { useUiStore } from '../../stores/ui';
import { JobRow, type CancelNote } from './JobRow';
import type { JobSubjectNames } from './jobMeta';
import { SessionLogFeed, useJobSubjects } from './JobDrawer';

export function QueuePage(): ReactElement {
  const serviceState = useUiStore((state) => state.serviceState);
  const jobs = useJobsStore((state) => state.jobs);
  const available = useJobsStore((state) => state.available);
  const error = useJobsStore((state) => state.error);
  const names = useJobSubjects(true);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, CancelNote>>({});

  const cancel = useCallback(
    (jobId: string): void => {
      setNotes((prev) => ({ ...prev, [jobId]: { kind: 'sending' } }));
      jobsApi
        .cancel(jobId)
        .then((result) => {
          setNotes((prev) => ({
            ...prev,
            [jobId]: result.cancelling
              ? { kind: 'cancelling' }
              : { kind: 'rejected', reason: result.reason ?? '不可取消' },
          }));
        })
        .catch(() => {
          setNotes((prev) => ({ ...prev, [jobId]: { kind: 'rejected', reason: '取消失败' } }));
        });
    },
    [],
  );

  const retry = useCallback((jobId: string, refId: string): void => {
    setRetrying(jobId);
    exportApi
      .retry(refId)
      .catch(() => undefined)
      .finally(() => setRetrying(null));
  }, []);

  if (serviceState !== 'ready') {
    return (
      <PageShell>
        <PageHeader title="队列" desc="跨项目任务一览 · 账来自轮询快照，下方滚动来自实时流" />
        <StateBlock state="loading" loadingText="等待服务就绪" />
      </PageShell>
    );
  }
  if (!available) {
    return (
      <PageShell>
        <PageHeader title="队列" desc="跨项目任务一览 · 账来自轮询快照，下方滚动来自实时流" />
        <StateBlock state="error" errorText={`任务列表取不到：${error ?? '原因未知'}`} onRetry={() => undefined} />
      </PageShell>
    );
  }

  const state: 'ready' | 'empty' = jobs.length === 0 ? 'empty' : 'ready';
  return (
    <PageShell>
      <PageHeader title="队列" desc="跨项目任务一览 · 账来自轮询快照，下方滚动来自实时流" />
      <StateBlock state={state === 'empty' ? 'empty' : 'ready'} emptyText="还没有任务记录">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {jobs.map((job) => {
            const retriable = job.status === 'failed' && job.type === 'export';
            const note = notes[job.id];
            return (
              <div key={job.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <JobRow
                  job={job}
                  names={names}
                  serverTimeMs={null}
                  note={note}
                  onCancel={() => cancel(job.id)}
                  onRetry={
                    retriable && job.ref_id !== null
                      ? () => retry(job.id, job.ref_id ?? '')
                      : undefined
                  }
                />
              </div>
            );
          })}
        </div>
      </StateBlock>
      <SessionLogFeed />
    </PageShell>
  );
}
