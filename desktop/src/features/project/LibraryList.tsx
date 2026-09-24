/** 剧库列表档（卷二 P-E 密度档）：同一部剧压成一行——小封面 + 剧名/meta +
 * 四阶段灯 + 卡点句 + 继续 + 管理菜单。
 *
 * 与卡档、工作台矩阵共词汇（卷三意见 07）：StageMicro / BlockNoteLine /
 * CoverThumb / menuFor 全部复用原件，不造第三套说法；管理菜单（重命名/复制/
 * 删除）与卡档同一份，列表档不阉割功能。
 */
import { Button, Dropdown } from 'antd';
import type { CSSProperties, ReactElement } from 'react';
import type { Project } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { CoverThumb } from '../home/DramaMatrix';
import type { MatrixRow } from '../home/matrixRows';
import { whenLabel } from '../home/relativeTime';
import type { BlockNote } from '../stages/stageState';
import { BlockNoteLine, StageMicro } from '../stages/StageMicro';
import { menuFor, type MenuHandlers } from './dramaMenuItems';
import { MoreButton } from './MoreButton';

export interface LibraryListProps extends MenuHandlers {
  readonly rows: readonly MatrixRow[];
  /** 成品/任务账缺席：成品数与相对时间显示「—」，不拿 0 冒充。 */
  readonly factsMissing: boolean;
  readonly serverTimeMs: number | null;
  readonly onOpen: (project: Project) => void;
  readonly onGoto: (route: string, project: Project) => void;
}

export function LibraryList({
  rows,
  factsMissing,
  serverTimeMs,
  onOpen,
  onGoto,
  onRename,
  onDuplicate,
  onDelete,
}: LibraryListProps): ReactElement {
  const handlers: MenuHandlers = { onRename, onDuplicate, onDelete };
  return (
    <ul
      style={{
        listStyle: 'none',
        margin: 0,
        padding: 0,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceSm,
      }}
    >
      {rows.map((row) => (
        <ListRow
          key={row.project.id}
          row={row}
          factsMissing={factsMissing}
          serverTimeMs={serverTimeMs}
          onOpen={onOpen}
          onGoto={onGoto}
          handlers={handlers}
        />
      ))}
    </ul>
  );
}

interface ListRowProps {
  readonly row: MatrixRow;
  readonly factsMissing: boolean;
  readonly serverTimeMs: number | null;
  readonly onOpen: (project: Project) => void;
  readonly onGoto: (route: string, project: Project) => void;
  readonly handlers: MenuHandlers;
}

function ListRow({ row, factsMissing, serverTimeMs, onOpen, onGoto, handlers }: ListRowProps): ReactElement {
  const { project, note } = row;
  const style: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spaceMd,
    borderRadius: tokens.radiusCard,
    border: `1px solid ${tokens.borderSecondary}`,
    background: tokens.bgContainer,
    padding: `${tokens.spaceSm} ${tokens.spaceLg}`,
    cursor: 'pointer',
  };
  return (
    <li
      style={style}
      onClick={() => {
        onOpen(project);
      }}
    >
      <CoverThumb cover={project.cover_path} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, minWidth: 0, flex: 1 }}>
        <TitleLine row={row} factsMissing={factsMissing} serverTimeMs={serverTimeMs} />
        <StageMicro stages={row.stages} note={note} />
        {note !== null && <NoteSlot note={note} project={project} onGoto={onGoto} />}
      </div>
      <Button
        size="small"
        style={{ flexShrink: 0 }}
        onClick={(event) => {
          event.stopPropagation();
          onGoto(row.cont.route, project);
        }}
      >
        {row.cont.label}
      </Button>
      <span
        style={{ flexShrink: 0 }}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <Dropdown menu={{ items: menuFor(project, handlers) }} trigger={['click']}>
          <MoreButton />
        </Dropdown>
      </span>
    </li>
  );
}

function TitleLine({
  row,
  factsMissing,
  serverTimeMs,
}: {
  row: MatrixRow;
  factsMissing: boolean;
  serverTimeMs: number | null;
}): ReactElement {
  const { project } = row;
  // 账缺时相对时间没有服务端尺子可量：显示「—」，不掺本机时钟
  const time = serverTimeMs === null ? '—' : whenLabel(row.lastActivityMs, serverTimeMs);
  const works = factsMissing ? '—' : String(row.workCount);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, minWidth: 0 }}>
      <span
        style={{
          fontSize: tokens.text.body.size,
          lineHeight: tokens.text.body.leading,
          fontWeight: 600,
          color: tokens.textPrimary,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={project.name}
      >
        {project.name}
      </span>
      <span
        style={{
          marginLeft: 'auto',
          flexShrink: 0,
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tokens.textTertiary,
        }}
      >
        {`${String(project.episode_count)} 集 · ${works} 部成品 · ${time}`}
      </span>
    </div>
  );
}

/** 卡点行动作与整行点击分开走：拦 bubbling，动作按钮去自己的路由（卡档同款）。 */
function NoteSlot({
  note,
  project,
  onGoto,
}: {
  note: BlockNote;
  project: Project;
  onGoto: (route: string, project: Project) => void;
}): ReactElement {
  return (
    <span
      style={{ display: 'flex', minWidth: 0 }}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <BlockNoteLine
        note={note}
        onAction={(route) => {
          onGoto(route, project);
        }}
      />
    </span>
  );
}
