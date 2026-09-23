/** 我的剧矩阵的行派生：纯函数，不发 RPC（数据由 useWorkbench 一次取全）。
 *
 * 每行 = 一部剧的五要素：封面、meta、四阶段灯、卡点句、继续按钮（卷三图 1）。
 * 聚合筛选（卷三意见 05）：全部/在跑/有失败/已出片——芯片即筛选器，点了就收窄。
 */
import type { JobInfo, Project, WorkItem } from '@dramaclip/protocol';
import {
  continueRoute,
  degradedFacts,
  deriveBlockNote,
  deriveStages,
  jobFactsFor,
  type BlockNote,
  type StageMap,
} from '../stages/stageState';

export interface MatrixRow {
  readonly project: Project;
  readonly workCount: number;
  readonly stages: StageMap;
  readonly note: BlockNote | null;
  readonly cont: { readonly route: string; readonly label: string };
  readonly running: boolean;
  readonly failed: boolean;
  readonly lastActivityMs: number;
}

export type MatrixFilter = 'all' | 'running' | 'failed' | 'shipped';

export const FILTERS: readonly { key: MatrixFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '在跑' },
  { key: 'failed', label: '有失败' },
  { key: 'shipped', label: '已出片' },
];

export function buildMatrixRows(
  projects: readonly Project[],
  works: readonly WorkItem[],
  jobs: readonly JobInfo[],
  serverTimeMs: number,
): MatrixRow[] {
  const workCounts = new Map<string, number>();
  const workTimes = new Map<string, number>();
  for (const work of works) {
    workCounts.set(work.project_id, (workCounts.get(work.project_id) ?? 0) + 1);
    if (work.completed_at !== undefined) {
      workTimes.set(work.project_id, Math.max(workTimes.get(work.project_id) ?? 0, work.completed_at));
    }
  }
  return projects.map((project) => {
    const workCount = workCounts.get(project.id) ?? 0;
    const jobFacts = jobFactsFor(project.id, jobs);
    const stageFacts = degradedFacts(project.episode_count, workCount, jobFacts);
    const stages = deriveStages(stageFacts);
    const note = deriveBlockNote(stageFacts, stages, {
      dramaId: project.id,
      createdAtMs: project.created_at,
      serverTimeMs,
    });
    return {
      project,
      workCount,
      stages,
      note,
      cont: continueRoute(project.id, stages),
      running: jobFacts.activeTypes.size > 0,
      failed: jobFacts.failed !== null,
      lastActivityMs: lastActivity(project, jobs, workTimes.get(project.id) ?? 0),
    };
  });
}

/** 最近动静：建库时间、该剧成品完成时间、该剧任务账更新时间三者取最大（同一把服务端尺子）。 */
function lastActivity(project: Project, jobs: readonly JobInfo[], lastWorkMs: number): number {
  let latest = Math.max(project.created_at, lastWorkMs);
  for (const job of jobs) {
    if (job.ref_id === project.id && job.updated_at > latest) latest = job.updated_at;
  }
  return latest;
}

/** 排序：最近打开的那部置顶（继续上次），其余按最近动静倒序。 */
export function sortRows(rows: readonly MatrixRow[], heroId: string | null): MatrixRow[] {
  return [...rows].sort((a, b) => {
    if (a.project.id === heroId) return -1;
    if (b.project.id === heroId) return 1;
    return b.lastActivityMs - a.lastActivityMs;
  });
}

export function matchesFilter(row: MatrixRow, filter: MatrixFilter): boolean {
  if (filter === 'running') return row.running;
  if (filter === 'failed') return row.failed;
  if (filter === 'shipped') return row.workCount > 0;
  return true;
}

export function countByFilter(rows: readonly MatrixRow[], filter: MatrixFilter): number {
  if (filter === 'all') return rows.length;
  return rows.filter((row) => matchesFilter(row, filter)).length;
}
