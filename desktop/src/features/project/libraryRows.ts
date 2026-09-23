/** 剧库行派生与查询：复用工作台矩阵的同一套阶段词汇（卷三意见 07），纯函数。 */
import type { Project } from '@dramaclip/protocol';
import { buildMatrixRows, matchesFilter, type MatrixFilter, type MatrixRow } from '../home/matrixRows';
import { continueRoute, UNKNOWN_STAGES } from '../stages/stageState';
import type { LibraryFacts } from './useLibraryFacts';

export type SortKey = 'activity' | 'created' | 'name';

export interface LibraryQuery {
  readonly filter: MatrixFilter;
  readonly search: string;
  readonly sort: SortKey;
}

export interface LibraryRows {
  readonly rows: MatrixRow[];
  /** 成品/任务账缺席：卡片成品数显示「—」、灯全灰、卡点句缺席。 */
  readonly factsMissing: boolean;
}

export function buildLibraryRows(projects: readonly Project[], facts: LibraryFacts): LibraryRows {
  const { works, jobs, serverTimeMs } = facts;
  if (works !== null && jobs !== null && serverTimeMs !== null) {
    return { rows: buildMatrixRows(projects, works, jobs, serverTimeMs), factsMissing: false };
  }
  // 账本缺席：只信项目行里的硬数据（集数），其余点灰不猜。
  return {
    factsMissing: true,
    rows: projects.map((project) => {
      const stages = { ...UNKNOWN_STAGES, intake: project.episode_count > 0 ? ('done' as const) : ('idle' as const) };
      return {
        project,
        workCount: 0,
        stages,
        note: null,
        cont: continueRoute(project.id, stages),
        running: false,
        failed: false,
        lastActivityMs: project.created_at,
      };
    }),
  };
}

export function sortLibraryRows(rows: readonly MatrixRow[], sort: SortKey): MatrixRow[] {
  const sorted = [...rows];
  if (sort === 'created') {
    sorted.sort((a, b) => b.project.created_at - a.project.created_at);
  } else if (sort === 'name') {
    sorted.sort((a, b) => a.project.name.localeCompare(b.project.name, 'zh-Hans-CN'));
  } else {
    sorted.sort((a, b) => b.lastActivityMs - a.lastActivityMs);
  }
  return sorted;
}

/** 筛选 + 搜索 + 排序一次过；搜索是剧名包含（大小写不敏感），trim 后为空 = 不搜。 */
export function applyQuery(rows: readonly MatrixRow[], query: LibraryQuery): MatrixRow[] {
  const needle = query.search.trim().toLowerCase();
  const filtered = rows.filter(
    (row) => matchesFilter(row, query.filter) && (needle === '' || row.project.name.toLowerCase().includes(needle)),
  );
  return sortLibraryRows(filtered, query.sort);
}
