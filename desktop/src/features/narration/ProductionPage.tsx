/** 出片中心：③ 选模式出 K 条方案 → 勾选方案 → ④ 出片所选，成品入作品库。 */
import type { ReactElement } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert } from 'antd';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { ExportJob, ModeRecommendation, NarrationMode, Project } from '@dramaclip/protocol';
import { PageFooter, PageHeader as PageKitHeader, PageShell } from '../../components/layout/PageKit';
import { MODE_INFO } from '../../components/modeMeta';
import { exportApi, narrationApi, projectApi, settingsApi } from '../../services/client';
import { dramaEntryPath } from '../../app/routes';
import { rememberDrama } from '../../stores/lastDrama';
import { useUiStore } from '../../stores/ui';
import { layout, tokens } from '../../styles/theme';
import { ExportsCard } from './ExportsCard';
import { ModePicker } from './ModePicker';
import { PlanPickList } from './PlanPickList';
import { PlanQueue } from './PlanQueue';
import { avgCompletedBytes } from './produceView';
import { StyleSelectCard } from './StyleSelectCard';
import { useExportQueue } from './useExportQueue';
import { useFocusScroll } from './useFocusScroll';
import { usePlanBatch } from './usePlanBatch';

const ALL_MODES = MODE_INFO.map((item) => item.mode) as NarrationMode[];
/** K 的兜底值：设置读不到/读脏时用，与服务端 narration.variants_per_mode 默认值同口径。 */
const DEFAULT_K = 3;
/** K 下拉的合法区间（ModePicker K_OPTIONS 1–8）；设置值越界就不采用。 */
const K_MIN = 1;
const K_MAX = 8;

function toggleMode(setModes: React.Dispatch<React.SetStateAction<NarrationMode[]>>, mode: NarrationMode): void {
  setModes((prev) => (prev.includes(mode) ? prev.filter((m) => m !== mode) : [...prev, mode]));
}

/** K 默认初值读设置页同键 narration.variants_per_mode（键与消费端同源）；
 * 读不到、读脏或越界（K 下拉只有 1–8）就保持兜底值，不硬塞。 */
function useKDefault(serviceState: string, setK: (k: number) => void): void {
  useEffect(() => {
    if (serviceState !== 'ready') return;
    void settingsApi
      .get()
      .then((values) => {
        const parsed = Number.parseInt(values['narration.variants_per_mode'] ?? '', 10);
        if (Number.isFinite(parsed) && parsed >= K_MIN && parsed <= K_MAX) setK(parsed);
      })
      .catch(() => undefined);
  }, [serviceState, setK]);
}

/** 实话读数（外部审查 P0-C）：把「今天能出几条」提前算给用户，而不是等失败。
 * Y = 选中模式数 × K；素材集数不进读数（素材多少不构成产品分支，业主裁决）。
 * LLM 三态：null（读取失败）按已配置口径展示，不误导。 */
function CapacityReadout({
  llmConfigured,
  modeCount,
  k,
}: {
  llmConfigured: boolean | null;
  modeCount: number;
  k: number;
}): ReactElement | null {
  const FREE_MODE_COUNT = 2; // 纯原片剪辑 + 金句流（零文案模式，全链不触 LLM）
  if (llmConfigured === null) return null;
  const available = llmConfigured ? 9 : FREE_MODE_COUNT;
  const planned = modeCount * k;
  const llmPart =
    !llmConfigured
      ? `未配置文案 LLM · 可用 ${String(FREE_MODE_COUNT)} 种免文案模式 · `
      : `已配置文案 LLM · 可用 ${String(available)} 种模式 · `;
  if (planned === 0) {
    return (
      <Alert type="info" showIcon title={`${llmPart}勾选模式后开始出方案`} />
    );
  }
  return (
    <Alert
      type="info"
      showIcon
      title={`${llmPart}当前勾选 ${String(modeCount)} 种 × 每种 ${String(k)} 条 = 本次将出 ${String(planned)} 条方案`}
    />
  );
}

/** LLM 配置状态：true=已配置 / false=确认未配置 / null=读取失败（未知）。
 * 三态缺一不可：把「读取失败」当「未配置」会让用户去白配 LLM（外部审查实锤）。 */
function useLlmConfigured(serviceState: string): boolean | null {
  const [configured, setConfigured] = useState<boolean | null>(null);
  useEffect(() => {
    if (serviceState !== 'ready') return;
    void settingsApi
      .get()
      .then((values) => {
        setConfigured(Boolean((values['llm.base_url'] ?? '').trim()));
      })
      .catch(() => {
        setConfigured(null);
      });
  }, [serviceState]);
  return configured;
}

/** ③ 区段容器：与 PageShell 同一节奏的纵向排布，focus 滚动的锚。 */
function sectionStyle(): React.CSSProperties {
  return { display: 'flex', flexDirection: 'column', gap: layout.page.gap };
}

/** 页面装载：拉项目详情（名称/集数/源集封面）+ 登记当前项目与最近打开的剧。
 * 卸载时清当前项目，但 rememberDrama 不清——「最近剧库」是跨页面的。 */
function useProductionProject(projectId: string): {
  project: Project | null;
  episodeCount: number;
  episodeCovers: Record<string, { cover: string | null; number: number }>;
} {
  const setCurrentProjectId = useUiStore((state) => state.setCurrentProjectId);
  const [project, setProject] = useState<Project | null>(null);
  const [episodeCount, setEpisodeCount] = useState(0);
  const [episodeCovers, setEpisodeCovers] = useState<
    Record<string, { cover: string | null; number: number }>
  >({});
  useEffect(() => {
    setCurrentProjectId(projectId === '' ? null : projectId);
    void projectApi.get(projectId).then((detail) => {
      setProject(detail.project);
      setEpisodeCount(detail.episodes.length);
      setEpisodeCovers(
        Object.fromEntries(
          detail.episodes.map((episode) => [
            episode.id,
            { cover: episode.cover_path ?? null, number: episode.episode_number },
          ]),
        ),
      );
      rememberDrama(detail.project.id, detail.project.name);
    });
    return () => {
      setCurrentProjectId(null);
    };
  }, [projectId, setCurrentProjectId]);
  return { project, episodeCount, episodeCovers };
}

/** 规划和渲染是两步：先看清 K 条方案各说什么，再决定出哪几条。 */
export function ProductionPage() {
  const { projectId = '' } = useParams();
  const serviceState = useUiStore((state) => state.serviceState);
  const [modes, setModes] = useState<NarrationMode[]>([]);
  const [recommendation, setRecommendation] = useState<ModeRecommendation | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [k, setK] = useState<number>(DEFAULT_K);
  const [exports, setExports] = useState<ExportJob[] | null>(null);
  const { project, episodeCount, episodeCovers } = useProductionProject(projectId);
  const { planningRef, exportRef } = useFocusScroll();

  const reloadExports = useCallback(async () => {
    setExports(await exportApi.list(projectId));
  }, [projectId]);

  useEffect(() => {
    if (serviceState !== 'ready') return;
    void reloadExports();
  }, [reloadExports, serviceState]);

  // K 默认（09-10 §4.6「生产线默认值」）：初值读设置页同键，不写死 3
  useKDefault(serviceState, setK);
  const llmConfigured = useLlmConfigured(serviceState);
  // null（读取失败）按已配置处理：不显示「需配置」警示——误导性归因比不提示更坏

  // AI 模式推荐：服务端随项目缓存（命中秒回，未命中现算并落缓存）
  useEffect(() => {
    if (serviceState !== 'ready' || projectId === '') return;
    let cancelled = false;
    setRecLoading(true);
    narrationApi
      .recommendModes(projectId)
      .then((rec) => {
        if (!cancelled) setRecommendation(rec);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setRecLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, serviceState]);

  // 推荐到位且用户尚未手选 → 默认勾上推荐模式；手动改过就绝不覆盖
  useEffect(() => {
    if (recommendation === null) return;
    setModes((prev) => {
      if (prev.length > 0) return prev;
      const ids = recommendation.modes.map((item) => item.mode) as NarrationMode[];
      return ids;
    });
  }, [recommendation]);

  const onRerollRecommendation = useCallback(() => {
    setRecLoading(true);
    narrationApi
      .recommendModes(projectId, true)
      .then((rec) => {
        setRecommendation(rec);
        setModes(rec.modes.map((m) => m.mode) as NarrationMode[]); // 显式重算=用户授权覆盖
      })
      .catch(() => undefined)
      .finally(() => {
        setRecLoading(false);
      });
  }, [projectId]);

  const batch = usePlanBatch(projectId);

  const onGenerate = useCallback(
    (modes: NarrationMode[], k: number) => {
      void batch.run(modes, k); // 规格由 hook 记录（batch.spec），规划队列据此画骨架
    },
    [batch],
  );
  const queue = useExportQueue(reloadExports);
  // 磁盘预估系数：本剧已完成成片的实测均值（意见08「估」字要带得出出处）
  const avgBytes = useMemo(() => avgCompletedBytes(exports), [exports]);

  return (
    <PageShell>
      <PageHeader projectName={project?.name} />
      <div ref={planningRef} style={sectionStyle()}>
        <CapacityReadout llmConfigured={llmConfigured} modeCount={modes.length} k={k} />
        <StyleSelectCard />
        <ModePicker
          batch={batch}
          modes={modes}
          llmConfigured={llmConfigured}
          onGenerate={onGenerate}
          recommendation={recommendation}
          recLoading={recLoading}
          onReroll={onRerollRecommendation}
          k={k}
          onToggleMode={(mode) => {
            toggleMode(setModes, mode);
          }}
          onSelectAll={() => {
            setModes(ALL_MODES);
          }}
          onKChange={setK}
        />
        {batch.planning ? (
          <PlanQueue batch={batch} spec={batch.spec} />
        ) : (
          <PlanPickList
            batch={batch}
            queue={queue}
            episodeCount={episodeCount}
            avgBytes={avgBytes}
            episodeCovers={episodeCovers}
          />
        )}
      </div>
      <div ref={exportRef}>
        <ExportsCard exports={exports} onRefresh={() => void reloadExports()} />
      </div>
      <ProductionFooter projectId={projectId} exports={exports} />
    </PageShell>
  );
}

/** 向导底栏（W12 贯通）：上一步回分析页，下一步去作品库——分析页 footer 的下一站。 */
function ProductionFooter({
  projectId,
  exports,
}: {
  projectId: string;
  exports: ExportJob[] | null;
}): ReactElement {
  const navigate = useNavigate();
  const doneCount = (exports ?? []).filter((job) => job.status === 'completed').length;
  return (
    <PageFooter
      canProceed
      proceedHint={
        doneCount > 0
          ? `已完成 ${String(doneCount)} 条成片 · 到作品库查看与发布`
          : '出片完成后到作品库查看；也可以先回去调整分析或模式'
      }
      nextLabel="查看作品库"
      onPrev={() => {
        void navigate(dramaEntryPath(projectId));
      }}
      onNext={() => {
        void navigate('/works');
      }}
    />
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
