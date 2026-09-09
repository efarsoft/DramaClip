/** 最近成品：跨项目最新出片（点击进作品库）。 */
import { Card } from 'antd';
import { useNavigate } from 'react-router-dom';
import type { WorkItem } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { MODE_INFO } from '../../components/modeMeta';

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
    <section>
      <SectionHeader>最近成品</SectionHeader>
      <Card size="small" styles={{ body: { padding: '4px 0' } }}>
        {works.length === 0 ? (
          <div style={{ padding: 16, fontSize: 12.5, color: tokens.textTertiary, textAlign: 'center' }}>
            还没有成品——出片完成后会出现在这里
          </div>
        ) : (
          works.map((work) => (
            <div
              key={work.id}
              onClick={() => {
                void navigate('/works');
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '9px 12px',
                cursor: 'pointer',
              }}
              onMouseEnter={(event) => {
                event.currentTarget.style.background = tokens.bgElevated;
              }}
              onMouseLeave={(event) => {
                event.currentTarget.style.background = 'transparent';
              }}
            >
              <span style={{ fontSize: 12.5, color: tokens.textPrimary, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {work.project_name} · {modeLabel(work.narration_mode)}
              </span>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: tokens.textTertiary, flexShrink: 0 }}>
                {formatDate(work.completed_at)}
              </span>
            </div>
          ))
        )}
        {works.length > 0 && (
          <div
            onClick={() => {
              void navigate('/works');
            }}
            style={{ padding: '8px 12px', fontSize: 12, color: tokens.colorPrimary, cursor: 'pointer' }}
          >
            查看全部 →
          </div>
        )}
      </Card>
    </section>
  );
}

function SectionHeader({ children }: { children: string }): React.ReactElement {
  return (
    <h3
      style={{
        margin: '0 0 12px',
        fontSize: 15,
        fontWeight: 600,
        color: tokens.textPrimary,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span style={{ width: 3, height: 14, borderRadius: 2, background: tokens.gradientAccent }} />
      {children}
    </h3>
  );
}
