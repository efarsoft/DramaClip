/** 出片记录：本项目历次导出的终态列表，点开进成片详情；失败行带重试（规格 §1.3）。 */
import { Button, Empty, Tag, Tooltip } from 'antd';
import { PageSection } from '../../components/layout/PageKit';
import { useNavigate } from 'react-router-dom';
import { useState, type ReactElement } from 'react';
import type { ExportJob } from '@dramaclip/protocol';
import { modeLabel } from '../../components/modeMeta';
import { computeLabel } from '../engines/assetState';
import { errorText } from '../engines/errorText';
import { exportApi } from '../../services/client';
import { reasonOr } from './poll';
import { tokens } from '../../styles/theme';

export function ExportsCard({
  exports,
  onRefresh,
}: {
  exports: ExportJob[] | null;
  onRefresh: () => void;
}) {
  return (
    <PageSection title="出片记录" dense>
      {exports === null ? null : exports.length === 0 ? (
        <Empty description="还没有出片记录——选好方案点「出片所选」" styles={{ image: { height: 60 } }} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
          {exports.map((job) => (
            <ExportRow key={job.id} job={job} onRefresh={onRefresh} />
          ))}
        </div>
      )}
    </PageSection>
  );
}

function ExportRow({ job, onRefresh }: { job: ExportJob; onRefresh: () => void }) {
  const navigate = useNavigate();
  const [retrying, setRetrying] = useState(false);
  const [retryProblem, setRetryProblem] = useState('');
  const label = job.status === 'completed' ? '完成' : job.status === 'failed' ? '失败' : '进行中';
  const color = job.status === 'completed' ? 'success' : job.status === 'failed' ? 'error' : 'processing';
  const first = job.compute?.[0];
  const runtime = computeLabel(first);
  const degraded = job.degraded_notes ?? [];

  const retry = (): void => {
    if (retrying) return;
    setRetrying(true);
    setRetryProblem('');
    exportApi
      .retry(job.id)
      .then(() => onRefresh())
      .catch((error: unknown) => {
        setRetryProblem(errorText(error, '服务端未给出原因'));
      })
      .finally(() => setRetrying(false));
  };

  // 详情页要播成片、读旁挂时间轴，未成功的行里这两样都还没有——点进去是黑房子（规格 §1.6）。
  const openable = job.status === 'completed' && job.output_path !== undefined && job.output_path !== '';

  // 原话进可见文本，Tooltip 只作溢出补充（规格 H3 §3.1.4：可见文本只有「原因」二字是档1 判过的违规）。
  const failureNote =
    retryProblem !== ''
      ? `重试失败：${retryProblem}`
      : `导出失败：${reasonOr(job.error, '服务端未给出原因')}`;

  return (
    <div
      onClick={
        openable
          ? (): void => {
              void navigate(`/works/${job.id}`);
            }
          : undefined
      }
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `${tokens.spaceSm} 0`,
        borderBottom: `1px solid ${tokens.borderSecondary}`,
        fontSize: tokens.text.body.size,
        lineHeight: tokens.text.body.leading,
        cursor: openable ? 'pointer' : 'default',
      }}
    >
      <Tag color={color}>{label}</Tag>
      {job.status === 'failed' ? (
        <Tooltip title={failureNote}>
          <span
            style={{
              color: tokens.errorText,
              fontSize: tokens.text.badge.size,
              lineHeight: tokens.text.badge.leading,
              marginLeft: tokens.spaceSm,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {failureNote}
          </span>
        </Tooltip>
      ) : null}
      {job.status === 'failed' ? (
        <Button
          size="small"
          loading={retrying}
          onClick={(event) => {
            event.stopPropagation();
            retry();
          }}
        >
          重试
        </Button>
      ) : null}
      <span style={{ color: tokens.textPrimary }}>{modeLabel(job.narration_mode)}</span>
      {degraded.length > 0 ? (
        <Tooltip
          title={degraded.map((note, index) => (
            <div key={note.at + String(index)}>
              {note.subject}：{note.outcome}
            </div>
          ))}
        >
          <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, marginLeft: tokens.spaceSm, color: tokens.textTertiary }}>
            降级 {degraded.length}
          </span>
        </Tooltip>
      ) : null}
      {runtime !== undefined && (
        <span
          style={{
            marginLeft: 'auto',
            fontSize: tokens.text.meta.size,
            lineHeight: tokens.text.meta.leading,
            color: first?.fallback === true ? tokens.colorWarning : tokens.textTertiary,
          }}
        >
          {runtime}
        </span>
      )}
      <span style={{ marginLeft: runtime === undefined ? 'auto' : tokens.spaceSm, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, fontFamily: tokens.fontFamilyMono, fontVariantNumeric: 'tabular-nums', color: tokens.textTertiary }}>
        {job.duration_s !== undefined ? `${String(Math.round(job.duration_s))}s` : '—'}
      </span>
    </div>
  );
}
