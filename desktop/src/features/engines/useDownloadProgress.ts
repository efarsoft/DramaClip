/** 下载进度：生效卡与资产库行内同源，唯一真相是 store 里按 model_id 记的那一条。 */
import type { ModelInfo } from '@dramaclip/protocol';
import { useUiStore } from '../../stores/ui';

export function useDownloadProgress(model: ModelInfo | undefined): number | undefined {
  const download = useUiStore((state) =>
    model === undefined ? undefined : state.modelDownloads[model.model_id],
  );
  return download?.status === 'downloading' ? download.percent : undefined;
}
