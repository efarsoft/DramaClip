/** 下载进度：生效卡与资产库行内同源，唯一真相是 store 里按 model_id 记的那一条。 */
import type { ModelInfo } from '@dramaclip/protocol';
import { type ModelDownloadState, useUiStore } from '../../stores/ui';

export function useDownloadProgress(model: ModelInfo | undefined): number | undefined {
  const download = useDownloadState(model);
  return download?.status === 'downloading' ? download.percent : undefined;
}

/** 整条下载状态（含速度/ETA/失败原因）：failed 态渲染与重试入口靠它（附录 B②）。 */
export function useDownloadState(model: ModelInfo | undefined): ModelDownloadState | undefined {
  return useUiStore((state) =>
    model === undefined ? undefined : state.modelDownloads[model.model_id],
  );
}
