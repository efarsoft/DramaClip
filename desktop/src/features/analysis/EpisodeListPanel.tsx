/** 左栏·剧集素材列表：封面+文件名+状态，支持拖拽手动排序与多选批量。 */
import type { RefObject } from 'react';
import { Button, Card, Checkbox } from 'antd';
import type { Episode, HighlightSegment } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
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
  return (
    <Card
      size="small"
      title={`剧集素材（${String(props.orderedIds.length)}）`}
      styles={{ body: { padding: '4px 0' } }}
    >
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
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, padding: '4px 12px 8px' }}>
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
