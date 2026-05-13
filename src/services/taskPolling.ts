/**
 * 任务轮询服务
 * 用于监控长时间运行的任务进度
 */

import type { ProgressPayload } from '../types/ipc';

type TaskType = 'analyze' | 'clip' | 'export';

interface TaskPollingOptions {
  pollInterval?: number;
  timeout?: number;
}

class TaskPollingService {
  private pollingIntervals: Map<string, NodeJS.Timeout> = new Map();
  private progressCallbacks: Map<string, (payload: ProgressPayload) => void> = new Map();
  private taskTypes: Map<string, TaskType> = new Map();
  private unsubscribeFunctions: (() => void)[] = [];
  private initialized = false;

  /**
   * 初始化监听器
   */
  init(): void {
    if (this.initialized || !window.electronAPI) {
      return;
    }

    const unsubProgress = window.electronAPI.backend.onProgress((payload) => {
      const callback = this.progressCallbacks.get(payload.task_id);
      if (callback) {
        callback(payload);
      }
    });

    this.unsubscribeFunctions.push(unsubProgress);
    this.initialized = true;
  }

  /**
   * 清理资源
   */
  destroy(): void {
    this.stopAll();
    this.unsubscribeFunctions.forEach((unsub) => unsub());
    this.unsubscribeFunctions = [];
    this.initialized = false;
  }

  /**
   * 开始轮询任务
   */
  startPolling(
    taskId: string,
    taskType: TaskType,
    onProgress: (payload: ProgressPayload) => void,
    options: TaskPollingOptions = {}
  ): void {
    // 清理之前的轮询
    this.stopPolling(taskId);

    const { pollInterval = 1000 } = options;

    this.taskTypes.set(taskId, taskType);
    this.progressCallbacks.set(taskId, onProgress);

    // 启动轮询
    const interval = setInterval(async () => {
      try {
        if (!window.electronAPI) {
          return;
        }

        let status: unknown;
        let method: string;

        switch (taskType) {
          case 'analyze':
            method = 'analyze.getStatus';
            break;
          case 'clip':
            method = 'clip.getProgress';
            break;
          case 'export':
            method = 'export.getProgress';
            break;
          default:
            return;
        }

        const response = await window.electronAPI.backend.call<{
          status: string;
          progress: number;
          message: string;
        }>(method, { task_id: taskId });

        if (response.success && response.data) {
          const data = response.data;

          // 如果任务完成，停止轮询
          if (data.status === 'completed' || data.status === 'failed') {
            this.stopPolling(taskId);

            // 发送最终进度
            onProgress({
              task_id: taskId,
              progress: data.status === 'completed' ? 100 : 0,
              message: data.message,
              detail: { status: data.status },
            });
          }
        }
      } catch (error) {
        console.error(`[TaskPolling] Error polling ${taskId}:`, error);
      }
    }, pollInterval);

    this.pollingIntervals.set(taskId, interval);
  }

  /**
   * 停止轮询指定任务
   */
  stopPolling(taskId: string): void {
    const interval = this.pollingIntervals.get(taskId);
    if (interval) {
      clearInterval(interval);
      this.pollingIntervals.delete(taskId);
    }

    this.progressCallbacks.delete(taskId);
    this.taskTypes.delete(taskId);
  }

  /**
   * 停止所有轮询
   */
  stopAll(): void {
    for (const taskId of this.pollingIntervals.keys()) {
      this.stopPolling(taskId);
    }
  }

  /**
   * 检查是否正在轮询
   */
  isPolling(taskId: string): boolean {
    return this.pollingIntervals.has(taskId);
  }

  /**
   * 获取当前轮询的任务数
   */
  getActivePollingCount(): number {
    return this.pollingIntervals.size;
  }
}

// 单例
export const taskPollingService = new TaskPollingService();
