/** 剧卡五要素（卷三图 2）：封面 + 剧名 + 四阶段灯 + 卡点句 + meta 行。
 *
 * 与工作台矩阵行共用 stages 词汇（意见 07：共词汇不共组件）：卡片是竖排版，
 * 矩阵是横排版，数据与文案同源。操作菜单（重命名/复制/删除）沿用封面角位。
 */
import { PlayCircleFilled } from '@ant-design/icons';
import { Card, Dropdown } from 'antd';
import { memo, type ReactElement } from 'react';
import { useUiStore } from '../../stores/ui';
import type { Project } from '@dramaclip/protocol';
import { mediaUrl } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import type { MatrixRow } from '../home/matrixRows';
import type { BlockNote } from '../stages/stageState';
import { BlockNoteLine, StageMicro } from '../stages/StageMicro';
import { menuFor, type MenuHandlers } from './dramaMenuItems';
import { MoreButton } from './MoreButton';

export interface DramaCardProps extends MenuHandlers {
  readonly row: MatrixRow;
  /** 成品/任务账缺席：成品数显示「—」，不拿 0 冒充。 */
  readonly factsMissing: boolean;
  readonly onOpen: (project: Project) => void;
  readonly onGoto: (route: string, project: Project) => void;
}

/** 渲染层优化（UI 批③）：memo 防父组件状态变化时列表卡片级联重渲——
 * props 不变（同 row 同回调）时跳过整个卡片树的 reconciliation。 */
export const DramaCard = memo(function DramaCard({ row, factsMissing, onOpen, onGoto, onRename, onDuplicate, onDelete }: DramaCardProps): ReactElement {
  const { project } = row;
  const analysisPercent = useUiStore(
    (state) =>
      state.currentProjectId === project.id && state.analysisProgress !== null
        ? state.analysisProgress.percent
        : null,
  );
  const analysisLabel = useUiStore(
    (state) =>
      state.currentProjectId === project.id && state.analysisProgress !== null
        ? state.analysisProgress.message
        : '',
  );
  return (
    <Card
      hoverable
      styles={{ body: { padding: 0 } }}
      onClick={() => {
        onOpen(project);
      }}
    >
      <CoverArea project={project} handlers={{ onRename, onDuplicate, onDelete }} />
      <CardBody row={row} factsMissing={factsMissing} onGoto={onGoto} />
      {analysisPercent !== null && (
        <CardProgress percent={analysisPercent} label={analysisLabel} />
      )}
    </Card>
  );
});

/** 迷你进度条（🟡批②）：分析任务进行中，项目卡上内嵌当前进度与阶段文字——
 * 不用切到任务页就能看到「跑到哪了」。 */
function CardProgress({ percent, label }: { percent: number; label: string }): ReactElement {
  return (
    <div
      style={{
        padding: `${tokens.spaceXs} ${tokens.spaceSm}`,
        borderTop: `1px solid ${tokens.border}`,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
      }}
    >
      <div
        style={{
          flex: 1,
          height: 4,
          borderRadius: tokens.radiusDot,
          background: tokens.border,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${String(Math.min(percent, 100))}%`,
            height: '100%',
            borderRadius: tokens.radiusDot,
            background: tokens.colorPrimary,
            transition: 'width 0.3s ease',
          }}
        />
      </div>
      <span
        style={{
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tokens.textSecondary,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          maxWidth: 120,
        }}
      >
        {label !== '' ? label : `${String(Math.round(percent))}%`}
      </span>
    </div>
  );
}

function CardBody({
  row,
  factsMissing,
  onGoto,
}: {
  row: MatrixRow;
  factsMissing: boolean;
  onGoto: (route: string, project: Project) => void;
}): ReactElement {
  const { project, note } = row;
  return (
    <div
      style={{
        padding: `${tokens.spaceSm} ${tokens.spaceLg} ${tokens.spaceMd}`,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceXs,
      }}
    >
      <div
        style={{
          fontSize: tokens.text.body.size,
          lineHeight: tokens.text.body.leading,
          fontWeight: 600,
          color: tokens.textPrimary,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
        title={project.name}
      >
        {project.name}
      </div>
      <StageMicro stages={row.stages} note={note} />
      <div
        style={{
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: tokens.textTertiary,
        }}
        title={project.source_path}
      >
        {`${String(project.episode_count)} 集 · ${factsMissing ? '—' : String(row.workCount)} 部成品`}
      </div>
      {note !== null && <NoteSlot note={note} project={project} onGoto={onGoto} />}
    </div>
  );
}

/** 卡点行动作与整卡点击分开走：拦 bubbling，动作按钮去自己的路由。 */
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

function CoverArea({ project, handlers }: { project: Project; handlers: MenuHandlers }): ReactElement {
  return (
    <div className="project-cover" style={{ position: 'relative' }}>
      {/* 真值判断挡掉 null/''（库内 NULL 原样过线）：缺封面走占位，不请求 mediaUrl(null) */}
      {project.cover_path ? (
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
      <span style={{ ...mixins.chip(), position: 'absolute', left: 10, bottom: 10, background: tokens.posterPlate, color: tokens.colorWhite }}>
        {String(project.episode_count)} 集
      </span>
    </div>
  );
}
