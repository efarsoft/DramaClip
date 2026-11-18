/**
 * 任务中心抽屉：全局唯一任务入口（队列页的前身，卷二 §4.3）。
 * 三条诚实纪律：不编速度/ETA（jobs 里没有，只有 % + 阶段词 + 服务端时钟差）；
 * 失败行 error 原文不截断且给「去处理」；取消被拒时把服务端 reason 原样说出来。
 * 行内三段与过滤工具条在 ./JobRow（300 行红线拆出）。
 */
import { Fragment, useEffect, useState, type ReactElement } from 'react';
import { Alert, Drawer, Empty } from 'antd';
import type { JobInfo } from '@dramaclip/protocol';
import { analysisApi, jobsApi, modelsApi, projectApi } from '../../services/client';
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
  const [retryNotes, setRetryNotes] = useState<Readonly<Record<string, string>>>({});
  const retry = (job: JobInfo): void => {
    // 通用重试只有两类有单条 API：模型下载（重发下载）与分析（重跑整项目）；
    // export/narration 的重跑依赖页面上下文（方案参数/导出 id），保持「去处理」路由。
    setRetryNotes((prev) => ({ ...prev, [job.id]: '已重新提交' }));
    const finish = (reason: string): void => {
      setRetryNotes((prev) => ({ ...prev, [job.id]: reason }));
    };
    const call = (() => {
      if (job.type === 'model_download' && job.ref_id !== null && job.ref_id !== '') {
        return modelsApi.download(job.ref_id).then(() => '已重新提交下载');
      }
      if (job.type === 'analysis' && job.ref_id !== null && job.ref_id !== '') {
        return analysisApi.start(job.ref_id).then(() => '已重新提交分析');
      }
      return Promise.reject(new Error('该任务类型请在对应页面重新发起'));
    })();
    call.catch((error: unknown) => {
      finish(error instanceof Error && error.message !== '' ? error.message : String(error));
    });
  };

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
      {shown.map((job) => {
        const retryNote = retryNotes[job.id];
        return (
          <Fragment key={job.id}>
        <JobRow
          key={job.id}
          job={job}
          names={names}
          serverTimeMs={serverTimeMs}
          note={notes[job.id]}
          onCancel={() => {
            cancel(job.id);
          }}
          onRetry={
            job.type === 'model_download' || job.type === 'analysis'
              ? () => {
                  retry(job);
                }
              : undefined
          }
        />
        {retryNote !== undefined && (
          <span style={{ fontSize: tokens.text.badge.size, color: tokens.textSecondary }}>
            {job.label ?? ''}：{retryNote}
          </span>
        )}
          </Fragment>
        );
      })}
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        仅显示最近变更的 200 条任务。
      </span>
      <SessionLogFeed />
    </div>
  );
}

/** 主体名册：抽屉打开时低频拉一次；拉不到就用空名册（退化成短 id，不阻塞任务行）。 */
export function useJobSubjects(open: boolean): JobSubjectNames {
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


/** 本会话留痕（规格 §1.2 实时流）：log.append 按作业归档的滚动视图，只增不清——
 * 事后可查的账在 export_jobs.degraded_notes，这里只服务「作业进行中」的即时观察。 */
export function SessionLogFeed(): React.ReactElement {
  const notifyLog = useJobsStore((state) => state.notifyLog);
  if (notifyLog.length === 0) {
    return (
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        本会话暂无业务日志。
      </span>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        本会话留痕（实时流，重启即失；事后账在任务与成片记录里）
      </span>
      <div style={{ maxHeight: 160, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
        {notifyLog.map((entry, index) => (
          <span
            key={`${String(entry.at)}-${String(index)}`}
            style={{
              fontSize: tokens.text.badge.size,
              lineHeight: tokens.text.badge.leading,
              fontFamily: 'monospace',
              color: entry.level === 'warn' ? tokens.colorWarning : tokens.textTertiary,
              wordBreak: 'break-all',
            }}
          >
            {entry.jobId !== null ? `[${entry.jobId.slice(0, 6)}] ` : ''}
            {entry.message}
          </span>
        ))}
      </div>
    </div>
  );
}
