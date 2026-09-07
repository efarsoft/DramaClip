/** 左栏·剧集素材列表：文件名/时长/ASR 状态/高光数，支持单选查看与多选批量。 */
import { Button, Card, Checkbox } from 'antd';
import type { AnalysisResults, Episode } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { EpisodeListRow } from './EpisodeListRow';

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
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px 8px' }}>
      <Checkbox
        checked={allChecked}
        onChange={(event) => {
          onToggleAll(event.target.checked);
        }}
      >
        <span style={{ fontSize: 11.5, color: tokens.textTertiary }}>全选</span>
      </Checkbox>
      {running && (
        <Button size="small" type="primary" style={{ marginLeft: 'auto' }} loading>
          分析中
        </Button>
      )}
    </div>
  );
}

export function EpisodeListPanel({
  episodes,
  results,
  activeEpisodeId,
  selectedIds,
  running,
  onActivate,
  onToggle,
}: {
  episodes: Episode[];
  results: AnalysisResults | null;
  activeEpisodeId: string | null;
  selectedIds: string[];
  running: boolean;
  onActivate: (id: string) => void;
  onToggle: (id: string, checked: boolean) => void;
}): React.ReactElement {
  const allChecked = episodes.length > 0 && selectedIds.length === episodes.length;
  return (
    <Card
      size="small"
      title={`剧集素材（${String(episodes.length)}）`}
      styles={{ body: { padding: '4px 0' } }}
    >
      <ListHeader
        allChecked={allChecked}
        running={running}
        onToggleAll={(checked) => {
          episodes.forEach((episode) => {
            onToggle(episode.id, checked);
          });
        }}
      />
      {episodes.map((episode) => (
        <EpisodeListRow
          key={episode.id}
          episode={episode}
          highlightCount={results?.highlights?.[episode.id]?.length ?? 0}
          active={activeEpisodeId === episode.id}
          checked={selectedIds.includes(episode.id)}
          onActivate={() => {
            onActivate(episode.id);
          }}
          onToggle={(checked) => {
            onToggle(episode.id, checked);
          }}
        />
      ))}
      {episodes.length === 0 && (
        <div style={{ padding: 16, fontSize: 12.5, color: tokens.textTertiary }}>暂无剧集</div>
      )}
    </Card>
  );
}
