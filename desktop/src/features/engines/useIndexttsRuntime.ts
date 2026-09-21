/** IndexTTS 运行环境状态/安装/进度（UI 解耦）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { RuntimeState } from './runtimeState';
import { indexttsApi, jobsApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';

export function useIndexttsRuntime(): RuntimeState {
  const { message } = AntdApp.useApp();
  const serviceState = useUiStore((state) => state.serviceState);
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [jobId, setJobId] = useState('');
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async (): Promise<void> => {
    setInstalled((await indexttsApi.status()).installed);
  }, []);

  useEffect(() => {
    if (serviceState === 'ready') {
      refresh().catch(() => {
        setInstalled(false);
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
          setStage(job.stage ?? '');
          if (job.status === 'completed') {
            setJobId('');
            setInstalled(true);
            message.success('IndexTTS 运行环境就绪');
          } else if (job.status === 'failed') {
            setJobId('');
            message.error(`安装失败：${job.error ?? '未知原因'}`);
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => {
      clearInterval(timer);
    };
  }, [jobId, message]);

  const install = (): void => {
    setBusy(true);
    indexttsApi
      .install()
      .then(({ job_id }) => {
        setJobId(job_id);
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return { installed, jobId, progress, stage, busy, install };
}
