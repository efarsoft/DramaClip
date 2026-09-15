/** 最近成品：跨项目最新出片（点击进作品库）。
 *
 * 不出缩略图：逐片封面不存在，拿项目封面冒充逐片封面正是 §4.5 要治的
 * "同剧 9 条片共用一张封面"。缩略图归 P-3.3。
 */
import { useNavigate } from 'react-router-dom';
import type { WorkItem } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { mediaUrl } from '../../services/client';
import { MODE_INFO } from '../../components/modeMeta';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

function modeLabel(mode: string | undefined): string {
  if (mode === undefined) return '成片';
  return MODE_INFO.find((item) => item.mode === mode)?.label ?? mode;
}

function formatDate(ms: number | undefined): string {
  if (ms === undefined) return '';
  const date = new Date(ms);
  return `${String(date.getMonth() + 1)}/${String(date.getDate())} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export function RecentWorks({ works }: { works: readonly WorkItem[] }): React.ReactElement {
  const navigate = useNavigate();
  return (
    <PageSection
      title="最近成品"
      extra={
        works.length > 0 ? (
          <GhostLink
            label="查看全部"
            onClick={() => {
              void navigate('/works');
            }}
          />
        ) : undefined
      }
      dense
    >
      {works.length === 0 ? (
        <div
          style={{
            padding: tokens.spaceLg,
            fontSize: tokens.fontCaption,
            color: tokens.textTertiary,
            textAlign: 'center',
          }}
        >
          还没有成片——出片完成后会出现在这里
        </div>
      ) : (
        works.map((work) => (
          <WorkRow
            key={work.id}
            work={work}
            onClick={() => {
              void navigate('/works');
            }}
          />
        ))
      )}
    </PageSection>
  );
}

function WorkRow({ work, onClick }: { work: WorkItem; onClick: () => void }): React.ReactElement {
  return (
    <div
      onClick={onClick}
      style={{
        ...mixins.listRow(),
        padding: `${String(tokens.spaceSm)} ${String(tokens.spaceLg)}`,
        gap: tokens.spaceMd,
        cursor: 'pointer',
      }}
      onMouseEnter={(event) => {
        event.currentTarget.style.background = tokens.bgElevated;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.background = 'transparent';
      }}
    >
      <span style={{ position: 'relative', flexShrink: 0, width: 56, height: 32, borderRadius: 4, overflow: 'hidden' }}>
        {work.cover_path ? (
          <img
            src={mediaUrl(work.cover_path)}
            alt=""
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          />
        ) : (
          <span
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: tokens.accentSoft,
              color: tokens.colorPrimary,
              fontSize: tokens.fontIcon,
            }}
          >
            ▶
          </span>
        )}
      </span>
      <span
        style={{
          fontSize: tokens.fontCaption,
          color: tokens.textPrimary,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {work.project_name} · {modeLabel(work.narration_mode)}
      </span>
      <span
        style={{
          marginLeft: 'auto',
          flexShrink: 0,
          fontSize: tokens.fontMicro,
          color: tokens.textTertiary,
        }}
      >
        {formatDate(work.completed_at)}
      </span>
    </div>
  );
}

function GhostLink({ label, onClick }: { label: string; onClick: () => void }): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: 'none',
        border: 'none',
        padding: 0,
        color: tokens.colorPrimary,
        fontSize: tokens.fontCaption,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  );
}
