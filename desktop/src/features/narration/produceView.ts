/** 出片段纯逻辑（卷三图4 底栏 + 意见08 一期口径）：覆盖度行与成本预估——不发 RPC。 */
import type { ExportJob, NarrationPlan } from '@dramaclip/protocol';

/**
 * 磁盘预估的系数来源：本剧已完成成片的实测均值字节。
 * 没有成片就没有实测口径——返回 null，界面磁盘项显示「—」，不编数字（意见08）。
 */
export function avgCompletedBytes(exports: readonly ExportJob[] | null): number | null {
  if (exports === null) return null;
  const sizes = exports.flatMap((job) =>
    job.status === 'completed' && (job.size_bytes ?? 0) > 0 ? [job.size_bytes ?? 0] : [],
  );
  if (sizes.length === 0) return null;
  return sizes.reduce((sum, size) => sum + size, 0) / sizes.length;
}

export interface DiskEstimate {
  /** 「约 2.0 GB（估）」；null = 没有实测口径，界面显示「—」。 */
  readonly diskGb: string | null;
  /** 系数来源说明（tooltip 原文）——「估」字必须带得出出处。 */
  readonly source: string;
}

export function estimateDisk(count: number, avgBytes: number | null): DiskEstimate {
  if (count <= 0) return { diskGb: null, source: '勾选方案后给出预估' };
  if (avgBytes === null) return { diskGb: null, source: '本剧还没有已完成成片，没有实测均值可用' };
  const gb = (count * avgBytes) / 1073741824;
  return { diskGb: `约 ${gb.toFixed(1)} GB（估）`, source: '系数来源：本剧已完成成片的实测均值大小 × 条数' };
}

export interface Coverage {
  readonly covered: number;
  readonly total: number;
}

/**
 * 覆盖度行「本次规划覆盖 n/m 集」（静默清单第 2 条）：n = 本批方案取材集合并计数（同一集只算一次），
 * m = 全剧集数。集数拿不到（m=0）或还没有方案时返回 null——常驻行也不能拿 0/0 充数。
 */
export function coverageOf(plans: readonly NarrationPlan[], episodeCount: number): Coverage | null {
  if (episodeCount <= 0 || plans.length === 0) return null;
  const ids = new Set<string>();
  for (const plan of plans) {
    for (const id of plan.episode_ids) ids.add(id);
  }
  return { covered: ids.size, total: episodeCount };
}
