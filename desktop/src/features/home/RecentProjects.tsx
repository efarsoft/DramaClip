import { Card } from 'antd';
import { RightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { SectionTitle } from './SectionTitle';

const STATUS_META: Record<string, { label: string; color: string }> = {
  ready: { label: '就绪', color: tokens.colorSuccess },
  analyzing: { label: '分析中', color: tokens.colorInfo },
  failed: { label: '异常', color: tokens.colorError },
};

/** 最近项目列表（工作台）。 */
export function RecentProjects({ projects }: { projects: Project[] }) {
  const navigate = useNavigate();
  return (
    <section>
      <SectionTitle>最近项目</SectionTitle>
      {projects.length === 0 ? (
        <Card variant="outlined">
          <div style={{ textAlign: 'center', color: tokens.textTertiary, padding: 28 }}>
            还没有项目——点击右上角「新建项目」，选择剧集文件夹开始
          </div>
        </Card>
      ) : (
        <Card styles={{ body: { padding: '6px 0' } }}>
          {projects.map((project) => (
            <ProjectRow
              key={project.id}
              project={project}
              onOpen={() => {
                void navigate(`/projects/${project.id}/analysis`);
              }}
            />
          ))}
        </Card>
      )}
    </section>
  );
}

function ProjectRow({ project, onOpen }: { project: Project; onOpen: () => void }) {
  const meta = STATUS_META[project.status] ?? { label: project.status, color: tokens.textTertiary };
  return (
    <div
      onClick={onOpen}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '13px 18px',
        cursor: 'pointer',
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
      onMouseEnter={(event) => {
        event.currentTarget.style.background = tokens.bgElevated;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.background = 'transparent';
      }}
    >
      <strong style={{ fontSize: 14, color: tokens.textPrimary }}>{project.name}</strong>
      <span
        style={{
          fontSize: 11,
          padding: '1px 8px',
          borderRadius: 10,
          background: tokens.bgElevated,
          color: tokens.textSecondary,
        }}
      >
        {String(project.episode_count)} 集
      </span>
      <span
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          fontSize: 12,
          color: tokens.textTertiary,
        }}
      >
        <span style={{ color: meta.color }}>● {meta.label}</span>
        <RightOutlined style={{ fontSize: 10 }} />
      </span>
    </div>
  );
}
