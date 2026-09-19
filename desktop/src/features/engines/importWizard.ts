/**
 * 导入向导的判据层：把 models.import_inspect 的实测结果翻译成「下一步能不能走」。
 *
 * 这里不重复实现「能不能导入」——那套判据在服务端 importer 一处。本文件只拦业主还没做
 * 的选择：没声明能力、没裁决冲突、体检没过又没勾选不完整导入。所以每条理由说的都是
 * 「你还得选什么」，而不是「目录里缺什么文件」（那话由后端体检项自己说）。
 */
import type { ImportInspection, ImportRecord } from '@dramaclip/protocol';
import { formatBytes } from './assetState';

export type ImportMode = 'copy' | 'move' | 'register';

export type ConflictVerdict = 'overwrite' | 'merge' | 'coexist';

export type ExternalKind = '' | 'asr' | 'tts';

export interface ImportDraft {
  mode: ImportMode;
  onConflict: ConflictVerdict | '';
  allowIncomplete: boolean;
  externalKind: ExternalKind;
  label: string;
}

export function emptyDraft(): ImportDraft {
  return { mode: 'copy', onConflict: '', allowIncomplete: false, externalKind: '', label: '' };
}

/** 落位方式在界面上的说法。选哪种的代价写在 modeHint 里，全用实测字段。 */
export const MODE_LABEL: Record<ImportMode, string> = {
  copy: '复制到规范目录（推荐）',
  move: '移动过去',
  register: '仅登记路径，不搬文件',
};

/** 冲突裁决的三种说法：每一种对库里那份做了什么，得让业主看见再点。 */
export const VERDICT_LABEL: Record<ConflictVerdict, string> = {
  overwrite: '用导入的覆盖',
  merge: '合并补齐缺项',
  coexist: '作为新资产并存',
};

export const VERDICT_HINT: Record<ConflictVerdict, string> = {
  overwrite: '库里那份先改名留下，不删旧文件',
  merge: '只补缺失文件，不动已有权重',
  coexist: '两份都留在库里，这份登记为外部路径',
};

/** 认不出身份时要业主声明的能力类别。 */
export const EXTERNAL_KIND_LABEL: Record<Exclude<ExternalKind, ''>, string> = {
  asr: '识别 ASR',
  tts: '配音 TTS',
};

/** 拦住第 ③ 步的理由；undefined = 放行。 */
export function gateBlock(draft: ImportDraft, report: ImportInspection): string | undefined {
  const choice = effective(draft, report);
  if (!report.recognized && draft.externalKind === '') {
    return '未识别出内置模型：先声明它属于哪一类能力，不认身份就不猜它该放哪';
  }
  if (needsConflict(choice, report) && choice.onConflict === '') {
    return '冲突未裁决：库里已有同一件资产，先决定覆盖、合并还是并存，不裁决就不动库里那一份';
  }
  if (blocksLanding(choice, report)) {
    return `第 ② 步体检未通过（${failedCheckNames(report).join(' · ')}）：补齐文件，或显式勾选「按现状导入并标记为不完整」`;
  }
  return undefined;
}

/** 认不出身份的目录只能仅登记：按别的模式选出来的闸门与负载都不算数。 */
function effective(draft: ImportDraft, report: ImportInspection): ImportDraft {
  return report.recognized ? draft : { ...draft, mode: 'register' };
}

/** 第 ③ 步该高亮哪一项：草稿里残留的复制方式不算选中，选中态与实际提交的 mode 必须同一个来源。 */
export function effectiveMode(draft: ImportDraft, report: ImportInspection): ImportMode {
  return effective(draft, report).mode;
}

/** 复制/移动才可能撞到库里那份；仅登记根本不碰它。 */
export function needsConflict(draft: ImportDraft, report: ImportInspection): boolean {
  return report.conflict != null && draft.mode !== 'register';
}

/** 后端只在真要落盘（复制/移动）时把体检当闸门，仅登记只是留个路径。 */
function blocksLanding(draft: ImportDraft, report: ImportInspection): boolean {
  return !report.ok && draft.mode !== 'register' && !draft.allowIncomplete;
}

export function failedCheckNames(report: ImportInspection): string[] {
  return report.checks.filter((check) => check.status === 'fail').map((check) => check.name);
}

/** 认不出身份的目录只有「仅登记」可选：placement 不知道就不能猜。 */
export function modeChoices(report: ImportInspection): ImportMode[] {
  return report.recognized ? ['copy', 'move', 'register'] : ['register'];
}

export function modeHint(mode: ImportMode, report: ImportInspection): string {
  const need = formatBytes(report.total_bytes);
  const target = report.target?.path ?? '模型库';
  if (mode === 'copy') return `→ ${target} · 需 ${need} · 原文件保留`;
  if (mode === 'move') return `→ ${target} · 不占双倍空间；落位体检通过后源目录会被清空`;
  return `模型仍在 ${report.source_path} · 需 ${need}，库里标「外部路径」`;
}

/** 只带本次裁决真正需要的键：没冲突就别传 on_conflict，空串会让后端分不清「没选」和「选了空」。 */
export function commitPayload(
  draft: ImportDraft,
  report: ImportInspection,
): Record<string, string | boolean> {
  const choice = effective(draft, report);
  const payload: Record<string, string | boolean> = { path: report.source_path, mode: choice.mode };
  if (!report.recognized) payload.external_kind = choice.externalKind;
  if (needsConflict(choice, report) && choice.onConflict !== '') payload.on_conflict = choice.onConflict;
  if (!report.ok && choice.mode !== 'register' && choice.allowIncomplete) {
    payload.allow_incomplete = true;
  }
  const label = choice.label.trim();
  if (label !== '') payload.label = label;
  return payload;
}

/** 「选为生效」按 model_id 落配置：清单外的目录压根没有它，引擎没接入的设成生效只会让下一次分析报错。 */
export function activatableAfterImport(report: ImportInspection): boolean {
  return report.recognized && report.engine_ready;
}

/**
 * 完成页要说的那条登记：落在登记本里，而不是前端凭体检结果猜一个路径。
 * 同一路径可能导过多次（先仅登记、后来复制进库），最新那条才是此刻的状态。
 */
export function landedRecord(
  records: readonly ImportRecord[],
  sourcePath: string,
): ImportRecord | null {
  const mine = records.filter((record) => record.source_path === sourcePath);
  if (mine.length === 0) return null;
  return mine.reduce((latest, record) => (record.imported_at > latest.imported_at ? record : latest));
}
