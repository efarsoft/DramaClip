/** 项目卡片：封面 + 集数 + 操作菜单。 */
import { PlayCircleFilled } from '@ant-design/icons';
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
      <div style={{ padding: `${tokens.spaceSm} ${tokens.spaceLg} ${tokens.spaceMd}` }}>
        <div style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>{project.name}</div>
        <div
          style={{
            marginTop: tokens.spaceXs,
            fontSize: tokens.text.badge.size,
            lineHeight: tokens.text.badge.leading,
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
    <div className="project-cover" style={{ position: 'relative' }}>
      {project.cover_path !== undefined ? (
        <img
          src={mediaUrl(project.cover_path)}
          alt={project.name}
          style={{ width: '100%', aspectRatio: '9 / 16', objectFit: 'cover', display: 'block' }}
        />
      ) : (
        <div
          style={{
            aspectRatio: '9 / 16',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: tokens.glyph.poster,
            color: tokens.textTertiary,
            background: `linear-gradient(135deg, ${tokens.bgElevated}, ${tokens.bgContainer})`,
          }}
        >
          <PlayCircleFilled />
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
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          padding: '2px 8px',
          borderRadius: tokens.radiusChip,
          background: 'rgba(0,0,0,0.55)',
          color: tokens.colorWhite,
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
      style={{ background: 'rgba(0,0,0,0.45)', color: tokens.colorWhite }}
      {...props}
    >
      ⋯
    </Button>
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

