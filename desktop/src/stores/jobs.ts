/** 任务喂数快照：features/jobs/JobsFeed 是唯一写入方，StatusBar 与 JobDrawer 只读。 */
import { create } from 'zustand';
import { onServiceEvent } from '../services/client';
import type { JobInfo, JobStatus } from '@dramaclip/protocol';

const ACTIVE_STATUSES: ReadonlySet<JobStatus> = new Set(['pending', 'running']);

export function isActiveJob(job: JobInfo): boolean {
  return ACTIVE_STATUSES.has(job.status);
}

/** summarizeJobs 的返回形状（文件内私有：状态栏与抽屉消费的是函数，不引类型）。 */
interface JobsSummary {
  readonly active: number;
  readonly failed: number;
  /** 最新启动的在跑 job 的进度（状态栏「最高优先级」取 Newest-started 语义）；
   *  在跑 job 都不带进度时为 null，状态栏只显条数（缺席而非编 0）。 */
  readonly runningPercent: number | null;
}

/** 状态栏角标只吃这三个数；jobs 取不到时调用方显示「—」，不是 0。 */
export function summarizeJobs(jobs: readonly JobInfo[]): JobsSummary {
  let active = 0;
  let failed = 0;
  let newest: JobInfo | null = null;
  for (const job of jobs) {
    if (isActiveJob(job)) {
      active += 1;
      if (newest === null || job.created_at > newest.created_at) newest = job;
    } else if (job.status === 'failed') failed += 1;
  }
  const runningPercent = newest !== null ? Math.round(newest.progress) : null;
  return { active, failed, runningPercent };
}

/** 本会话业务日志（log.append 实时流）：按作业归档的滚动视图数据源。
 * 会话级、上限 200 条——事后可查的账在 export_jobs.degraded_notes（账在库层）。 */
export interface NotifyLogEntry {
  readonly jobId: string | null;
  readonly level: string;
  readonly message: string;
  readonly at: number;
}

/** 入列后的形态：多一个单调自增 id。滚动窗口滑出旧条目时整列前移、index 全变，
 * 渲染 key 必须钉在条目自己的身份上——否则每来一条新日志，199 行全量 remount。 */
export interface StoredNotifyLogEntry extends NotifyLogEntry {
  readonly id: number;
}

interface JobsState {
  jobs: readonly JobInfo[];
  /** jobs.list 最近一次是否取到。取不到 ≠ 空列表：未知时界面显示「—」，不假装 0。 */
  available: boolean;
  /** 取不到时的原因原文（进 title/详情，不截断）。 */
  error: string | null;
  /** 服务端毫秒时钟（时长/已耗时的唯一基准，不掺本机时钟）。 */
  serverTimeMs: number | null;
  drawerOpen: boolean;
  /** 快消费档计数（分析在跑/规划在跑等）：>0 时轮询节距 2s，否则 10s。 */
  fast: number;
  notifyLog: readonly StoredNotifyLogEntry[];
  appendNotifyLog: (entry: NotifyLogEntry) => void;
  /** 登记 fast 消费；返回释放函数（useEffect 清理直接返回它）。 */
  enterFast: () => (() => void);
  setSnapshot: (jobs: readonly JobInfo[], serverTimeMs: number) => void;
  setUnavailable: (error: string) => void;
  setDrawerOpen: (open: boolean) => void;
}

/** notifyLog 条目的单调序号：进程内自增即可（会话级数据，重启归零无妨）。 */
let notifyLogSeq = 0;

export const useJobsStore = create<JobsState>((set) => ({
  jobs: [],
  available: false,
  error: null,
  serverTimeMs: null,
  drawerOpen: false,
  fast: 0,
  notifyLog: [],
  appendNotifyLog: (entry) => {
    set((state) => ({
      notifyLog: [...state.notifyLog.slice(-199), { ...entry, id: (notifyLogSeq += 1) }],
    }));
  },
  enterFast: () => {
    set((state) => ({ fast: state.fast + 1 }));
    return () => {
      set((state) => ({ fast: Math.max(state.fast - 1, 0) }));
    };
  },
  setSnapshot: (jobs, serverTimeMs) => {
    set({ jobs, available: true, error: null, serverTimeMs });
  },
  setUnavailable: (error) => {
    set({ available: false, error });
  },
  setDrawerOpen: (drawerOpen) => {
    set({ drawerOpen });
  },
}));


/** 订阅 log.append → notifyLog（在 App 装配一次，返回取消函数）。 */
export function subscribeNotifyLog(): () => void {
  return onServiceEvent((event) => {
    if (event.type !== 'notification' || event.method !== 'log.append') return;
    const params = event.params as { level?: unknown; message?: unknown; job_id?: unknown };
    useJobsStore.getState().appendNotifyLog({
      jobId: typeof params.job_id === 'string' ? params.job_id : null,
      level: typeof params.level === 'string' ? params.level : 'info',
      message: typeof params.message === 'string' ? params.message : '',
      at: Date.now(),
    });
  });
}
