import { App as AntdApp, Button, Card, Checkbox, Progress, Tag } from 'antd';
import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import type { Episode } from '@dramaclip/protocol';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { EpisodeResultPanel } from './EpisodeResultPanel';
import { useAnalysisWorkspace } from './useAnalysisWorkspace';

/** 智能分析页（docs/desktop/01 §6 W3 版）：选集 → 分析进度 → 结果看板。 */
export function AnalysisPage() {
  const { projectId = '' } = useParams();
  const { message } = AntdApp.useApp();
  const setCurrentProjectId = useUiStore((state) => state.setCurrentProjectId);
  const analysisProgress = useUiStore((state) => state.analysisProgress);
  const workspace = useAnalysisWorkspace(projectId);

  useEffect(() => {
    setCurrentProjectId(projectId === '' ? null : projectId);
    return () => {
      setCurrentProjectId(null);
    };
  }, [projectId, setCurrentProjectId]);

  const running = workspace.job?.status === 'running' || workspace.job?.status === 'pending';
  const percent =
    running && analysisProgress !== null && analysisProgress.jobId === workspace.job?.job_id
      ? analysisProgress.percent
      : (workspace.job?.progress ?? 0);
  const statusMessage = running ? (analysisProgress?.message ?? '准备中') : '';

  const onStart = async () => {
    try {
      await workspace.start();
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        projectName={workspace.project?.name ?? '…'}
        running={running}
        count={workspace.selectedIds.length}
        disabled={!workspace.canStart}
        onStart={() => void onStart()}
      />

      <Card size="small" title="剧集选择">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          {workspace.episodes.map((episode) => (
            <EpisodeChip
              key={episode.id}
              episode={episode}
              checked={workspace.selectedIds.includes(episode.id)}
              active={workspace.activeEpisodeId === episode.id}
              onToggle={(checked) => { workspace.toggleSelected(episode.id, checked); }}
              onSelect={() => { workspace.setActiveEpisodeId(episode.id); }}
            />
          ))}
        </div>
        {running && (
          <div style={{ marginTop: 16 }}>
            <Progress percent={Math.round(percent)} status="active" />
            <div style={{ fontSize: 12, color: tokens.textSecondary }}>{statusMessage}</div>
          </div>
        )}
      </Card>

      {workspace.activeEpisodeId !== null && (
        <EpisodeResultPanel episodeId={workspace.activeEpisodeId} results={workspace.results} />
      )}
    </div>
  );
}

function PageHeader({
  projectName,
  running,
  count,
  disabled,
  onStart,
}: {
  projectName: string;
  running: boolean;
  count: number;
  disabled: boolean;
  onStart: () => void;
}) {
  return (
    <header style={{ display: 'flex', alignItems: 'center' }}>
      <h1 style={{ margin: 0, fontSize: 20, color: tokens.textPrimary }}>{projectName} · 智能分析</h1>
      <Button type="primary" style={{ marginLeft: 'auto' }} disabled={disabled} onClick={onStart}>
        {running ? '分析中…' : `开始分析（${String(count)} 集）`}
      </Button>
    </header>
  );
}

const EPISODE_STATUS_COLORS: Record<string, string> = {
  pending: 'default',
  analyzing: 'processing',
  done: 'success',
  failed: 'error',
};

function EpisodeChip({
  episode,
  checked,
  active,
  onToggle,
  onSelect,
}: {
  episode: Episode;
  checked: boolean;
  active: boolean;
  onToggle: (checked: boolean) => void;
  onSelect: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 10px',
        borderRadius: 6,
        cursor: 'pointer',
        border: `1px solid ${active ? tokens.colorPrimary : tokens.border}`,
        background: active ? 'rgba(77,159,255,0.08)' : 'transparent',
      }}
    >
      <Checkbox
        checked={checked}
        onClick={(event) => {
          event.stopPropagation();
        }}
        onChange={(event) => {
          onToggle(event.target.checked);
        }}
      />
      <span style={{ fontSize: 13, color: tokens.textPrimary }}>
        第{String(episode.episode_number)}集
      </span>
      <Tag color={EPISODE_STATUS_COLORS[episode.status] ?? 'default'} style={{ marginRight: 0 }}>
        {episode.status}
      </Tag>
    </div>
  );
}
