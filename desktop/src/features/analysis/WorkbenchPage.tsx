/** 项目详情工作台：步骤导航 + 左素材列表 + 右复合面板（分割线可拖拽）。 */
import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { App as AntdApp } from 'antd';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { useAnalysisWorkspace } from './useAnalysisWorkspace';
import { useEpisodeOrder } from './useEpisodeOrder';
import { useEpisodeReorder, useProjectDetail } from './useProjectDetail';
import { useSplitDrag } from './useSplit';
import { WorkbenchHeader } from './WorkbenchHeader';
import { StepFooter } from './StepFooter';
import { EpisodeListPanel } from './EpisodeListPanel';
import { EpisodeDetail } from './EpisodeDetail';

/** 分析工作台页（路由 /projects/:id/analysis）。 */
export function WorkbenchPage() {
  const { projectId = '' } = useParams();
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const setCurrentProjectId = useUiStore((state) => state.setCurrentProjectId);
  const workspace = useAnalysisWorkspace(projectId);
  const { project, reloadProject } = useProjectDetail(projectId);
  const onReorder = useEpisodeReorder(projectId, reloadProject);

  useEffect(() => {
    setCurrentProjectId(projectId === '' ? null : projectId);
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
      <TwoColumns
        projectId={projectId}
        episodes={workspace.episodes}
        results={workspace.results}
        activeEpisodeId={workspace.activeEpisodeId}
        selectedIds={workspace.selectedIds}
        running={running}
        onActivate={workspace.setActiveEpisodeId}
        onToggle={workspace.toggleSelected}
        onReorder={onReorder}
        onReload={() => {
          void workspace.reload();
        }}
      />
      <StepFooter
        step={1}
        total={4}
        canProceed={doneCount > 0}
        proceedHint={
          doneCount === 0
            ? '完成至少一集分析后进入出片'
            : `已完成 ${String(doneCount)} 集 · 修正转写后进入出片`
        }
        nextLabel="生成解说文案"
        onPrev={() => {
          void navigate('/projects');
        }}
        onNext={() => {
          void navigate('../produce');
        }}
      />
    </div>
  );
}

interface TwoColumnsProps {
  projectId: string;
  episodes: ReturnType<typeof useAnalysisWorkspace>['episodes'];
  results: ReturnType<typeof useAnalysisWorkspace>['results'];
  activeEpisodeId: string | null;
  selectedIds: string[];
  running: boolean;
  onActivate: (id: string) => void;
  onToggle: (id: string, checked: boolean) => void;
  onReorder: (orderedIds: string[]) => void;
  onReload: () => void;
}

function TwoColumns(props: TwoColumnsProps): React.ReactElement {
  const { pct, containerRef, onHandleDown } = useSplitDrag(24);
  const order = useEpisodeOrder(props.episodes, props.onReorder);
  return (
    <div
      ref={containerRef}
      style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'stretch' }}
    >
      <div style={{ width: `${String(pct)}%`, minWidth: 250, overflowY: 'auto' }}>
        <EpisodeListPanel
          orderedIds={order.orderedIds}
          byId={order.byId}
          highlights={props.results?.highlights ?? {}}
          activeEpisodeId={props.activeEpisodeId}
          selectedIds={props.selectedIds}
          running={props.running}
          onActivate={props.onActivate}
          onToggle={props.onToggle}
          dragIndex={order.dragIndex}
          overIndex={order.overIndex}
          setOverIndex={order.setOverIndex}
          onDragStart={order.onDragStart}
          onDrop={order.drop}
          onMove={order.move}
        />
      </div>
      <div
        onPointerDown={onHandleDown}
        style={{ width: 6, cursor: 'col-resize', flexShrink: 0, background: tokens.borderSecondary }}
      />
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', paddingLeft: 14 }}>
        <EpisodeDetail
          projectId={props.projectId}
          episodes={props.episodes}
          activeEpisodeId={props.activeEpisodeId}
          results={props.results}
          onReload={props.onReload}
        />
      </div>
    </div>
  );
}
