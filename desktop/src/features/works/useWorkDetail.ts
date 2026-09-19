/** 成片详情数据：job/项目名/解说文案/候选标题 的加载与标题再生成（UI 解耦）。 */
import { useEffect, useState } from 'react';
import { App as AntdApp } from 'antd';
import type { ExportJob, TitleCandidate } from '@dramaclip/protocol';
import { exportApi, projectApi, rpc, titlesApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';

export function useWorkDetail(exportId: string): WorkDetail {
  const { message } = AntdApp.useApp();
  const serviceState = useUiStore((state) => state.serviceState);
  const [job, setJob] = useState<ExportJob | null>(null);
  const [failed, setFailed] = useState(false);
  const [projectName, setProjectName] = useState('…');
  const [titles, setTitles] = useState<TitleCandidate[]>([]);
  const [narrationTexts, setNarrationTexts] = useState<{ id: string; text: string }[]>([]);
  const [planId, setPlanId] = useState('');
  const [generating, setGenerating] = useState(false);

  // 服务就绪前 RPC 会失败；ready 后再加载
  useEffect(() => {
    if (exportId === '' || serviceState !== 'ready') return;
    void exportApi
      .get(exportId)
      .then((row) => {
        setJob(row);
        void projectApi
          .get(row.project_id)
          .then((detail) => {
            setProjectName(detail.project.name);
          })
          .catch(() => undefined);
        if (row.narration_plan_id) {
          setPlanId(row.narration_plan_id);
          void rpc<{ plan: { titles?: TitleCandidate[]; plan_data?: { narration_texts?: { id: string; text: string }[] } } }>(
            'narration.get_plan',
            { plan_id: row.narration_plan_id },
          )
            .then((detail) => {
              setTitles(detail.plan.titles ?? []);
              setNarrationTexts(detail.plan.plan_data?.narration_texts ?? []);
            })
            .catch(() => undefined);
        }
      })
      .catch(() => { setFailed(true); });
  }, [exportId, serviceState]);

  const onGenerate = (): void => {
    setGenerating(true);
    void titlesApi
      .generate(planId)
      .then((r) => { setTitles(r.titles); })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => { setGenerating(false); });
  };

  return {
    job,
    failed,
    projectName,
    titles,
    setTitles,
    narrationTexts,
    planId,
    generating,
    onGenerate,
  };
}

export interface WorkDetail {
  job: ExportJob | null;
  failed: boolean;
  projectName: string;
  titles: TitleCandidate[];
  setTitles: (titles: TitleCandidate[]) => void;
  narrationTexts: { id: string; text: string }[];
  planId: string;
  generating: boolean;
  onGenerate: () => void;
}
