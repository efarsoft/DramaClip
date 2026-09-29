/**
 * 任务中心抽屉：全局唯一任务入口（队列页的前身，卷二 §4.3）。
 * 三条诚实纪律：不编速度/ETA（jobs 里没有，只有 % + 阶段词 + 服务端时钟差）；
 * 失败行 error 原文不截断且给「去处理」；取消被拒时把服务端 reason 原样说出来。
 * 行内三段与过滤工具条在 ./JobRow（300 行红线拆出）。
 */
import { useEffect, useState, type ReactElement } from 'react';
import { Alert, Drawer, Empty } from 'antd';
import type { JobInfo } from '@dramaclip/protocol';
import { jobsApi, modelsApi, projectApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { useJobsStore } from '../../stores/jobs';
import {
  EMPTY_NAMES,
  isActiveJob,
  sortJobs,
  summarizeJobs,
  type JobSubjectNames,
} from './jobMeta';
import { JobRow, JobsToolbar, type CancelNote } from './JobRow';

type Filter = 'all' | 'failed' | 'active';

function matches(job: JobInfo, filter: Filter): boolean {
  if (filter === 'failed') return job.status === 'failed';
  if (filter === 'active') return isActiveJob(job);
  return true;
}

export function JobDrawer(): ReactElement {
  const open = useJobsStore((state) => state.drawerOpen);
  const setOpen = useJobsStore((state) => state.setDrawerOpen);
  return (
    <Drawer
      title="任务中心"
      placement="right"
      size={430}
      open={open}
      onClose={() => {
        setOpen(false);
      }}
    >
      {open && <JobsBody />}
    </Drawer>
  );
}

function JobsBody(): ReactElement {
  const jobs = useJobsStore((state) => state.jobs);
  const available = useJobsStore((state) => state.available);
  const error = useJobsStore((state) => state.error);
  const serverTimeMs = useJobsStore((state) => state.serverTimeMs);
  const open = useJobsStore((state) => state.drawerOpen);
  const names = useJobSubjects(open);
  const [filter, setFilter] = useState<Filter>('all');
  const [notes, cancel] = useCancelJob();

  if (!available) {
    return (
      <Alert
        type="error"
        showIcon
        title="任务状态取不到"
        description={`${error ?? '原因未知'}。恢复前这里无法列出任务；服务状态可在底部状态栏查看。`}
      />
    );
  }
  const summary = summarizeJobs(jobs);
  const shown = sortJobs(jobs).filter((job) => matches(job, filter));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <JobsToolbar
        total={jobs.length}
        failed={summary.failed}
        active={summary.active}
        filter={filter}
        onFilter={setFilter}
      />
      {shown.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合条件的任务" />}
      {shown.map((job) => (
        <JobRow
          key={job.id}
          job={job}
          names={names}
          serverTimeMs={serverTimeMs}
          note={notes[job.id]}
          onCancel={() => {
            cancel(job.id);
          }}
        />
      ))}
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        仅显示最近变更的 200 条任务。
      </span>
    </div>
  );
}

/** 主体名册：抽屉打开时低频拉一次；拉不到就用空名册（退化成短 id，不阻塞任务行）。 */
function useJobSubjects(open: boolean): JobSubjectNames {
  const [names, setNames] = useState<JobSubjectNames>(EMPTY_NAMES);
  useEffect(() => {
    if (!open) return;
    let stopped = false;
    void Promise.all([projectApi.list().catch(() => []), modelsApi.list().catch(() => [])]).then(
      ([projects, models]) => {
        if (stopped) return;
        setNames({
          projects: new Map(projects.map((item) => [item.id, item.name])),
          models: new Map(models.map((item) => [item.model_id, item.name])),
        });
      },
    );
    return () => {
      stopped = true;
    };
  }, [open]);
  return names;
}

function useCancelJob(): [Readonly<Record<string, CancelNote>>, (jobId: string) => void] {
  const [notes, setNotes] = useState<Readonly<Record<string, CancelNote>>>({});
  const cancel = (jobId: string): void => {
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
      .catch((error: unknown) => {
        const reason = error instanceof Error && error.message !== '' ? error.message : String(error);
        setNotes((prev) => ({ ...prev, [jobId]: { kind: 'rejected', reason } }));
      });
  };
  return [notes, cancel];
}
