/** 视觉推理运行时（llama.cpp）：安装态/一键下载/进度（0.2.5 主题一 1.1；视觉页槽位共用）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { jobsApi, llamaRuntimeApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { errorText } from './errorText';

export interface LlamaRuntimeState {
  /** null = 探测中/探测失败（槽位据此显示「状态未知」而不是「未安装」）。 */
  readonly installed: boolean | null;
  /** 已装时的变体（cuda124/cpu）；未装/旧手动放置为空串。 */
  readonly variant: string;
  readonly jobId: string;
  readonly progress: number;
  readonly stage: string;
  readonly busy: boolean;
  readonly problem: string;
  readonly install: () => void;
  readonly retryProbe: () => void;
}

export function useLlamaRuntime(): LlamaRuntimeState {
  const { message } = AntdApp.useApp();
  const serviceState = useUiStore((state) => state.serviceState);
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [variant, setVariant] = useState('');
  const [jobId, setJobId] = useState('');
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  const refresh = useCallback(async (): Promise<void> => {
    const state = await llamaRuntimeApi.status();
    setInstalled(state.installed);
    setVariant(state.variant);
    setProblem('');
  }, []);

  useEffect(() => {
    if (serviceState === 'ready') {
      void refresh().catch((error: unknown) => {
        setInstalled(null);
        setProblem(errorText(error, '服务端未给出原因'));
      });
    }
  }, [refresh, serviceState]);

  useEffect(() => {
    if (jobId === '') return;
    const timer = setInterval(() => {
      jobsApi
        .get(jobId)
        .then(({ job }) => {
          setProgress(job.progress);
          setStage(job.label ?? '');
          if (job.status === 'completed') {
            setJobId('');
            message.success('llama.cpp 运行时就绪');
            void refresh();
          } else if (job.status === 'failed') {
            setJobId('');
            setProblem(`安装失败：${job.error ?? '服务端未给出原因'}`);
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => {
      clearInterval(timer);
    };
  }, [jobId, message, refresh]);

  const install = (): void => {
    setBusy(true);
    setProblem('');
    llamaRuntimeApi
      .install()
      .then(({ job_id }) => {
        setJobId(job_id);
      })
      .catch((error: unknown) => {
        setProblem(`启动安装失败：${errorText(error, '服务端未给出原因')}`);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const retryProbe = (): void => {
    void refresh().catch((error: unknown) => {
      setProblem(errorText(error, '服务端未给出原因'));
    });
  };

  return { installed, variant, jobId, progress, stage, busy, problem, install, retryProbe };
}
