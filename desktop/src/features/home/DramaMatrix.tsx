/** 我的剧矩阵（卷三图 1）：工作台主区第二块，吸收原三统计芯片/最近成品/继续上次。
 *
 * 一行一部剧：封面 + meta + 四阶段灯 + 卡点句 + 继续。聚合行即筛选器（意见 05）。
 * 「继续上次」不再是独立卡片：最近打开的剧置顶 + accentSoft 铺底 + 芯片点名。
 */
import { PlayCircleFilled } from '@ant-design/icons';
import { Button } from 'antd';
import { useMemo, useState, type CSSProperties, type ReactElement } from 'react';
import type { JobInfo, Project, WorkItem } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { mediaUrl } from '../../services/client';
import { readLastDrama } from '../../stores/lastDrama';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import type { BlockNote } from '../stages/stageState';
import { BlockNoteLine, StageMicro } from '../stages/StageMicro';
import {
  buildMatrixRows,
  countByFilter,
  FILTERS,
  matchesFilter,
  sortRows,
  type MatrixFilter,
  type MatrixRow,
} from './matrixRows';
import { whenLabel } from './relativeTime';

export interface DramaMatrixProps {
  readonly projects: readonly Project[];
  readonly works: readonly WorkItem[];
  readonly jobs: readonly JobInfo[];
  readonly serverTimeMs: number;
  /** 在跑芯片的悬停提示（stats.etaLabel 的量级外推）；'' 时不给 title。 */
  readonly etaLabel: string;
  readonly onNavigate: (route: string) => void;
}

export function DramaMatrix({ projects, works, jobs, serverTimeMs, etaLabel, onNavigate }: DramaMatrixProps): ReactElement {
  const [filter, setFilter] = useState<MatrixFilter>('all');
  const heroId = readLastDrama()?.id ?? null;
  const rows = useMemo(
    () => sortRows(buildMatrixRows(projects, works, jobs, serverTimeMs), heroId),
    [projects, works, jobs, serverTimeMs, heroId],
  );
  const shown = rows.filter((row) => matchesFilter(row, filter));

  return (
    <PageSection title="我的剧">
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, flexWrap: 'wrap' }}>
          {FILTERS.map((spec) => (
            <FilterChip
              key={spec.key}
              label={spec.label}
              count={countByFilter(rows, spec.key)}
              active={filter === spec.key}
              title={spec.key === 'running' ? etaLabel : ''}
              onClick={() => {
                setFilter(spec.key);
              }}
            />
          ))}
        </div>
        {shown.length === 0 ? (
          <div style={{ ...mixins.chip(), padding: tokens.spaceLg, textAlign: 'center', color: tokens.textTertiary }}>
            没有符合筛选的剧
          </div>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
            {shown.map((row) => (
              <MatrixRowView
                key={row.project.id}
                row={row}
                hero={row.project.id === heroId}
                serverTimeMs={serverTimeMs}
                onNavigate={onNavigate}
              />
            ))}
          </ul>
        )}
      </div>
    </PageSection>
  );
}

/** 聚合芯片即筛选器（卷三意见 05）：剧库工具条同款复用，词汇与计数口径一致。 */
export function FilterChip({
  label,
  count,
  active,
  title,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  title: string;
  onClick: () => void;
}): ReactElement {
  const style: CSSProperties = {
    ...mixins.chip(),
    display: 'inline-flex',
    alignItems: 'center',
    gap: tokens.spaceXs,
    border: 'none',
    cursor: 'pointer',
    fontFamily: 'inherit',
    background: active ? tokens.accentSoft : tokens.bgElevated,
    color: active ? tokens.colorPrimary : tokens.textSecondary,
  };
  return (
    <button type="button" style={style} title={title === '' ? undefined : title} onClick={onClick}>
      {label} {String(count)}
    </button>
  );
}

function MatrixRowView({
  row,
  hero,
  serverTimeMs,
  onNavigate,
}: {
  row: MatrixRow;
  hero: boolean;
  serverTimeMs: number;
  onNavigate: (route: string) => void;
}): ReactElement {
  const style: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spaceMd,
    borderRadius: tokens.radiusCard,
    border: `1px solid ${tokens.borderSecondary}`,
    background: hero ? tokens.accentSoft : tokens.bgContainer,
    padding: `${tokens.spaceMd} ${tokens.spaceLg}`,
    cursor: 'pointer',
  };
  return (
    <li
      style={style}
      onClick={() => {
        onNavigate(row.cont.route);
      }}
    >
      <CoverThumb cover={row.project.cover_path} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, minWidth: 0, flex: 1 }}>
        <RowTitle row={row} hero={hero} serverTimeMs={serverTimeMs} />
        <StageMicro stages={row.stages} note={row.note} />
        {row.note !== null && <NoteSlot note={row.note} onNavigate={onNavigate} />}
      </div>
      <Button
        size="small"
        style={{ flexShrink: 0 }}
        onClick={(event) => {
          event.stopPropagation();
          onNavigate(row.cont.route);
        }}
      >
        {row.cont.label}
      </Button>
    </li>
  );
}

function RowTitle({ row, hero, serverTimeMs }: { row: MatrixRow; hero: boolean; serverTimeMs: number }): ReactElement {
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
      >
        {row.project.name}
      </span>
      {hero && <span style={mixins.chip()}>继续上次</span>}
      <span
        style={{
          marginLeft: 'auto',
          flexShrink: 0,
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tokens.textTertiary,
        }}
      >
        {`${String(row.project.episode_count)} 集 · ${String(row.workCount)} 部成品 · ${whenLabel(row.lastActivityMs, serverTimeMs)}`}
      </span>
    </div>
  );
}

/** 卡点行动作与整行点击分开走：包一层拦 bubbling，动作按钮去自己的路由。 */
function NoteSlot({ note, onNavigate }: { note: BlockNote; onNavigate: (route: string) => void }): ReactElement {
  return (
    <span
      style={{ display: 'flex', minWidth: 0 }}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <BlockNoteLine note={note} onAction={onNavigate} />
    </span>
  );
}

function CoverThumb({ cover }: { cover: string | undefined }): ReactElement {
  return (
    <span
      style={{
        width: 45,
        height: 80,
        borderRadius: tokens.radiusThumb,
        overflow: 'hidden',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: tokens.accentSoft,
        color: tokens.colorPrimary,
      }}
    >
      {cover !== undefined ? (
        <img src={mediaUrl(cover)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
      ) : (
        <PlayCircleFilled style={{ fontSize: tokens.glyph.poster }} />
      )}
    </span>
  );
}
