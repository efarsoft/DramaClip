/** 本地智能运行环境：分组状态/安装/进度（E-2；ASR 与配音两页槽位共用）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { jobsApi, localRuntimeApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { errorText } from './errorText';

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
  /** 探测取不到的原话（规格 H3 §3.2.1）：空串 = 探到了或还在探。取不到≠未安装，两句话不是一回事。 */
  readonly probeProblem: string;
  /** 上一次安装失败的原话（规格 H3 §3.1.3）：常驻槽位，不交给会自己消失的 toast。 */
  readonly installProblem: string;
  readonly install: () => void;
  readonly retryProbe: () => void;
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
  const [probeProblem, setProbeProblem] = useState('');
  const [installProblem, setInstallProblem] = useState('');

  const refresh = useCallback(async (): Promise<void> => {
    const state = await localRuntimeApi.status();
    setInstalled(state.installed);
    setGroups(state.groups);
    setOrtGpu(state.ort_gpu ?? null);
    setProbeProblem('');
  }, []);

  useEffect(() => {
    if (serviceState === 'ready') {
      // 原先 catch 里写 setInstalled(false)：把「取不到」说成「未安装」，槽位于是催用户
      // 重下一趟 2~6GB 的栈。未知就报未知，并给一次重探（规格 H3 §3.2.1）。
      void refresh().catch((error: unknown) => {
        setInstalled(null);
        setProbeProblem(errorText(error, '服务端未给出原因'));
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
            setInstallProblem('');
            message.success('本地智能运行环境就绪');
            void refresh();
          } else if (job.status === 'failed') {
            setJobId('');
            setInstallProblem(`安装失败：${job.error ?? '服务端未给出原因'}`);
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
    setInstallProblem('');
    localRuntimeApi
      .install()
      .then(({ job_id }) => {
        setJobId(job_id);
      })
      .catch((error: unknown) => {
        setInstallProblem(`启动安装失败：${errorText(error, '服务端未给出原因')}`);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const retryProbe = (): void => {
    void refresh().catch((error: unknown) => {
      setProbeProblem(errorText(error, '服务端未给出原因'));
    });
  };

  return {
    installed,
    groups,
    ortGpu,
    jobId,
    progress,
    stage,
    busy,
    probeProblem,
    installProblem,
    install,
    retryProbe,
  };
}
