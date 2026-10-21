/** 本地智能运行环境：分组状态/安装/进度（E-2；ASR 与配音两页槽位共用）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { jobsApi, localRuntimeApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';

export interface OrtGpuState {
  readonly variant: string;
  readonly gpu: boolean;
  readonly providers: readonly string[];
  readonly version: string;
  readonly reason: string;
}

export interface LocalRuntimeState {
  /** 双栈 TTS 基线（indextts+torch）——旧口径，前端既有判据零改动。 */
  readonly installed: boolean | null;
  /** 按能力分组探针：indextts/funasr/kokoro/torch（升级补装按组判缺）。 */
  readonly groups: Record<string, boolean>;
  /** 人声分离的 ORT 后端（安装期探测）；旧服务端无此字段时为 null。 */
  readonly ortGpu: OrtGpuState | null;
  readonly jobId: string;
  readonly progress: number;
  readonly stage: string;
  readonly busy: boolean;
  readonly install: () => void;
}

export function useLocalRuntime(): LocalRuntimeState {
  const { message } = AntdApp.useApp();
  const serviceState = useUiStore((state) => state.serviceState);
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [groups, setGroups] = useState<Record<string, boolean>>({});
  const [ortGpu, setOrtGpu] = useState<OrtGpuState | null>(null);
  const [jobId, setJobId] = useState('');
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async (): Promise<void> => {
    const state = await localRuntimeApi.status();
    setInstalled(state.installed);
    setGroups(state.groups);
    setOrtGpu(state.ort_gpu ?? null);
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
          setStage(job.label ?? '');
          if (job.status === 'completed') {
            setJobId('');
            message.success('本地智能运行环境就绪');
            void refresh();
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
  }, [jobId, message, refresh]);

  const install = (): void => {
    setBusy(true);
    localRuntimeApi
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

  return { installed, groups, ortGpu, jobId, progress, stage, busy, install };
}
