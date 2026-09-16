/** 最近成品：海报卡片网格（16:9 逐片封面 + 时长角标 + 模式标签）。 */
import { useNavigate } from 'react-router-dom';
import type { WorkItem } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { MODE_INFO } from '../../components/modeMeta';
import { mediaUrl } from '../../services/client';
import { tokens } from '../../styles/theme';

function modeLabel(mode: string | undefined): string {
  if (mode === undefined) return '成片';
  return MODE_INFO.find((item) => item.mode === mode)?.label ?? mode;
}

function formatDate(ms: number | undefined): string {
  if (ms === undefined) return '';
  const date = new Date(ms);
  return `${String(date.getMonth() + 1)}/${String(date.getDate())}`;
}

function durationLabel(s: number | undefined): string {
  if (s === undefined || s <= 0) return '';
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
}

export function RecentWorks({ works }: { works: readonly WorkItem[] }): React.ReactElement {
  const navigate = useNavigate();
  return (
    <PageSection
      title="最近成品"
      extra={
        works.length > 0 ? (
          <button
            type="button"
            onClick={() => {
              void navigate('/works');
            }}
            style={{
              background: 'none', border: 'none', padding: 0,
              color: tokens.colorPrimary, fontSize: tokens.fontCaption, cursor: 'pointer',
            }}
          >
            查看全部
          </button>
        ) : undefined
      }
      style={{ background: 'transparent', border: 'none', boxShadow: 'none' }}
    >
      {works.length === 0 ? (
        <div
          style={{
            padding: tokens.spaceLg,
            fontSize: tokens.fontCaption,
            color: tokens.textTertiary,
            textAlign: 'center',
            border: `1px dashed ${tokens.borderSecondary}`,
            borderRadius: tokens.radiusCard,
          }}
        >
          还没有成片——出片完成后会出现在这里
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: tokens.spaceMd }}>
          {works.map((work) => (
            <WorkPoster
              key={work.id}
              work={work}
              onClick={() => {
                void navigate('/works');
              }}
            />
          ))}
        </div>
      )}
    </PageSection>
  );
}

function WorkPoster({ work, onClick }: { work: WorkItem; onClick: () => void }): React.ReactElement {
  return (
    <div
      onClick={onClick}
      style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}
    >
      <div
        style={{
          position: 'relative',
          aspectRatio: '16 / 9',
          borderRadius: tokens.radiusCard,
          overflow: 'hidden',
          background: tokens.bgElevated,
          border: `1px solid ${tokens.borderSecondary}`,
        }}
      >
        {work.cover_path ? (
          <img
            src={mediaUrl(work.cover_path)}
            alt=""
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          />
        ) : (
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: tokens.colorPrimary,
              background: tokens.accentSoft,
            }}
          >
            <span style={{ fontSize: tokens.fontHeading }}>▶</span>
          </div>
        )}
        <span
          style={{
            position: 'absolute', right: 6, bottom: 6,
            background: 'rgba(0,0,0,0.72)', color: tokens.colorWhite,
            fontSize: tokens.fontMicro, padding: '1px 6px',
            borderRadius: tokens.radiusChip, fontFamily: tokens.fontFamilyMono,
          }}
        >
          {durationLabel(work.duration_s)}
        </span>
        <span
          style={{
            position: 'absolute', left: 6, top: 6,
            background: 'rgba(0,0,0,0.72)', color: tokens.colorWhite,
            fontSize: tokens.fontMicro, padding: '1px 6px', borderRadius: tokens.radiusChip,
          }}
        >
          {modeLabel(work.narration_mode)}
        </span>
      </div>
      <div
        style={{
          fontSize: tokens.fontCaption, color: tokens.textSecondary,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}
      >
        {`${work.project_name} · ${formatDate(work.completed_at)}`}
      </div>
    </div>
  );
}
