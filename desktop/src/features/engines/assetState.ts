/**
 * 资产状态：把 models.list（engine_ready / status / size_bytes）与 models.verify
 * （体检结论）折算成 UI 语言。这里不出现任何「写死的就绪」——页面上每句
 * 「就绪 / 缺模型 / 不完整 / 待接入」都能回溯到这两个接口的字段。
 */
import type { ModelInfo, VerifyReport } from '@dramaclip/protocol';

export type Reports = ReadonlyMap<string, VerifyReport>;

export type AssetState = 'ready' | 'unverified' | 'incomplete' | 'missing' | 'reserve';

export type EngineTab = 'asr' | 'tts' | 'llm';

const LABEL: Record<AssetState, string> = {
  ready: '就绪',
  unverified: '未校验',
  incomplete: '不完整',
  missing: '缺模型',
  reserve: '待接入',
};

export function reportsOf(list: readonly VerifyReport[]): Reports {
  return new Map(list.map((item) => [item.model_id, item]));
}

export function reportFor(reports: Reports, modelId: string): VerifyReport | undefined {
  return reports.get(modelId);
}

/** 五态判定：未接入优先（装了也不能生效），其次落盘态，最后体检态。 */
export function assetState(model: ModelInfo, report: VerifyReport | undefined): AssetState {
  if (!model.engine_ready) return 'reserve';
  if (model.status !== 'installed') return 'missing';
  if (report === undefined) return 'unverified';
  return report.ok ? 'ready' : 'incomplete';
}

export function stateLabel(state: AssetState): string {
  return LABEL[state];
}

/** 能否「选为生效」：只有确认坏了或压根没装/没接入才禁用。 */
export function canActivate(model: ModelInfo, report: VerifyReport | undefined): boolean {
  const state = assetState(model, report);
  return state === 'ready' || state === 'unverified';
}

/** 体检里所有 fail 项，供横幅一行说清「缺哪三件」。 */
export function failureNote(report: VerifyReport | undefined): string | undefined {
  if (report === undefined || report.ok) return undefined;
  const failed = report.checks.filter((check) => check.status === 'fail');
  if (failed.length === 0) return undefined;
  return failed
    .map((check) => `${check.name}${check.detail === undefined ? '' : `：${check.detail}`}`)
    .join(' · ');
}

/** 分区只认后端下发的 engine_ready：体检结论改变不了「这台机器的工厂接没接它」。 */
export function partitionAssets(models: readonly ModelInfo[]): {
  usable: ModelInfo[];
  reserve: ModelInfo[];
} {
  return {
    usable: models.filter((model) => model.engine_ready),
    reserve: models.filter((model) => !model.engine_ready),
  };
}

export interface AssetSummary {
  readonly installed: number;
  readonly total: number;
  readonly bytes: number;
  readonly incomplete: number;
  readonly reserve: number;
}

export function assetSummary(models: readonly ModelInfo[], reports: Reports): AssetSummary {
  let installed = 0;
  let bytes = 0;
  let incomplete = 0;
  let reserve = 0;
  for (const model of models) {
    if (!model.engine_ready) reserve += 1;
    if (model.status === 'installed') {
      installed += 1;
      bytes += model.size_bytes ?? 0;
    }
    if (assetState(model, reportFor(reports, model.model_id)) === 'incomplete') incomplete += 1;
  }
  return { installed, total: models.length, bytes, incomplete, reserve };
}

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return '—';
  const gb = bytes / 1024 ** 3;
  if (gb < 1) return `${String(Math.round(bytes / 1024 ** 2))}MB`;
  return `${gb.toFixed(2)}GB`;
}

/** 域内概览：几件可用（引擎已接入）、几件待修（体检不通过）。 */
export interface DomainStats {
  readonly wired: number;
  readonly incomplete: number;
}

export function domainStats(
  models: readonly ModelInfo[],
  reports: Reports,
  kind: string,
): DomainStats {
  const domainModels = models.filter((model) => model.kind === kind);
  return {
    wired: domainModels.filter((model) => model.engine_ready).length,
    incomplete: incompleteAssets(domainModels, reports).length,
  };
}

export interface IncompleteAsset {
  readonly model: ModelInfo;
  readonly note: string;
  readonly tab: EngineTab;
}

/**
 * 「待修」清单：装了但体检不通过的已接入资产。
 * 没落盘的算缺模型（走下载），未接入的算储备（本来就不能生效），都不进这里。
 */
export function incompleteAssets(
  models: readonly ModelInfo[],
  reports: Reports,
): IncompleteAsset[] {
  const items: IncompleteAsset[] = [];
  for (const model of models) {
    const report = reportFor(reports, model.model_id);
    if (assetState(model, report) !== 'incomplete') continue;
    items.push({
      model,
      note: failureNote(report) ?? '体检未通过',
      tab: model.kind === 'asr' ? 'asr' : 'tts',
    });
  }
  return items;
}

/**
 * 「选为生效」写回设置表的值——必须与 activeAsset 的查法严格互逆：
 * whisper 一个档位一项（存短名，后端直接喂给 faster-whisper），其余引擎一个引擎一项。
 */
export function activateSettings(model: ModelInfo): Record<string, string> {
  const WHISPER = 'faster-whisper-';
  if (model.kind === 'asr') {
    if (model.engine === 'faster_whisper' && model.model_id.startsWith(WHISPER)) {
      return { 'asr.engine': 'faster_whisper', 'asr.model': model.model_id.slice(WHISPER.length) };
    }
    return { 'asr.engine': model.engine };
  }
  return { 'tts.engine': model.engine };
}

/** 设置值 → 资产：既接受完整 model_id，也接受档位短名（small → faster-whisper-small）。 */
function findAsset(
  models: readonly ModelInfo[],
  kind: string,
  value: string,
): ModelInfo | undefined {
  if (value === '') return undefined;
  return models.find(
    (model) =>
      model.kind === kind &&
      (model.model_id === value || model.model_id.endsWith(`-${value}`) || model.engine === value),
  );
}

/**
 * 「当前生效」的那件资产：设置里存的只有引擎短名与档位短名，回到资产库里查。
 * faster-whisper 一档一项（按 asr.model 定位），其余引擎一个引擎一件（按引擎名定位）。
 */
export function activeAsset(
  models: readonly ModelInfo[],
  kind: 'asr' | 'tts',
  settings: Readonly<Record<string, string>>,
): ModelInfo | undefined {
  if (kind === 'tts') return findAsset(models, 'tts', settings['tts.engine'] ?? '');
  const engine = settings['asr.engine'] ?? '';
  if (engine !== '' && engine !== 'faster_whisper') return findAsset(models, 'asr', engine);
  return findAsset(models, 'asr', settings['asr.model'] ?? '');
}
