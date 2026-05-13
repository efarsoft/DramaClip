/**
 * 导出进度 Hook
 */

import { useCallback, useEffect, useState } from 'react';
import { exportApi } from '../services/ipc';
import { taskPollingService } from '../services/taskPolling';
import { useExportStore } from '../stores/exportStore';
import type { ProgressPayload } from '../types/ipc';

export function useExportProgress() {
  const { currentTask, setCurrentTask, updateTaskProgress } = useExportStore();
  const [error, setError] = useState<string | null>(null);

  const startExport = useCallback(
    async (projectId: string) => {
      setError(null);

      try {
        const config = useExportStore.getState().config as unknown as Record<string, unknown>;
        const { task_id } = await exportApi.start(projectId, config);

        setCurrentTask({
          id: task_id,
          projectId,
          status: 'running',
          progress: 0,
          message: '开始导出...',
        });

        // 启动轮询
        taskPollingService.startPolling(
          task_id,
          'export',
          (payload: ProgressPayload) => {
            updateTaskProgress(payload.progress, payload.message);
          }
        );

        return task_id;
      } catch (err) {
        const message = err instanceof Error ? err.message : '未知错误';
        setError(message);
        throw err;
      }
    },
    [setCurrentTask, updateTaskProgress]
  );

  const cancelExport = useCallback(() => {
    if (currentTask) {
      taskPollingService.stopPolling(currentTask.id);
      setCurrentTask(null);
    }
  }, [currentTask, setCurrentTask]);

  // 监听进度
  useEffect(() => {
    if (!currentTask) return;

    const unsubscribe = window.electronAPI?.backend.onProgress((payload) => {
      if (payload.task_id === currentTask.id) {
        updateTaskProgress(payload.progress, payload.message);

        // 检查是否完成
        if (payload.progress >= 100) {
          setCurrentTask({
            ...currentTask,
            status: 'completed',
            progress: 100,
            message: '导出完成',
          });
        }
      }
    });

    return () => {
      unsubscribe?.();
    };
  }, [currentTask, updateTaskProgress, setCurrentTask]);

  return {
    currentTask,
    error,
    startExport,
    cancelExport,
  };
}
