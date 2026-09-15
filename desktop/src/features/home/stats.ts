/** 工作台三统计芯片派生（规格 §4.1）：剧数 / 在跑条数+ETA / 成品数+周增。
 *
 * 两处刻意不用现成数据源，理由都是"那个数不是它名字说的东西"：
 * 1. 成品数不用 project.dashboard_summary 的 export_count——那是
 *    `SELECT COUNT(*) FROM export_jobs`（repos/projects.py:158），不带状态过滤，
 *    失败与 pending 都会被算成成品。改用 export.list_works 的条数，那条查询带
 *    `status='completed' AND output_path IS NOT NULL`。修 summary() 要动 protocol，
 *    已登记给 P-3.3。
 * 2. 周增不用 Date.now()——用 jobs.list 返回的 server_time_ms，同一把尺子量
 *    completed_at（服务端一律 _now_ms，同为毫秒）。
 */
import type { WorkItem } from '@dramaclip/protocol';

/** 低于此进度不外推：此时 elapsed/progress 的误差大于它的信息量。 */
export const MIN_ETA_PROGRESS = 5;

/** 成品扫描上限。触到即判溢出，芯片显示 N+ 而不是假精确值。
 *  服务端不钳制 limit（api/export.py 直接 int(params.get("limit", 60))）。 */
export const WORKS_SCAN_LIMIT = 1000;

const MS_PER_MINUTE = 60_000;
const MS_PER_WEEK = 7 * 86_400_000;

export interface RunningJob {
  readonly id: string;
  readonly progress: number;
  readonly createdAtMs: number;
}

export interface StatsInput {
  readonly dramaCount: number;
  readonly running: readonly RunningJob[];
  readonly serverTimeMs: number;
  readonly works: readonly WorkItem[];
}

export interface WorkbenchStats {
  readonly dramaCount: number;
  readonly runningCount: number;
  /** '' = 不显示 ETA 那一行（无在跑任务）。 */
  readonly runningEtaLabel: string;
  readonly workCount: number;
  readonly workCountOverflow: boolean;
  /** null = 样本被截断，算不出可信的周增。视图层显示 '—' 而不是一个假数字。 */
  readonly workWeekDelta: number | null;
}

/** 线性外推的剩余时间文案。
 *
 * 进度不是时间的线性函数（转写慢、拼接快），所以这是量级提示而非承诺——
 * 界面措辞用「预计还需」，不用「剩余」。取最慢的一条，因为用户问的是
 * "还要等多久全跑完"。任何算不出可信值的边界都退回 '预计中…' 或 ''，
 * 绝不输出 NaN / Infinity / 负数 / "0 分"。
 *
 * progress >= 100 的行**跳过**而不是判"预计中"：它可能是尚未被清扫的终态残留，
 * 拿它把整块 ETA 打成"预计中"等于让一条死行掩盖其余活行的真实进度。
 */
export function etaLabel(running: readonly RunningJob[], nowMs: number): string {
  let worst: number | null = null;
  for (const job of running) {
    if (job.progress >= 100) continue;
    if (job.progress < MIN_ETA_PROGRESS) return '预计中…';
    const elapsed = Math.max(nowMs - job.createdAtMs, 0);
    if (elapsed === 0) return '预计中…';
    const remain = (elapsed / job.progress) * (100 - job.progress);
    worst = worst === null ? remain : Math.max(worst, remain);
  }
  if (worst === null) return '';
  const minutes = Math.max(Math.round(worst / MS_PER_MINUTE), 1);
  if (minutes < 60) return `预计还需 ${String(minutes)} 分`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `预计还需 ${String(hours)} 小时` : `预计还需 ${String(hours)} 小时 ${String(rest)} 分`;
}

export function buildStats(input: StatsInput): WorkbenchStats {
  const overflow = input.works.length >= WORKS_SCAN_LIMIT;
  const weekStart = input.serverTimeMs - MS_PER_WEEK;
  let weekDelta = 0;
  for (const work of input.works) {
    if (work.completed_at !== undefined && work.completed_at >= weekStart) weekDelta += 1;
  }
  return {
    dramaCount: input.dramaCount,
    runningCount: input.running.length,
    runningEtaLabel: etaLabel(input.running, input.serverTimeMs),
    workCount: input.works.length,
    workCountOverflow: overflow,
    workWeekDelta: overflow ? null : weekDelta,
  };
}
