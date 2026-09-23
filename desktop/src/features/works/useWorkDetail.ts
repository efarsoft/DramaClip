/** 成片详情数据：job/项目名/解说文案/候选标题/追溯（角度·取材集）/自检 的加载与动作（UI 解耦）。 */
import { useCallback, useEffect, useState } from 'react';
import { App as AntdApp } from 'antd';
import type { Episode, ExportJob, TitleCandidate } from '@dramaclip/protocol';
import { exportApi, projectApi, rpc, titlesApi } from '../../services/client';
import { useJobsStore } from '../../stores/jobs';
import { useUiStore } from '../../stores/ui';

interface PlanSlice {
  titles?: TitleCandidate[];
  angle?: string;
  episode_ids?: string[];
  plan_data?: { narration_texts?: { id: string; text: string }[] };
}

interface LoadedDetail {
  job: ExportJob | null;
  failed: boolean;
  projectName: string;
  episodes: Episode[];
  titles: TitleCandidate[];
  setTitles: (titles: TitleCandidate[]) => void;
  narrationTexts: { id: string; text: string }[];
  angle: string | null;
  episodeIds: string[] | null;
  planId: string;
}

/** 加载侧：详情 job + 项目（含集数映射，供取材区间）+ 方案切片（角度/取材集/文案/标题）。 */
function useLoadedDetail(exportId: string, reloadTick: number): LoadedDetail {
  const serviceState = useUiStore((state) => state.serviceState);
  const [job, setJob] = useState<ExportJob | null>(null);
  const [failed, setFailed] = useState(false);
  const [projectName, setProjectName] = useState('…');
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [titles, setTitles] = useState<TitleCandidate[]>([]);
  const [narrationTexts, setNarrationTexts] = useState<{ id: string; text: string }[]>([]);
  const [angle, setAngle] = useState<string | null>(null);
  const [episodeIds, setEpisodeIds] = useState<string[] | null>(null);
  const [planId, setPlanId] = useState('');
  // 服务就绪前 RPC 会失败；ready 后再加载。「刷新」走 reloadTick 触发重拉。
  useEffect(() => {
    if (exportId === '' || serviceState !== 'ready') return;
    void exportApi
      .get(exportId)
      .then((row) => {
        setJob(row);
        setFailed(false);
        void projectApi
          .get(row.project_id)
          .then((detail) => {
            setProjectName(detail.project.name);
            setEpisodes(detail.episodes);
          })
          .catch(() => undefined);
        if (row.narration_plan_id) {
          setPlanId(row.narration_plan_id);
          void rpc<{ plan: PlanSlice }>('narration.get_plan', { plan_id: row.narration_plan_id })
            .then((detail) => {
              setTitles(detail.plan.titles ?? []);
              setNarrationTexts(detail.plan.plan_data?.narration_texts ?? []);
              setAngle(detail.plan.angle ?? null);
              setEpisodeIds(detail.plan.episode_ids ?? null);
            })
            .catch(() => undefined);
        }
      })
      .catch(() => {
        setFailed(true);
      });
  }, [exportId, serviceState, reloadTick]);
  return { job, failed, projectName, episodes, titles, setTitles, narrationTexts, angle, episodeIds, planId };
}

/** 动作侧：重生成标题 + 补测此片（排入自检作业并展开抽屉；结果落库后点「刷新」看成绩单）。 */
function useDetailActions(planId: string, setTitles: (titles: TitleCandidate[]) => void) {
  const { message } = AntdApp.useApp();
  const setDrawerOpen = useJobsStore((state) => state.setDrawerOpen);
  const [generating, setGenerating] = useState(false);
  const onGenerate = useCallback((): void => {
    setGenerating(true);
    void titlesApi
      .generate(planId)
      .then((r) => {
        setTitles(r.titles);
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        setGenerating(false);
      });
  }, [planId, setTitles, message]);
  const onSelfcheck = useCallback((exportId: string): void => {
    void exportApi
      .selfcheck([exportId])
      .then((result) => {
        if (result.queued === 0) {
          message.info('这条成片不满足补测条件（未完成或产物不在盘上）');
          return;
        }
        setDrawerOpen(true);
        message.success('已排入自检，跑完后点「刷新」查看结果');
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      });
  }, [message, setDrawerOpen]);
  return { generating, onGenerate, onSelfcheck };
}

export function useWorkDetail(exportId: string): WorkDetail {
  const [reloadTick, setReloadTick] = useState(0);
  const loaded = useLoadedDetail(exportId, reloadTick);
  const actions = useDetailActions(loaded.planId, loaded.setTitles);
  const reload = useCallback(() => {
    setReloadTick((tick) => tick + 1);
  }, []);
  return {
    ...loaded,
    generating: actions.generating,
    onGenerate: actions.onGenerate,
    onSelfcheck: () => {
      actions.onSelfcheck(exportId);
    },
    reload,
  };
}

export interface WorkDetail extends LoadedDetail {
  generating: boolean;
  onGenerate: () => void;
  onSelfcheck: () => void;
  reload: () => void;
}
