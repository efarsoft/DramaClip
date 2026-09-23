/** 左栏·剧集素材列表：封面+文件名+状态，支持拖拽手动排序与多选批量；缺音轨告警行常驻（09-10 §2.3①）。 */
import type { RefObject } from 'react';
import { useState } from 'react';
import { Button, Card, Checkbox } from 'antd';
import type { Episode, HighlightSegment } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { missingAudioEpisodes } from './analysisView';
import { EpisodeListRow } from './EpisodeListRow';

interface ListProps {
  orderedIds: string[];
  byId: Map<string, Episode>;
  highlights: Partial<Record<string, HighlightSegment[]>>;
  activeEpisodeId: string | null;
  selectedIds: string[];
  running: boolean;
  onActivate: (id: string) => void;
  onToggle: (id: string, checked: boolean) => void;
  dragIndex: RefObject<number | null>;
  overIndex: number | null;
  setOverIndex: (index: number | null) => void;
  onDragStart: (index: number) => void;
  onDrop: (index: number) => void;
  onMove: (index: number, direction: -1 | 1) => void;
}

/** 剧集素材列表（按手动/智能顺序渲染）。 */
export function EpisodeListPanel(props: ListProps): React.ReactElement {
  const highlightCount = (id: string): number => props.highlights[id]?.length ?? 0;
  const missing = missingAudioEpisodes(orderedEpisodes(props.orderedIds, props.byId));
  return (
    <Card
      size="small"
      title={`剧集素材（${String(props.orderedIds.length)}）`}
      styles={{ body: { padding: `${tokens.spaceXs} 0` } }}
    >
      <NoAudioAlert missing={missing} />
      <ListHeader
        allChecked={
          props.orderedIds.length > 0 && props.selectedIds.length === props.orderedIds.length
        }
        running={props.running}
        onToggleAll={(checked) => {
          props.orderedIds.forEach((id) => {
            props.onToggle(id, checked);
          });
        }}
      />
      {props.orderedIds.map((id, index) => {
        const episode = props.byId.get(id);
        if (episode === undefined) return null;
        return (
          <EpisodeListRow
            key={id}
            episode={episode}
            highlightCount={highlightCount(id)}
            active={props.activeEpisodeId === id}
            checked={props.selectedIds.includes(id)}
            dropTarget={props.overIndex === index && props.dragIndex.current !== null}
            onActivate={() => {
              props.onActivate(id);
            }}
            onToggle={(checked) => {
              props.onToggle(id, checked);
            }}
            onDragStart={() => {
              props.onDragStart(index);
            }}
            onDragOver={() => {
              props.setOverIndex(index);
            }}
            onDrop={() => {
              props.onDrop(index);
            }}
            onMove={(direction) => {
              props.onMove(index, direction);
            }}
          />
        );
      })}
      {props.orderedIds.length === 0 && (
        <div style={{ padding: tokens.spaceLg, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>暂无剧集</div>
      )}
    </Card>
  );
}

/** 按当前顺序取回集对象（缺 id 的槽位跳过——列表与数据短暂不同步时不炸）。 */
function orderedEpisodes(orderedIds: readonly string[], byId: Map<string, Episode>): Episode[] {
  return orderedIds.flatMap((id) => {
    const episode = byId.get(id);
    return episode === undefined ? [] : [episode];
  });
}

/** 缺音频轨告警行：这些集转写必失败——先说出口，不让它们在分析里静默变红。 */
function NoAudioAlert({ missing }: { missing: readonly Episode[] }): React.ReactElement | null {
  const [expanded, setExpanded] = useState(false);
  if (missing.length === 0) return null;
  return (
    <div
      style={{
        margin: `0 ${tokens.spaceMd} ${tokens.spaceSm}`,
        padding: tokens.spaceSm,
        background: tokens.warningSoft,
        borderRadius: tokens.radiusThumb,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceXs,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.colorWarning }}>
          ⚠ {String(missing.length)} 集缺音频轨，无法转写
        </span>
        <button
          type="button"
          style={{
            marginLeft: 'auto',
            background: 'none',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
            fontSize: tokens.text.meta.size,
            lineHeight: tokens.text.meta.leading,
            color: tokens.colorPrimary,
          }}
          onClick={() => {
            setExpanded((prev) => !prev);
          }}
        >
          {expanded ? '收起清单' : '查看清单'}
        </button>
      </div>
      {expanded &&
        missing.map((episode) => (
          <span
            key={episode.id}
            style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}
          >
            第{String(episode.episode_number)}集 · {episode.name === '' ? '（未命名）' : episode.name}
          </span>
        ))}
    </div>
  );
}

function ListHeader({
  allChecked,
  running,
  onToggleAll,
}: {
  allChecked: boolean;
  running: boolean;
  onToggleAll: (checked: boolean) => void;
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, padding: `${tokens.spaceXs} ${tokens.spaceMd} ${tokens.spaceSm}` }}>
      <Checkbox
        checked={allChecked}
        onChange={(event) => {
          onToggleAll(event.target.checked);
        }}
      >
        <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>全选</span>
      </Checkbox>
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>拖拽行可调顺序</span>
      {running && (
        <Button size="small" type="primary" style={{ marginLeft: 'auto' }} loading>
          分析中
        </Button>
      )}
    </div>
  );
}
