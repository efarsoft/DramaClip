/** 项目详情工作台：步骤导航 + 转写档位 + 左素材列表 + 右复合面板（分割线可拖拽）。 */
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, App as AntdApp } from 'antd';
import type { AnalysisResults } from '@dramaclip/protocol';
import { layout, tokens } from '../../styles/theme';
import { prescreenCoverage } from './analysisView';
import { useAnalysisWorkspace } from './useAnalysisWorkspace';
import { useEpisodeOrder } from './useEpisodeOrder';
import { useProjectDetail, useEpisodeReorder } from './useProjectDetail';
import { useSplitDrag } from './useSplit';
import { useTranscribeTier } from './useTranscribeTier';
import { WorkbenchHeader } from './WorkbenchHeader';
import { PageFooter } from '../../components/layout/PageKit';
import { EpisodeListPanel } from './EpisodeListPanel';
import { EpisodeDetail } from './EpisodeDetail';

/** 分析工作台页（路由 /projects/:id/analysis）。 */
export function WorkbenchPage() {
  const { projectId = '' } = useParams();
  const { message } = AntdApp.useApp();
  const workspace = useAnalysisWorkspace(projectId);
  const { project, reloadProject } = useProjectDetail(projectId);
  const onReorder = useEpisodeReorder(projectId, reloadProject);
  const onTierError = (text: string): void => {
    message.error(`转写档位没存上：${text}`);
  };
  const tierState = useTranscribeTier(projectId, project, onTierError);

  const running = workspace.job?.status === 'running' || workspace.job?.status === 'pending';
  const doneCount = workspace.episodes.filter((episode) => episode.status === 'done').length;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg, height: '100%' }}>
      <WorkbenchHeader
        projectId={projectId}
        project={project}
        total={workspace.episodes.length}
        doneCount={doneCount}
        running={running}
        progressPercent={running && workspace.job !== null ? workspace.job.progress : 0}
        tier={tierState.tier}
        onTierChange={tierState.setTier}
        onBatchAnalyze={() => {
          const action = tierState.tier === 'recommended' ? workspace.startPrescreen : workspace.start;
          startAnalysis(action, message);
        }}
        onCancel={() => {
          startAnalysis(workspace.cancel, message);
        }}
      />
      <CoverageAlert results={workspace.results} />
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
      <WorkbenchFooter projectId={projectId} doneCount={doneCount} />
    </div>
  );
}

/** 金色覆盖度告警（静默清单第 1 条·输入覆盖度）：预筛只放行一部分集时必须说出口，
 * 不说不等于没发生——其余集的台词根本没进模型视野。导出供单测直钉。 */
export function CoverageAlert({ results }: { results: AnalysisResults | null }): React.ReactElement | null {
  const coverage = prescreenCoverage(results);
  if (coverage === null || coverage.notRecommended === 0) return null;
  return (
    <Alert
      type="warning"
      showIcon
      title={`预筛只放行 ${String(coverage.recommended)}/${String(coverage.prescreened)} 集进入精转——其余 ${String(coverage.notRecommended)} 集的台词没有进入模型视野；改选「全部精转」重跑可补齐`}
    />
  );
}

function WorkbenchFooter({ projectId, doneCount }: { projectId: string; doneCount: number }): React.ReactElement {
  const navigate = useNavigate();
  return (
    <PageFooter
      step={1}
      total={4}
      canProceed={doneCount > 0}
      proceedHint={
        doneCount === 0
          ? '完成至少一集分析后进入出片'
          : `已完成 ${String(doneCount)} 集 · 到出片中心选择模式`
      }
      lockedHint="完成至少一集分析后解锁"
      nextLabel="选择出片模式"
      onPrev={() => {
        void navigate('/projects');
      }}
      onNext={() => {
        void navigate(`/projects/${projectId}/produce`);
      }}
    />
  );
}

function startAnalysis(
  start: () => Promise<void>,
  message: { error: (text: string) => void },
): void {
  start().catch((error: unknown) => {
    message.error(error instanceof Error ? error.message : String(error));
  });
}

interface TwoColumnsProps {
  projectId: string;
  episodes: ReturnType<typeof useAnalysisWorkspace>['episodes'];
  results: ReturnType<typeof useAnalysisWorkspace>['results'];
  activeEpisodeId: string | null;
  selectedIds: readonly string[];
  running: boolean;
  onActivate: (id: string) => void;
  onToggle: (id: string, checked: boolean) => void;
  onReorder: (orderedIds: string[]) => void;
  onReload: () => void;
}

function TwoColumns(props: TwoColumnsProps): React.ReactElement {
  const { pct, containerRef, onHandleDown } = useSplitDrag();
  const order = useEpisodeOrder(props.episodes, props.onReorder);
  return (
    <div
      ref={containerRef}
      style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'stretch' }}
    >
      <div style={{ width: `${String(pct)}%`, minWidth: layout.split.minWidth, overflowY: 'auto' }}>
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
        style={{ width: layout.split.handle, cursor: 'col-resize', flexShrink: 0, background: tokens.borderSecondary }}
      />
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', paddingLeft: layout.split.paddingX }}>
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
