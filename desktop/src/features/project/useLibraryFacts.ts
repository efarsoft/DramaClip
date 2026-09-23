/** 剧库卡片阶段灯的数据源：成品账 + 任务账（随页面装载低频取一次）。
 *
 * 取失败不拖垮列表：项目列表照常渲染，卡片灯点灰（UNKNOWN_STAGES）、
 * 卡点句缺席，页顶横幅说清哪本账缺了——宁灰勿假绿（卷三意见 03）。
 */
import { useCallback, useEffect, useState } from 'react';
import type { JobInfo, JobsListResult, WorkItem } from '@dramaclip/protocol';
import { jobsApi, listWorks } from '../../services/client';
import { WORKS_SCAN_LIMIT } from '../home/stats';
import { JOBS_SCAN_LIMIT } from '../home/useWorkbench';

export interface LibraryFacts {
  /** null = 取不到（不是「没有成品」）。 */
  readonly works: readonly WorkItem[] | null;
  /** null = 取不到（不是「没有在跑」）。 */
  readonly jobs: readonly JobInfo[] | null;
  readonly serverTimeMs: number | null;
  /** 缺账原因原文；null = 两本账都在。 */
  readonly factsError: string | null;
  readonly reload: () => Promise<void>;
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}

export function useLibraryFacts(): LibraryFacts {
  const [works, setWorks] = useState<WorkItem[] | null>(null);
  const [jobs, setJobs] = useState<JobInfo[] | null>(null);
  const [serverTimeMs, setServerTimeMs] = useState<number | null>(null);
  const [factsError, setFactsError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [worksResult, jobsResult] = await Promise.all([
      listWorks(WORKS_SCAN_LIMIT).then(
        (value): WorkItem[] | Error => value,
        asError,
      ),
      jobsApi.list(JOBS_SCAN_LIMIT).then(
        (value): JobsListResult | Error => value,
        asError,
      ),
    ]);
    const problems: string[] = [];
    if (worksResult instanceof Error) {
      setWorks(null);
      problems.push(`成品账：${worksResult.message}`);
    } else {
      setWorks(worksResult);
    }
    if (jobsResult instanceof Error) {
      setJobs(null);
      setServerTimeMs(null);
      problems.push(`任务账：${jobsResult.message}`);
    } else {
      setJobs(jobsResult.jobs);
      setServerTimeMs(jobsResult.server_time_ms);
    }
    setFactsError(problems.length > 0 ? problems.join('；') : null);
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { works, jobs, serverTimeMs, factsError, reload };
}
