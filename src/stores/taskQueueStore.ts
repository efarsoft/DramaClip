/**
 * 统一任务队列 Store
 * 管理所有长时间运行任务（analyze/clip/export）的排队、执行、重试、取消
 */
import { create } from 'zustand';
import { ipcClient } from '../services/ipc';

// ── 类型定义 ──

export type TaskType = 'analyze' | 'clip' | 'export';

export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface Task {
  id: string;
  type: TaskType;
  projectId: string;
  status: TaskStatus;
  progress: number;
  phase: string;
  message: string;
  /** 创建任务时的参数（用于重试） */
  params: Record<string, unknown>;
  outputPath?: string;
  error?: string;
  createdAt: number;
  startedAt?: number;
  completedAt?: number;
  /** 唯一标识同类型重复提交（相同 projectId+type+params 视为重复） */
  dedupKey?: string;
}

// ── IPC 方法表 ──

const IPC_METHODS: Record<TaskType, { start: string; progress: string; cancel: string }> = {
  analyze: { start: 'analyze.start', progress: 'analyze.getStatus', cancel: 'analyze.cancel' },
  clip:    { start: 'clip.execute', progress: 'clip.getProgress', cancel: '' },
  export:  { start: 'export.start', progress: 'export.getProgress', cancel: '' },
};

// ── Store ──

interface TaskQueueState {
  /** 所有任务，按入队顺序排列 */
  tasks: Task[];
  /** 当前正在执行的任务 ID（无并发） */
  activeTaskId: string | null;
  /** 是否正在执行（简化外部判断） */
  isRunning: boolean;

  // ── 操作 ──

  /** 入队一个新任务。返回 taskId；若检测到重复则返回已有任务 ID 不入队 */
  enqueue: (type: TaskType, projectId: string, params: Record<string, unknown>) => string;
  /** 取消指定任务（未开始的移出队列，已运行的后端 cancel） */
  cancel: (taskId: string) => Promise<void>;
  /** 重试失败/已取消的任务 */
  retry: (taskId: string) => Promise<void>;
  /** 清理已结束的任务 */
  clearCompleted: () => void;
  /** 删除单个任务 */
  remove: (taskId: string) => void;
  /** 清空所有任务 */
  clearAll: () => void;
  /** @internal 执行队列中下一个等待的任务 */
  executeNext: () => void;
}

// ── 辅助：生成去重 Key ──

function buildDedupKey(type: TaskType, projectId: string, params: Record<string, unknown>): string {
  // 对 params 中不影响实质的字段（如回调）做稳定排序
  const stable = Object.keys(params)
    .filter(k => k !== 'onProgress' && k !== 'onComplete')
    .sort()
    .map(k => `${k}=${JSON.stringify(params[k])}`)
    .join('&');
  return `${type}:${projectId}:${stable}`;
}

// ── 辅助：生成 ID ──

let _counter = 0;
function nextId(type: TaskType): string {
  return `${type}-${Date.now()}-${++_counter}`;
}

// ── 轮询执行一个任务 ──

async function pollTask(
  task: Task,
  onUpdate: (updates: Partial<Task>) => void,
  onDone: () => void,
): Promise<void> {
  const method = IPC_METHODS[task.type].progress;
  if (!method) {
    onDone();
    return;
  }

  const poll = async () => {
    try {
      const status = await ipcClient.call<{
        status: string;
        progress: number;
        phase?: string;
        message?: string;
        output_path?: string;
      }>(method, { task_id: task.id });

      if (!status) {
        onUpdate({ status: 'failed', message: '获取任务状态失败' });
        onDone();
        return;
      }

      onUpdate({
        progress: status.progress ?? 0,
        phase: status.phase || status.message || '',
        message: status.message || '',
      });

      if (status.status === 'completed') {
        onUpdate({
          status: 'completed',
          progress: 100,
          completedAt: Date.now(),
          outputPath: status.output_path,
        });
        onDone();
        return;
      }

      if (status.status === 'failed') {
        onUpdate({ status: 'failed', error: status.message || '任务失败', completedAt: Date.now() });
        onDone();
        return;
      }

      // 还在运行中，继续轮询
      setTimeout(poll, 1000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onUpdate({ status: 'failed', error: msg, message: msg, completedAt: Date.now() });
      onDone();
    }
  };

  // 100ms 后开始第一次轮询（给任务一点启动时间）
  setTimeout(poll, 100);
}

// ── Store 实现 ──

export const useTaskQueueStore = create<TaskQueueState>((set, get) => ({
  tasks: [],
  activeTaskId: null,
  isRunning: false,

  enqueue: (type, projectId, params) => {
    const state = get();
    const dedupKey = buildDedupKey(type, projectId, params);

    // 查重：相同 type+projectId+params 且未结束的任务不重复提交
    const existing = state.tasks.find(
      t => t.dedupKey === dedupKey && (t.status === 'queued' || t.status === 'running'),
    );
    if (existing) {
      console.log(`[TaskQueue] 跳过重复任务: ${existing.id}`);
      return existing.id;
    }

    const id = nextId(type);
    const task: Task = {
      id,
      type,
      projectId,
      status: 'queued',
      progress: 0,
      phase: '等待中',
      message: '已加入队列',
      params: { ...params },
      createdAt: Date.now(),
      dedupKey,
    };

    set(s => ({ tasks: [...s.tasks, task] }));

    // 如果当前没有活跃任务，立即执行
    if (!get().activeTaskId) {
      get().executeNext();
    }

    return id;
  },

  cancel: async (taskId) => {
    const task = get().tasks.find(t => t.id === taskId);
    if (!task) return;

    if (task.status === 'queued') {
      // 未开始：直接移除
      set(s => ({
        tasks: s.tasks.filter(t => t.id !== taskId),
      }));
      return;
    }

    if (task.status === 'running') {
      // 正在运行：通知后端取消
      const cancelMethod = IPC_METHODS[task.type]?.cancel;
      if (cancelMethod) {
        try {
          await ipcClient.call(cancelMethod, { task_id: taskId });
        } catch { /* ignore */ }
      }
      set(s => ({
        tasks: s.tasks.map(t =>
          t.id === taskId ? { ...t, status: 'cancelled', message: '已取消', completedAt: Date.now() } : t,
        ),
        activeTaskId: s.activeTaskId === taskId ? null : s.activeTaskId,
      }));
      // 执行下一个
      get().executeNext();
    }
  },

  retry: async (taskId) => {
    const task = get().tasks.find(t => t.id === taskId);
    if (!task) return;
    if (task.status !== 'failed' && task.status !== 'cancelled') return;

    // 复用 taskId，重置状态
    const resetTask: Task = {
      ...task,
      status: 'queued',
      progress: 0,
      phase: '等待重试',
      message: '已重新加入队列',
      error: undefined,
      outputPath: undefined,
      startedAt: undefined,
      completedAt: undefined,
    };

    set(s => ({
      tasks: s.tasks.map(t => (t.id === taskId ? resetTask : t)),
    }));

    if (!get().activeTaskId) {
      get().executeNext();
    }
  },

  clearCompleted: () => {
    set(s => ({
      tasks: s.tasks.filter(
        t => t.status === 'queued' || t.status === 'running',
      ),
    }));
  },

  remove: (taskId) => {
    set(s => ({
      tasks: s.tasks.filter(t => t.id !== taskId),
    }));
  },

  clearAll: () => {
    set({ tasks: [], activeTaskId: null, isRunning: false });
  },

  // ── 内部：执行下一个任务 ──
  executeNext: () => {
    const state = get();
    if (state.activeTaskId) return; // 有活跃任务，不执行

    const next = state.tasks.find(t => t.status === 'queued');
    if (!next) {
      set({ isRunning: false });
      return;
    }

    // 运行时 task_id 引用，后端返回后可能更新（mock 后端会生成自己的 task_id）
    let runtimeTaskId = next.id;

    // 标记为 running
    set(s => ({
      activeTaskId: runtimeTaskId,
      isRunning: true,
      tasks: s.tasks.map(t =>
        t.id === runtimeTaskId
          ? { ...t, status: 'running', phase: '启动中...', message: '任务执行中', startedAt: Date.now() }
          : t,
      ),
    }));

    // 启动任务
    const method = IPC_METHODS[next.type].start;
    ipcClient
      .call<{ task_id: string }>(method, next.params)
      .then((result) => {
        // 后端可能返回不同的 task_id，用它覆盖，确保轮询能匹配
        if (result?.task_id && result.task_id !== runtimeTaskId) {
          const oldId = runtimeTaskId;
          runtimeTaskId = result.task_id;
          set(s => ({
            tasks: s.tasks.map(t =>
              t.id === oldId ? { ...t, id: runtimeTaskId } : t,
            ),
            activeTaskId: runtimeTaskId,
          }));
        }

        // 获取当前任务对象（ID 可能已更新）
        const currentTask = get().tasks.find(t => t.id === runtimeTaskId);
        if (!currentTask) return; // 任务被清理

        // 开始轮询进度
        pollTask(
          currentTask,
          (updates) => {
            // 任务已被取消，忽略后续更新
            const current = get().tasks.find(t => t.id === runtimeTaskId);
            if (!current || current.status === 'cancelled') return;
            set(s => ({
              tasks: s.tasks.map(t => (t.id === runtimeTaskId ? { ...t, ...updates } : t)),
            }));
          },
          () => {
            // 当前任务结束，清理并执行下一个
            set(s => ({
              activeTaskId: s.activeTaskId === runtimeTaskId ? null : s.activeTaskId,
            }));
            // 给状态更新一点时间再执行下一个
            setTimeout(() => get().executeNext(), 300);
          },
        );
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        set(s => ({
          activeTaskId: null,
          tasks: s.tasks.map(t =>
            t.id === runtimeTaskId ? { ...t, status: 'failed', error: msg, message: msg, completedAt: Date.now() } : t,
          ),
        }));
        setTimeout(() => get().executeNext(), 300);
      });
  },
}));

/** 选择器：获取指定 type 的当前运行中任务 */
export function useActiveTask(type: TaskType): Task | undefined {
  return useTaskQueueStore(s =>
    s.tasks.find(t => t.type === type && t.status === 'running'),
  );
}

/** 选择器：获取指定 type 的所有任务 */
export function useTasksByType(type: TaskType): Task[] {
  return useTaskQueueStore(s => s.tasks.filter(t => t.type === type));
}

/** 选择器：获取队列统计 */
export function useQueueStats(): {
  total: number;
  running: number;
  queued: number;
  completed: number;
  failed: number;
} {
  return useTaskQueueStore(s => {
    const tasks = s.tasks;
    return {
      total: tasks.length,
      running: tasks.filter(t => t.status === 'running').length,
      queued: tasks.filter(t => t.status === 'queued').length,
      completed: tasks.filter(t => t.status === 'completed').length,
      failed: tasks.filter(t => t.status === 'failed' || t.status === 'cancelled').length,
    };
  });
}
