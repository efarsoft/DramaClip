/** 项目卡片：封面 + 集数 + 操作菜单。 */
import { Button, Card, Dropdown } from 'antd';
import type { Project } from '@dramaclip/protocol';
import type { ReactElement } from 'react';
import { mediaUrl } from '../../services/client';
import { tokens } from '../../styles/theme';

export function ProjectCard({
  project,
  onOpen,
  onRename,
  onDuplicate,
  onDelete,
}: {
  project: Project;
  onOpen: (project: Project) => void;
  onRename: (project: Project) => void;
  onDuplicate: (project: Project) => void;
  onDelete: (project: Project) => void;
}): ReactElement {
  return (
    <Card
      hoverable
      styles={{ body: { padding: 0 } }}
      onClick={() => {
        onOpen(project);
      }}
    >
      <CoverArea project={project} handlers={{ onRename, onDuplicate, onDelete }} />
      <div style={{ padding: '12px 14px 14px' }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: tokens.textPrimary }}>{project.name}</div>
        <div
          style={{
            marginTop: 4,
            fontSize: 11.5,
            color: tokens.textTertiary,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {project.source_path}
        </div>
      </div>
    </Card>
  );
}

function CoverArea({
  project,
  handlers,
}: {
  project: Project;
  handlers: MenuHandlers;
}): ReactElement {
  return (
    <div style={{ position: 'relative' }}>
      {project.cover_path !== undefined ? (
        <img
          src={mediaUrl(project.cover_path)}
          alt={project.name}
          style={{ width: '100%', height: 140, objectFit: 'cover', display: 'block' }}
        />
      ) : (
        <div
          style={{
            height: 140,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 30,
            color: tokens.textTertiary,
            background: `linear-gradient(135deg, ${tokens.bgElevated}, ${tokens.bgContainer})`,
          }}
        >
          ▶
        </div>
      )}
      <span
        style={{ position: 'absolute', top: 10, right: 10 }}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <Dropdown menu={{ items: menuFor(project, handlers) }} trigger={['click']}>
          <MoreButton />
        </Dropdown>
      </span>
      <span
        style={{
          position: 'absolute',
          left: 10,
          bottom: 10,
          fontSize: 11,
          padding: '2px 8px',
          borderRadius: 999,
          background: 'rgba(0,0,0,0.55)',
          color: '#FFFFFF',
        }}
      >
        {String(project.episode_count)} 集
      </span>
    </div>
  );
}

function MoreButton(props: React.ComponentProps<typeof Button>): ReactElement {
  return (
    <Button
      type="text"
      size="small"
      style={{ background: 'rgba(0,0,0,0.45)', color: '#FFFFFF' }}
      {...props}
    />
  );
}

interface MenuHandlers {
  onRename: (project: Project) => void;
  onDuplicate: (project: Project) => void;
  onDelete: (project: Project) => void;
}

function menuFor(
  project: Project,
  { onRename, onDuplicate, onDelete }: MenuHandlers,
): NonNullable<React.ComponentProps<typeof Dropdown>['menu']>['items'] {
  return [
    {
      key: 'rename',
      label: '重命名',
      onClick: () => {
        onRename(project);
      },
    },
    {
      key: 'duplicate',
      label: '复制',
      onClick: () => {
        onDuplicate(project);
      },
    },
    { type: 'divider' as const },
    {
      key: 'delete',
      label: '删除',
      danger: true,
      onClick: () => {
        onDelete(project);
      },
    },
  ];
}

