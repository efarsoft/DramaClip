/** 一键引导的串装链（业主拍板推荐档=Paraformer-large，2026-11-16）：
 * 本地运行环境（funasr worker 依赖）→ 三包逐下（串行闸决定不能并行）→ 完成回调。
 * 快速档（Whisper Small）免环境，同一 hook 的单包捷径。
 *
 * 自愈重入：每一步动手前都先查现状——环境 groups 齐即跳安装、包已 installed 即跳
 * 下载，所以失败后点重试天然从断点续走，不重下已装好的东西。
 * 进度分两源：环境阶段读 job（models.download_progress 不覆盖运行时 job），
 * 包下载阶段由渲染层读全局 ui store 的 modelDownloads。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { jobsApi, localRuntimeApi, modelsApi } from '../../services/client';
import { requestCancel } from '../engines/downloadCancel';
import { errorText } from '../engines/errorText';
import { RECOMMENDED_CHAIN } from './onboardingModel';

export type ChainPhase =
  | { readonly kind: 'idle' }
  | { readonly kind: 'runtime'; readonly progress: number; readonly stage: string }
  | { readonly kind: 'download'; readonly modelId: string; readonly modelName: string; readonly index: number; readonly total: number }
  | { readonly kind: 'done' }
  | { readonly kind: 'error'; readonly problem: string };

const POLL_MS = 3_000;
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

export interface OnboardingChain {
  readonly phase: ChainPhase;
  /** 推荐档串装（环境→三包）；链已在跑时调用无效。 */
  readonly startRecommended: () => void;
  /** 快速档单包（免环境）；链已在跑时调用无效。 */
  readonly startQuick: (modelId: string, modelName: string) => void;
  readonly cancel: () => void;
}

export function useOnboardingChain(onChanged: () => void): OnboardingChain {
  const [phase, setPhase] = useState<ChainPhase>({ kind: 'idle' });
  const cancelRequested = useRef(false);
  const runtimeJobId = useRef('');
  const activeModelId = useRef('');
  const unmounted = useRef(false);

  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
    };
  }, []);

  const settle = useCallback((next: ChainPhase): void => {
    if (!unmounted.current) setPhase(next);
  }, []);

  // 判停一律走函数：直接读 .current 会在 runChain 开头赋值 false 后被 TS 属性流
  // 窄化成字面量，后续判停被当「恒 falsy」误报（no-unnecessary-condition 实锤）
  const isCancelled = useCallback((): boolean => cancelRequested.current || unmounted.current, []);

  const cancel = useCallback((): void => {
    cancelRequested.current = true;
    // 两类在途任务都兜住：环境安装 job 与当前包下载 job（查不到=已终态，无妨）
    if (runtimeJobId.current !== '') void jobsApi.cancel(runtimeJobId.current).catch(() => undefined);
    if (activeModelId.current !== '') {
      void requestCancel(activeModelId.current).catch(() => undefined);
    }
  }, []);

  /** 等一个 model_download 作业走出在跑集，然后按 models.list 裁定成败。 */
  const waitForModel = useCallback(
    async (model: { model_id: string; name: string }): Promise<boolean> => {
      for (;;) {
        if (cancelRequested.current || unmounted.current) return false;
        await sleep(POLL_MS);
        const { jobs } = await jobsApi.list(200, true);
        const stillRunning = jobs.some((j) => j.type === 'model_download' && j.ref_id === model.model_id);
        if (stillRunning) continue;
        const list = await modelsApi.list();
        const row = list.find((m) => m.model_id === model.model_id);
        if (row?.status === 'installed') return true;
        throw new Error(`${model.name}：下载未完成（服务端已无在跑任务但模型未就位）`);
      }
    },
    [],
  );

  const runChain = useCallback(
    async (quick?: { modelId: string; modelName: string }): Promise<void> => {
      cancelRequested.current = false;
      try {
        // ① 本地运行环境：快速档跳过；推荐档 groups 缺（torch/funasr 任一）才装。
        //    「已就绪」的竞态拒绝也当跳过——判据在服务端，比前端猜的准。
        if (quick === undefined) {
          const status = await localRuntimeApi.status();
          const ready = Boolean(status.groups.torch) && Boolean(status.groups.funasr);
          if (!ready) {
            settle({ kind: 'runtime', progress: 0, stage: '准备安装本地运行环境' });
            const { job_id } = await localRuntimeApi.install();
            runtimeJobId.current = job_id;
            for (;;) {
              if (isCancelled()) {
                runtimeJobId.current = '';
                settle({ kind: 'idle' }); // 取消收尾：回 idle，别把界面留在进行态
                return;
              }
              await sleep(POLL_MS);
              const { job } = await jobsApi.get(job_id);
              if (job.status === 'completed') break;
              if (job.status === 'failed') {
                throw new Error(`本地运行环境安装失败：${job.error ?? '服务端未给出原因'}`);
              }
              settle({ kind: 'runtime', progress: job.progress, stage: job.label ?? '' });
            }
            runtimeJobId.current = '';
          }
        }
        // ② 逐包下载（串行闸：服务端一次只放一个 model_download）
        const queue: readonly { modelId: string; modelName: string }[] =
          quick !== undefined
            ? [{ modelId: quick.modelId, modelName: quick.modelName }]
            : RECOMMENDED_CHAIN.map((modelId) => ({ modelId, modelName: '' }));
        for (let index = 0; index < queue.length; index += 1) {
          const item = queue[index];
          if (item === undefined) continue;
          if (isCancelled()) return;
          activeModelId.current = item.modelId;
          const list = await modelsApi.list();
          const row = list.find((m) => m.model_id === item.modelId);
          if (row?.status === 'installed') continue; // 断点自愈：已装跳过
          const name = item.modelName !== '' ? item.modelName : (row?.name ?? item.modelId);
          settle({ kind: 'download', modelId: item.modelId, modelName: name, index: index + 1, total: queue.length });
          try {
            await modelsApi.download(item.modelId);
          } catch (error: unknown) {
            const text = errorText(error, '下载任务创建失败');
            if (!text.includes('已安装')) throw new Error(text, { cause: error }); // 竞态已装=跳过
          }
          const ok = await waitForModel({ model_id: item.modelId, name });
          if (!ok) {
            activeModelId.current = '';
            settle({ kind: 'idle' }); // 取消收尾：回 idle，别把界面留在进行态
            return;
          }
          activeModelId.current = '';
        }
        activeModelId.current = '';
        settle({ kind: 'done' });
        onChanged();
      } catch (error: unknown) {
        if (isCancelled()) return;
        settle({ kind: 'error', problem: errorText(error, '一键装齐失败：服务端未给出原因') });
      }
    },
    [isCancelled, settle, onChanged],
  );

  const startRecommended = useCallback((): void => {
    if (cancelRequested.current) return; // 上一轮取消收尾中，按钮本就该 disabled
    void runChain();
  }, [runChain]);

  const startQuick = useCallback(
    (modelId: string, modelName: string): void => {
      if (cancelRequested.current) return;
      void runChain({ modelId, modelName });
    },
    [runChain],
  );

  return { phase, startRecommended, startQuick, cancel };
}
