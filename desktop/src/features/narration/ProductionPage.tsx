/** 出片中心：③ 选模式出 K 条方案 → 勾选方案 → ④ 出片所选，成品入作品库。 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { ExportJob, NarrationMode, Project } from '@dramaclip/protocol';
import { PageHeader as PageKitHeader, PageShell } from '../../components/layout/PageKit';
import { MODE_INFO } from '../../components/modeMeta';
import { exportApi, projectApi } from '../../services/client';
import { rememberDrama } from '../../stores/lastDrama';
import { useUiStore } from '../../stores/ui';
import { layout, tokens } from '../../styles/theme';
import { ExportsCard } from './ExportsCard';
import { ModePicker } from './ModePicker';
import { PlanPickList } from './PlanPickList';
import { avgCompletedBytes } from './produceView';
import { StyleSelectCard } from './StyleSelectCard';
import { useExportQueue } from './useExportQueue';
import { useFocusScroll } from './useFocusScroll';
import { usePlanBatch } from './usePlanBatch';

const ALL_MODES = MODE_INFO.map((item) => item.mode) as NarrationMode[];
/** 与 ModePicker 的下拉、服务端 narration.variants_per_mode 默认值同口径。 */
const DEFAULT_K = 3;

function toggleMode(setModes: React.Dispatch<React.SetStateAction<NarrationMode[]>>, mode: NarrationMode): void {
  setModes((prev) => (prev.includes(mode) ? prev.filter((m) => m !== mode) : [...prev, mode]));
}

/** ③ 区段容器：与 PageShell 同一节奏的纵向排布，focus 滚动的锚。 */
function sectionStyle(): React.CSSProperties {
  return { display: 'flex', flexDirection: 'column', gap: layout.page.gap };
}

/** 规划和渲染是两步：先看清 K 条方案各说什么，再决定出哪几条。 */
export function ProductionPage() {
  const { projectId = '' } = useParams();
  const setCurrentProjectId = useUiStore((state) => state.setCurrentProjectId);
  const serviceState = useUiStore((state) => state.serviceState);
  const [project, setProject] = useState<Project | null>(null);
  const [episodeCount, setEpisodeCount] = useState(0);
  const [modes, setModes] = useState<NarrationMode[]>([]);
  const [k, setK] = useState<number>(DEFAULT_K);
  const [exports, setExports] = useState<ExportJob[] | null>(null);
  const { planningRef, exportRef } = useFocusScroll();

  useEffect(() => {
    setCurrentProjectId(projectId === '' ? null : projectId);
    void projectApi.get(projectId).then((detail) => {
      setProject(detail.project);
      setEpisodeCount(detail.episodes.length);
      rememberDrama(detail.project.id, detail.project.name);
    });
    return () => {
      setCurrentProjectId(null);
    };
  }, [projectId, setCurrentProjectId]);

  const reloadExports = useCallback(async () => {
    setExports(await exportApi.list(projectId));
  }, [projectId]);

  useEffect(() => {
    if (serviceState !== 'ready') return;
    void reloadExports();
  }, [reloadExports, serviceState]);

  const batch = usePlanBatch(projectId);
  const queue = useExportQueue(reloadExports);
  // 磁盘预估系数：本剧已完成成片的实测均值（意见08「估」字要带得出出处）
  const avgBytes = useMemo(() => avgCompletedBytes(exports), [exports]);

  return (
    <PageShell>
      <PageHeader projectName={project?.name} />
      <div ref={planningRef} style={sectionStyle()}>
        <StyleSelectCard />
        <ModePicker
          batch={batch}
          modes={modes}
          k={k}
          onToggleMode={(mode) => {
            toggleMode(setModes, mode);
          }}
          onSelectAll={() => {
            setModes(ALL_MODES);
          }}
          onKChange={setK}
        />
        <PlanPickList batch={batch} queue={queue} episodeCount={episodeCount} avgBytes={avgBytes} />
      </div>
      <div ref={exportRef}>
        <ExportsCard exports={exports} />
      </div>
    </PageShell>
  );
}

function PageHeader({ projectName }: { projectName?: string }): React.ReactElement {
  return (
    <PageKitHeader
      title={`${projectName ?? '…'} · 出片中心`}
      desc="先出方案再出片：AI 编排的角度、文案、配音在这一步看得见"
      actions={
        <Link to="/works" style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.colorPrimary }}>
          前往作品库 →
        </Link>
      }
    />
  );
}
