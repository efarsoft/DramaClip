/** 本机运行条件判定：机器规格 + 模型体积 → 可行性结论（诚实保守，全部可 CPU 运行）。
 *
 * 规则：磁盘按体积×1.25 留解压余量；内存按 int8 CPU 推理×1.5 且不超总量六成；
 * GPU 只影响加速不影响可行性——本地图全部设计为 CPU 可跑。
 */
import type { HealthResult } from '@dramaclip/protocol';

export interface MachineSpecs {
  readonly ramTotalGb?: number;
  readonly ramFreeGb?: number;
  readonly diskFreeGb?: number;
}

export type FitVerdict = 'unknown' | 'ok' | 'tight' | 'disk' | 'ram';

export interface FitVerdictInfo {
  readonly verdict: FitVerdict;
  readonly reason: string;
}

const DISK_HEADROOM = 1.25;
const RAM_FACTOR = 1.5;
const RAM_SHARE_LIMIT = 0.6;

/** 解析 registry 的 size_label（如 "~480MB" / "~5.5GB"）→ GB；解析失败返回 undefined。 */
export function parseSizeGb(sizeLabel: string | undefined): number | undefined {
  if (sizeLabel === undefined) return undefined;
  const match = /~?\s*(\d+(?:\.\d+)?)\s*(MB|GB)/i.exec(sizeLabel);
  const value = match?.[1];
  const unit = match?.[2];
  if (value === undefined || unit === undefined) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return undefined;
  return unit.toUpperCase() === 'GB' ? parsed : parsed / 1024;
}

export function judgeModelFit(specs: MachineSpecs, sizeGb: number | undefined): FitVerdictInfo {
  if (sizeGb === undefined) return { verdict: 'unknown', reason: '' };
  if (
    specs.diskFreeGb === undefined &&
    specs.ramTotalGb === undefined &&
    specs.ramFreeGb === undefined
  ) {
    // 规格探测失败时不下"可运行"结论——用户问的正是"能不能用"
    return { verdict: 'unknown', reason: '' };
  }
  if (specs.diskFreeGb !== undefined && sizeGb * DISK_HEADROOM > specs.diskFreeGb) {
    return {
      verdict: 'disk',
      reason: `数据盘可用不足 ${String(Math.ceil(sizeGb * DISK_HEADROOM))}GB，无法下载`,
    };
  }
  if (specs.ramTotalGb !== undefined && sizeGb * RAM_FACTOR > specs.ramTotalGb * RAM_SHARE_LIMIT) {
    return {
      verdict: 'ram',
      reason: `运行约需 ${String(Math.ceil(sizeGb * RAM_FACTOR))}GB 内存，超出本机承受`,
    };
  }
  if (specs.ramFreeGb !== undefined && sizeGb * RAM_FACTOR > specs.ramFreeGb) {
    return {
      verdict: 'tight',
      reason: '当前空闲内存偏低，建议关闭大程序后使用',
    };
  }
  return { verdict: 'ok', reason: '本机可运行' };
}

/** 整机结论：这台机器能不能吃下全部本地模型（取最大模型判）。 */
export function judgeMachine(specs: MachineSpecs, maxSizeGb: number | undefined): FitVerdictInfo {
  if (maxSizeGb === undefined) return { verdict: 'unknown', reason: '暂无本地模型清单' };
  return judgeModelFit(specs, maxSizeGb);
}

export const FIT_VERDICT_LABEL: Record<FitVerdict, string> = {
  unknown: '',
  ok: '可运行',
  tight: '内存吃紧',
  disk: '磁盘不足',
  ram: '内存不足',
};

export const FIT_VERDICT_COLOR: Record<FitVerdict, string> = {
  unknown: 'transparent',
  ok: '#34D399',
  tight: '#FBBF24',
  disk: '#F87171',
  ram: '#F87171',
};

/** health 快照 → 判定输入。 */
export function specsFromHealth(health: HealthResult | null | undefined): MachineSpecs {
  if (!health) return {};
  return {
    ramTotalGb: health.ram_total_gb,
    ramFreeGb: health.ram_free_gb,
    diskFreeGb: health.disk_free_gb,
  };
}
