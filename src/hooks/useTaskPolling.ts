/**
 * 任务状态轮询 Hook
 */

import { useCallback, useEffect, useRef } from 'react';
import { taskPollingService } from '../services/taskPolling';
import type { ProgressPayload } from '../types/ipc';

interface UseTaskPollingOptions {
  taskId: string | null;
  taskType: 'analyze' | 'clip' | 'export';
  onProgress?: (payload: ProgressPayload) => void;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

export function useTaskPolling({
  taskId,
  taskType,
  onProgress,
  onComplete,
  onError,
}: UseTaskPollingOptions) {
  const taskIdRef = useRef(taskId);

  // 更新 ref
  useEffect(() => {
    taskIdRef.current = taskId;
  }, [taskId]);

  // 启动/停止轮询
  useEffect(() => {
    if (!taskId) {
      return;
    }

    const handleProgress = (payload: ProgressPayload) => {
      onProgress?.(payload);

      // 检查是否完成
      if (payload.progress >= 100) {
        onComplete?.();
      }
    };

    taskPollingService.startPolling(taskId, taskType, handleProgress);

    return () => {
      taskPollingService.stopPolling(taskId);
    };
  }, [taskId, taskType, onProgress, onComplete, onError]);

  const stopPolling = useCallback(() => {
    if (taskIdRef.current) {
      taskPollingService.stopPolling(taskIdRef.current);
    }
  }, []);

  return {
    stopPolling,
  };
}
