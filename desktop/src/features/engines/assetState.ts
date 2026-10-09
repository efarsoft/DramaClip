/**
 * 资产状态：把 models.list（engine_ready / status / size_bytes）、models.verify 的体检结论、
 * engines.selftest 的自检账本与 models.import_records 的登记项折算成 UI 语言。
 * 这里不出现任何「写死的就绪」——页面上每句「就绪 / 缺模型 / 不完整 / 待接入」
 * 都能回溯到这几个接口的字段。
 *
 * 就绪口径（§10.1）：**校验通过 + 自检通过**，两层缺一不可——文件在 ≠ 能推。
 */
import type {
  ImportRecord,
  ModelInfo,
  SelftestResult,
  SelftestResults,
  VerifyReport,
} from '@dramaclip/protocol';

export type Reports = ReadonlyMap<string, VerifyReport>;

export type AssetState = 'ready' | 'untested' | 'unverified' | 'incomplete' | 'missing' | 'reserve';

export type EngineTab = 'asr' | 'tts' | 'llm' | 'vision';

const LABEL: Record<AssetState, string> = {
  ready: '就绪',
  untested: '待自检',
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

/** 状态判定：未接入优先（装了也不能生效），其次落盘态，再文件层校验，最后能力层自检。 */
export function assetState(
  model: ModelInfo,
  report: VerifyReport | undefined,
  selftest?: SelftestResult,
): AssetState {
  if (!model.engine_ready) return 'reserve';
  if (model.status !== 'installed') return 'missing';
  if (report === undefined) return 'unverified';
  if (!report.ok) return 'incomplete';
  // 校验过了还差能力层：没跑过自检或自检没过都不许叫「就绪」（§10.3）。
  return selftest?.ok === true ? 'ready' : 'untested';
}

export function stateLabel(state: AssetState): string {
  return LABEL[state];
}

/**
 * 能否「选为生效」：只由文件层体检结论决定（report.ok，§10.1）——warn 级异常
 * （残留/无从对账/多余副本）不禁用生效，但必须上卡且自带修法；
 * fail、未校验、没装、未接入一律禁用。「待自检」可以生效：自检是就绪口径，不是准入闸。
 */
export function canActivate(model: ModelInfo, report: VerifyReport | undefined): boolean {
  if (!model.engine_ready || model.status !== 'installed') return false;
  return report?.ok === true;
}

/** 体检里所有 fail 项，供横幅一行说清「缺哪三件」。 */
export function failureNote(report: VerifyReport | undefined): string | undefined {
  if (report === undefined) return undefined;
  const failed = report.checks.filter((check) => check.status === 'fail');
  if (failed.length === 0) return undefined;
  return failed
    .map((check) => `${check.name}${check.detail === undefined ? '' : `：${check.detail}`}`)
    .join(' · ');
}

/** warn 项条数：不拦「选为生效」，但要上卡（§10.1 降级的另一半：可见 + 有修法）。 */
export function warnCount(report: VerifyReport | undefined): number {
  if (report === undefined) return 0;
  return report.checks.filter((check) => check.status === 'warn').length;
}

/** warn 项一行摘要：判据名 + 后端原话（行内截断展示，title 给全文）。 */
export function warnNote(report: VerifyReport | undefined): string | undefined {
  if (report === undefined) return undefined;
  const warns = report.checks.filter((check) => check.status === 'warn');
  if (warns.length === 0) return undefined;
  return warns
    .map((check) => `${check.name}${check.detail === undefined ? '' : `：${check.detail}`}`)
    .join(' · ');
}

/** warn 项短摘要（只列判据名与件数）：行内窄，详情在 title 与体检面板里。 */
export function warnSummary(report: VerifyReport | undefined): string | undefined {
  if (report === undefined) return undefined;
  const names = report.checks
    .filter((check) => check.status === 'warn')
    .map((check) => check.name);
  if (names.length === 0) return undefined;
  return `${String(names.length)} 项待修：${names.join('、')}`;
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

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return '—';
  const gb = bytes / 1024 ** 3;
  if (gb < 1) return `${String(Math.round(bytes / 1024 ** 2))}MB`;
  return `${gb.toFixed(2)}GB`;
}

/** 总览·模型资产：装了几件、占多少盘、几件待修、几件还是储备。 */
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

/** 总览·域卡概览：几件可用（引擎已接入）、几件待修（体检不通过）。 */
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
    incomplete: domainModels.filter(
      (model) => assetState(model, reportFor(reports, model.model_id)) === 'incomplete',
    ).length,
  };
}

/** 生效卡的状态补充行：fail 给判据原文；待自检/未校验给能落地的下一步，不替业主下结论。 */
export function activeStateNote(
  state: AssetState,
  report: VerifyReport | undefined,
): string | undefined {
  const note = failureNote(report);
  if (note !== undefined) return note;
  if (state === 'untested') return '文件校验通过，但能力自检还没通过——资产行里点「自检」，过了才叫就绪';
  if (state === 'unverified') return '还没校验过——资产行里点「体检」按判据核一遍';
  return undefined;
}

/** 「就绪与修复」段的一条待办：现象 + 后果（§10.5 三要素的前两件，动作在行内按钮上）。 */
export interface AttentionAsset {
  readonly model: ModelInfo;
  readonly report: VerifyReport | undefined;
  readonly selftest: SelftestResult | undefined;
  /** 现象：后端判据原文优先，状态类的给一句能回溯到判据的话。 */
  readonly note: string;
  /** 后果：影响什么——切过去会失败 / 没证实能用 / 只是占盘存疑。 */
  readonly consequence: string;
  readonly severity: 'fail' | 'unconfirmed' | 'warn';
  readonly tab: EngineTab;
}

/**
 * 待办清单（§10.2：每个异常态自带修法；行内动作由 RepairActions 按判据召唤）。
 * fail = 切过去会直接失败；unconfirmed = 没有证据能用（未校验/自检没过或没跑）；
 * warn = 能用但有事要做（残留占盘、无从对账、多余副本）。没落盘/储备档不进清单——
 * 前者走下载、后者本来就不能生效，就绪度格子里各有说法。
 */
export function attentionAssets(
  models: readonly ModelInfo[],
  reports: Reports,
  selftests?: SelftestResults,
): AttentionAsset[] {
  const items: AttentionAsset[] = [];
  for (const model of models) {
    if (!model.engine_ready || model.status !== 'installed') continue;
    const report = reportFor(reports, model.model_id);
    const selftest = selftests?.[model.model_id];
    const state = assetState(model, report, selftest);
    const tab: EngineTab = model.kind === 'asr' ? 'asr' : 'tts';
    const base = { model, report, selftest, tab };
    if (state === 'incomplete') {
      items.push({
        ...base,
        note: failureNote(report) ?? '体检未通过',
        consequence: '现在切过去会直接失败',
        severity: 'fail',
      });
    } else if (state === 'unverified') {
      items.push({
        ...base,
        note: '未校验：文件在，但还没按任何判据核过',
        consequence: '没有证据能用',
        severity: 'unconfirmed',
      });
    } else if (state === 'untested') {
      items.push({
        ...base,
        note:
          selftest === undefined
            ? '文件校验通过，但能力自检还没跑过'
            : `自检未通过：${selftest.error ?? '未知原因'}`,
        consequence: '文件在不等于能推——没证实能加载',
        severity: 'unconfirmed',
      });
    } else {
      const note = warnNote(report);
      if (note !== undefined) {
        items.push({ ...base, note, consequence: '不影响推理，但占磁盘或存疑', severity: 'warn' });
      }
    }
  }
  const rank = { fail: 0, unconfirmed: 1, warn: 2 } as const;
  return [...items].sort((a, b) => rank[a.severity] - rank[b.severity]);
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

/** 向导第 ④ 步交回的 model_id：库里查不到这一行就不给设置值，前端不猜。 */
export function activateById(
  models: readonly ModelInfo[],
  modelId: string,
): Record<string, string> | null {
  const picked = models.find((model) => model.model_id === modelId);
  return picked === undefined ? null : activateSettings(picked);
}

/**
 * 「外部资产」：登记本里认不出内置身份的那几条（model_id 为 null）。
 * 有 model_id 的登记不在这儿——它由内置清单的那一行自己带来源标记。
 */
export function externalAssets(records: readonly ImportRecord[], kind: string): ImportRecord[] {
  return records.filter((record) => record.model_id === null && record.kind === kind);
}

/** 按下「删除」到底会动到什么：只有真落进库的那一份才是删文件，仅登记的不碰业主的盘。 */
export function deleteNote(model: ModelInfo): string {
  const imported = model.imported;
  if (imported === undefined || imported === null) return '删除后可随时重新下载。';
  if (imported.mode === 'register') return '只撤销登记：你放在自己盘上的目录一个字节都不动。';
  return '本地导入的那一份：删除会清掉库里这一份文件，需要时用导入向导再落一次位。';
}
