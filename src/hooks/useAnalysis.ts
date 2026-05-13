/**
 * 分析流程 Hook
 */

import { useCallback, useEffect, useState } from 'react';
import { analyzeApi } from '../services/ipc';
import { taskPollingService } from '../services/taskPolling';
import type { ProgressPayload } from '../types/ipc';

export function useAnalysis() {
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startAnalysis = useCallback(
    async (projectId: string, episodeIds: string[]) => {
      setError(null);
      setIsAnalyzing(true);

      try {
        const { task_id } = await analyzeApi.start(projectId, episodeIds);

        setCurrentTaskId(task_id);

        // 启动轮询
        taskPollingService.startPolling(
          task_id,
          'analyze',
          (payload: ProgressPayload) => {
            console.log('[useAnalysis] Progress:', payload);
          }
        );

        return task_id;
      } catch (err) {
        const message = err instanceof Error ? err.message : '未知错误';
        setError(message);
        setIsAnalyzing(false);
        throw err;
      }
    },
    []
  );

  const cancelAnalysis = useCallback(async () => {
    if (currentTaskId) {
      try {
        await analyzeApi.cancel(currentTaskId);
        taskPollingService.stopPolling(currentTaskId);
        setCurrentTaskId(null);
        setIsAnalyzing(false);
      } catch (err) {
        console.error('[useAnalysis] Cancel failed:', err);
      }
    }
  }, [currentTaskId]);

  // 清理
  useEffect(() => {
    return () => {
      if (currentTaskId) {
        taskPollingService.stopPolling(currentTaskId);
      }
    };
  }, [currentTaskId]);

  return {
    isAnalyzing,
    currentTaskId,
    error,
    startAnalysis,
    cancelAnalysis,
  };
}
