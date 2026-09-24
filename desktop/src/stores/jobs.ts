/** 任务喂数快照：features/jobs/JobsFeed 是唯一写入方，StatusBar 与 JobDrawer 只读。 */
import { create } from 'zustand';
import type { JobInfo, JobStatus } from '@dramaclip/protocol';

const ACTIVE_STATUSES: ReadonlySet<JobStatus> = new Set(['pending', 'running']);

export function isActiveJob(job: JobInfo): boolean {
  return ACTIVE_STATUSES.has(job.status);
}

export interface JobsSummary {
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

interface JobsState {
  jobs: readonly JobInfo[];
  /** jobs.list 最近一次是否取到。取不到 ≠ 空列表：未知时界面显示「—」，不假装 0。 */
  available: boolean;
  /** 取不到时的原因原文（进 title/详情，不截断）。 */
  error: string | null;
  /** 服务端毫秒时钟（时长/已耗时的唯一基准，不掺本机时钟）。 */
  serverTimeMs: number | null;
  drawerOpen: boolean;
  setSnapshot: (jobs: readonly JobInfo[], serverTimeMs: number) => void;
  setUnavailable: (error: string) => void;
  setDrawerOpen: (open: boolean) => void;
}

export const useJobsStore = create<JobsState>((set) => ({
  jobs: [],
  available: false,
  error: null,
  serverTimeMs: null,
  drawerOpen: false,
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
