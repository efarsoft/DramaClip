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
}

/** 状态栏角标只吃这两个数；jobs 取不到时调用方显示「—」，不是 0。 */
export function summarizeJobs(jobs: readonly JobInfo[]): JobsSummary {
  let active = 0;
  let failed = 0;
  for (const job of jobs) {
    if (isActiveJob(job)) active += 1;
    else if (job.status === 'failed') failed += 1;
  }
  return { active, failed };
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
