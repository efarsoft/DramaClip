/** ASR 修正后仅重跑语义层（analysis.resync_semantic），轮询至结束。 */
import { useCallback, useState } from 'react';
import { analysisApi } from '../../services/client';

export function useResyncSemantic(
  projectId: string,
  episodeId: string,
  onDone: () => void,
): { running: boolean; run: () => Promise<void> } {
  const [running, setRunning] = useState(false);

  const run = useCallback(async (): Promise<void> => {
    setRunning(true);
    try {
      const { job_id } = await analysisApi.resyncSemantic(projectId, episodeId);
      for (;;) {
        const status = await analysisApi.status(job_id);
        if (status.status === 'completed') {
          onDone();
          return;
        }
        if (status.status === 'failed' || status.status === 'cancelled') return;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    } finally {
      setRunning(false);
    }
  }, [episodeId, onDone, projectId]);

  return { running, run };
}
