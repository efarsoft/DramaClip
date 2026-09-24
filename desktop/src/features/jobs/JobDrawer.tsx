/**
 * 任务中心抽屉：全局唯一任务入口（队列页的前身，卷二 §4.3）。
 * 三条诚实纪律：不编速度/ETA（jobs 里没有，只有 % + 阶段词 + 服务端时钟差）；
 * 失败行 error 原文不截断且给「去处理」；取消被拒时把服务端 reason 原样说出来。
 */
import { useEffect, useState, type CSSProperties, type ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Drawer, Empty, Popconfirm, Progress, Segmented } from 'antd';
import type { JobInfo, JobStatus } from '@dramaclip/protocol';
import { jobsApi, modelsApi, projectApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { useJobsStore } from '../../stores/jobs';
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
  type JobSubjectNames,
} from './jobMeta';

const STATUS_TEXT: Readonly<Record<JobStatus, string>> = {
  pending: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const STATUS_COLOR: Readonly<Record<JobStatus, string>> = {
  pending: tokens.colorWarning,
  running: tokens.colorInfo,
  completed: tokens.colorSuccess,
  failed: tokens.colorError,
  cancelled: tokens.textTertiary,
};

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
  const finishedCount = jobs.length - summary.active;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
        <Segmented
          size="small"
          value={filter}
          onChange={(value) => {
            setFilter(value as Filter);
          }}
          options={[
            { label: `全部 ${String(jobs.length)}`, value: 'all' },
            { label: `失败 ${String(summary.failed)}`, value: 'failed' },
            { label: `在跑 ${String(summary.active)}`, value: 'active' },
          ]}
        />
        <span style={{ flex: 1 }} />
        {finishedCount > 0 && (
          <Popconfirm
            title={`清空 ${String(finishedCount)} 条已结束记录？`}
            description="完成/失败/取消的都会删掉，失败原因原文一并清除；在跑与排队中的不受影响。"
            okText="清空"
            cancelText="取消"
            onConfirm={() => {
              void jobsApi.clearFinished();
            }}
          >
            <Button size="small" type="text">清空记录</Button>
          </Popconfirm>
        )}
      </div>
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

type CancelNote =
  | { readonly kind: 'sending' | 'cancelling' }
  | { readonly kind: 'rejected'; readonly reason: string };

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

const ROW_STYLE: CSSProperties = {
  background: tokens.bgContainer,
  border: `1px solid ${tokens.borderSecondary}`,
  borderRadius: tokens.radiusControl,
  padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
  display: 'flex',
  flexDirection: 'column',
  gap: tokens.spaceSm,
};

function JobRow({
  job,
  names,
  serverTimeMs,
  note,
  onCancel,
}: {
  job: JobInfo;
  names: JobSubjectNames;
  serverTimeMs: number | null;
  note: CancelNote | undefined;
  onCancel: () => void;
}): ReactElement {
  const elapsed = jobElapsedMs(job, serverTimeMs);
  return (
    <div style={ROW_STYLE}>
      <JobTitleLine job={job} names={names} />
      {job.status === 'running' && <Progress percent={Math.round(job.progress)} size="small" status="active" />}
      <JobMetaLine job={job} elapsed={elapsed} note={note} onCancel={onCancel} />
      {job.status === 'failed' && job.error !== null && job.error !== undefined && job.error !== '' && (
        <span
          style={{
            fontSize: tokens.text.meta.size,
            lineHeight: tokens.text.meta.leading,
            color: tokens.colorError,
            background: tokens.errorSoft,
            borderRadius: tokens.radiusControl,
            padding: `${tokens.spaceXs} ${tokens.spaceSm}`,
          }}
        >
          {job.error}
        </span>
      )}
    </div>
  );
}

function JobTitleLine({ job, names }: { job: JobInfo; names: JobSubjectNames }): ReactElement {
  const navigate = useNavigate();
  const setOpen = useJobsStore((state) => state.setDrawerOpen);
  const route = jobRoute(job);
  const go = (): void => {
    if (route === null) return;
    setOpen(false);
    void navigate(route);
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
      <span style={mixins.statusDot(STATUS_COLOR[job.status])} />
      <span
        style={{
          fontSize: tokens.text.body.size,
          lineHeight: tokens.text.body.leading,
          fontWeight: 600,
          color: tokens.textPrimary,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={`${jobTypeLabel(job.type)} · ${jobSubject(job, names)}`}
      >
        {jobTypeLabel(job.type)} · {jobSubject(job, names)}
      </span>
      <span
        style={{
          marginLeft: 'auto',
          flexShrink: 0,
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: STATUS_COLOR[job.status],
        }}
      >
        {STATUS_TEXT[job.status]}
      </span>
      {route !== null && (
        <Button size="small" type="link" style={{ flexShrink: 0 }} onClick={go}>
          {job.status === 'failed' ? '去处理' : '查看'}
        </Button>
      )}
    </div>
  );
}

function JobMetaLine({
  job,
  elapsed,
  note,
  onCancel,
}: {
  job: JobInfo;
  elapsed: number | null;
  note: CancelNote | undefined;
  onCancel: () => void;
}): ReactElement | null {
  const parts: string[] = [];
  if (job.status === 'running' && job.label !== null && job.label !== undefined && job.label !== '') {
    parts.push(job.label);
  }
  if (job.status === 'pending') parts.push('等待并发额度');
  if (elapsed !== null) parts.push(`${isActiveJob(job) ? '已进行' : '耗时'} ${durationLabel(elapsed)}`);
  const showCancel = isActiveJob(job);
  if (parts.length === 0 && !showCancel) return null;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
        color: tokens.textTertiary,
      }}
    >
      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {parts.join(' · ')}
      </span>
      {note?.kind === 'rejected' && (
        <span style={{ color: tokens.colorWarning, flexShrink: 0 }}>无法取消：{note.reason}</span>
      )}
      {showCancel && (
        <span style={{ marginLeft: 'auto', flexShrink: 0 }}>
          {note?.kind === 'cancelling' ? (
            <span>已请求取消，等任务在检查点退出</span>
          ) : (
            <Button size="small" loading={note?.kind === 'sending'} onClick={onCancel}>
              取消
            </Button>
          )}
        </span>
      )}
    </div>
  );
}
