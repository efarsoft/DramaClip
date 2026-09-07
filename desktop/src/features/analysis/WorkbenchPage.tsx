/** 项目详情工作台：步骤导航 + 左素材列表 + 右复合面板（分割线可拖拽）。 */
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { App as AntdApp } from 'antd';
import type { Project } from '@dramaclip/protocol';
import { projectApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { useAnalysisWorkspace } from './useAnalysisWorkspace';
import { useSplitDrag } from './useSplit';
import { WorkbenchHeader } from './WorkbenchHeader';
import { EpisodeListPanel } from './EpisodeListPanel';
import { EpisodeDetail } from './EpisodeDetail';

/** 分析工作台页（路由 /projects/:id/analysis）。 */
export function WorkbenchPage() {
  const { projectId = '' } = useParams();
  const { message } = AntdApp.useApp();
  const setCurrentProjectId = useUiStore((state) => state.setCurrentProjectId);
  const workspace = useAnalysisWorkspace(projectId);
  const [project, setProject] = useState<Project | null>(null);

  useEffect(() => {
    setCurrentProjectId(projectId === '' ? null : projectId);
    void projectApi
      .get(projectId)
      .then((detail) => {
        setProject(detail.project);
      })
      .catch(() => {
        setProject(null);
      });
    return () => {
      setCurrentProjectId(null);
    };
  }, [projectId, setCurrentProjectId]);

  const running = workspace.job?.status === 'running' || workspace.job?.status === 'pending';
  const doneCount = workspace.episodes.filter((episode) => episode.status === 'done').length;
  const onBatchAnalyze = (): void => {
    workspace.start().catch((error: unknown) => {
      message.error(error instanceof Error ? error.message : String(error));
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, height: '100%' }}>
      <WorkbenchHeader
        project={project}
        total={workspace.episodes.length}
        doneCount={doneCount}
        running={running}
        progressPercent={running && workspace.job !== null ? workspace.job.progress : 0}
        onBack={() => {
          window.history.back();
        }}
        onBatchAnalyze={onBatchAnalyze}
      />
      <WorkbenchBody projectId={projectId} workspace={workspace} running={running} />
    </div>
  );
}

interface WorkspaceLike {
  episodes: ReturnType<typeof useAnalysisWorkspace>['episodes'];
  results: ReturnType<typeof useAnalysisWorkspace>['results'];
  activeEpisodeId: string | null;
  selectedIds: string[];
  setActiveEpisodeId: (id: string) => void;
  toggleSelected: (id: string, checked: boolean) => void;
  reload: () => Promise<void>;
}

function WorkbenchBody({
  projectId,
  workspace,
  running,
}: {
  projectId: string;
  workspace: WorkspaceLike;
  running: boolean;
}): React.ReactElement {
  const { pct, containerRef, onHandleDown } = useSplitDrag(32);
  return (
    <div
      ref={containerRef}
      style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'stretch' }}
    >
      <div style={{ width: `${String(pct)}%`, minWidth: 240, overflowY: 'auto' }}>
        <EpisodeListPanel
          episodes={workspace.episodes}
          results={workspace.results}
          activeEpisodeId={workspace.activeEpisodeId}
          selectedIds={workspace.selectedIds}
          running={running}
          onActivate={workspace.setActiveEpisodeId}
          onToggle={workspace.toggleSelected}
        />
      </div>
      <div
        onPointerDown={onHandleDown}
        style={{ width: 6, cursor: 'col-resize', flexShrink: 0, background: tokens.borderSecondary }}
      />
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', paddingLeft: 14 }}>
        <EpisodeDetail
          projectId={projectId}
          episodes={workspace.episodes}
          activeEpisodeId={workspace.activeEpisodeId}
          results={workspace.results}
          onReload={() => {
            void workspace.reload();
          }}
        />
      </div>
    </div>
  );
}
