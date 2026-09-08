/** 出片任务：发起后端组合任务并轮询进度（页面离开不影响后端执行）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useState } from 'react';
import type { AnalysisJobStatus, NarrationMode } from '@dramaclip/protocol';
import { analysisApi, narrationApi } from '../../services/client';

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

export function useProduceJob(
  projectId: string,
  onFinished: () => Promise<void>,
): {
  producing: boolean;
  percent: number;
  stageText: string;
  start: (modes: NarrationMode[]) => Promise<void>;
} {
  const { message } = AntdApp.useApp();
  const [producing, setProducing] = useState(false);
  const [percent, setPercent] = useState(0);
  const [stageText, setStageText] = useState('');

  const start = useCallback(
    async (modes: NarrationMode[]): Promise<void> => {
      if (modes.length === 0 || producing) return;
      setProducing(true);
      setPercent(0);
      setStageText('提交出片任务');
      try {
        const { job_id } = await narrationApi.produce(projectId, modes);
        for (;;) {
          const status: AnalysisJobStatus = await analysisApi.status(job_id);
          setPercent(status.progress);
          setStageText(status.message ?? '');
          if (status.status === 'completed') {
            message.success('出片完成，成品已入作品库');
            await onFinished();
            return;
          }
          if (status.status === 'failed') {
            message.error(status.error ?? '出片失败');
            return;
          }
          if (status.status === 'cancelled') return;
          await sleep(1500);
        }
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      } finally {
        setProducing(false);
        setStageText('');
      }
    },
    [message, onFinished, producing, projectId],
  );

  return { producing, percent, stageText, start };
}
