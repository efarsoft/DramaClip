/** 下载结束（完成/失败）时提示并刷新列表（进度事件只到达一次，故按 model_id 记一次）。 */
import { useEffect, useRef } from 'react';
import { App as AntdApp } from 'antd';
import { useUiStore } from '../../stores/ui';

export function useDownloadSettled(onChanged: () => void): void {
  const { message } = AntdApp.useApp();
  const downloads = useUiStore((state) => state.modelDownloads);
  const seen = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const [modelId, state] of Object.entries(downloads)) {
      if (state.status === 'downloading' || seen.current.has(modelId)) continue;
      seen.current.add(modelId);
      if (state.status === 'done') {
        message.success('模型下载完成');
      } else {
        message.error('模型下载失败，可在该行重试下载');
      }
      onChanged();
    }
  }, [downloads, message, onChanged]);
}
