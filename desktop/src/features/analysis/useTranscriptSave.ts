/** 转写修正保存：单行编辑后整列表替换（update_asr）。 */
import { App as AntdApp } from 'antd';
import { useCallback } from 'react';
import type { AsrSegment } from '@dramaclip/protocol';
import { rpc } from '../../services/client';

export function useTranscriptSave(
  projectId: string,
  activeEpisodeId: string | null,
  transcript: readonly AsrSegment[],
  onReload: () => void,
): (index: number, text: string) => void {
  const { message } = AntdApp.useApp();

  return useCallback(
    (index: number, text: string): void => {
      if (activeEpisodeId === null) return;
      const next = transcript.flatMap((seg, i) =>
        i === index ? (text === '' ? [] : [{ ...seg, text }]) : [seg],
      );
      rpc('analysis.update_asr', {
        project_id: projectId,
        episode_id: activeEpisodeId,
        segments: next.map((segment) => ({
          start: segment.start,
          end: segment.end,
          text: segment.text,
          speaker: segment.speaker ?? null,
          emotion: segment.emotion ?? null,
        })),
      })
        .then(onReload)
        .catch((error: unknown) => {
          message.error(error instanceof Error ? error.message : String(error));
        });
    },
    [activeEpisodeId, message, onReload, projectId, transcript],
  );
}
