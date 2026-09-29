/** 任务行一族：状态行/标题行/元信息行 + 抽屉顶部的过滤清空工具条。
 *  从 JobDrawer 拆出（300 行红线）：行内三段各管一件事，工具条只管「看哪些、删哪些」。
 */
import { Button, Popconfirm, Progress, Segmented } from 'antd';
import { useNavigate } from 'react-router-dom';
import type { CSSProperties, ReactElement } from 'react';
import type { JobInfo, JobStatus } from '@dramaclip/protocol';
import { jobsApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { useJobsStore } from '../../stores/jobs';
import {
  durationLabel,
  isActiveJob,
  jobElapsedMs,
  jobRoute,
  jobSubject,
  jobTypeLabel,
  type JobSubjectNames,
} from './jobMeta';

export type CancelNote =
  | { readonly kind: 'sending' | 'cancelling' }
  | { readonly kind: 'rejected'; readonly reason: string };

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

const ROW_STYLE: CSSProperties = {
  background: tokens.bgContainer,
  border: `1px solid ${tokens.borderSecondary}`,
  borderRadius: tokens.radiusControl,
  padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
  display: 'flex',
  flexDirection: 'column',
  gap: tokens.spaceSm,
};

/** 过滤清空工具条：三个计数签 + 清空已结束记录（失败原因原文一并清除）。 */
export function JobsToolbar({
  total,
  failed,
  active,
  filter,
  onFilter,
}: {
  total: number;
  failed: number;
  active: number;
  filter: 'all' | 'failed' | 'active';
  onFilter: (value: 'all' | 'failed' | 'active') => void;
}): ReactElement {
  const finishedCount = total - active;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
      <Segmented
        size="small"
        value={filter}
        onChange={(value) => {
          onFilter(value as 'all' | 'failed' | 'active');
        }}
        options={[
          { label: `全部 ${String(total)}`, value: 'all' },
          { label: `失败 ${String(failed)}`, value: 'failed' },
          { label: `在跑 ${String(active)}`, value: 'active' },
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
  );
}

export function JobRow({
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
