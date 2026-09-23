/**
 * 开工就绪度：转写 → 文案 → 配音 → 渲染四环节，每格的结论都由资产状态、设置值与
 * 真实探测到的渲染引擎版本折算而来（红格必须说清「去哪修」）。
 */
import type { ModelInfo, SelftestResults } from '@dramaclip/protocol';
import { isModelFreeEngine, ttsEngineLabel } from './ttsVoices';
import {
  type AssetState,
  type EngineTab,
  type Reports,
  activeAsset,
  assetState,
  reportFor,
  stateLabel,
} from './assetState';

export interface ReadinessStep {
  readonly key: 'asr' | 'llm' | 'tts' | 'render';
  readonly index: string;
  readonly label: string;
  readonly detail: string;
  readonly ok: boolean;
  readonly tab: EngineTab | null;
}

export interface ReadinessInput {
  readonly models: readonly ModelInfo[];
  readonly reports: Reports;
  /** 自检账本：缺省时按「未自检」折算——不发假绿灯，而不是按通过折算。 */
  readonly selftests?: SelftestResults;
  readonly settings: Readonly<Record<string, string>>;
  readonly ffmpegVersion: string;
}

/**
 * 只有 ready（校验过 + 自检过）算「能开工」（§10.1 缺陷 4）：
 * 「未校验」「待自检」都不算就绪——文件在 ≠ 能推，没证据就不发绿灯。
 */
const OK_STATES: ReadonlySet<AssetState> = new Set<AssetState>(['ready']);

function assetStep(
  key: 'asr' | 'tts',
  index: string,
  label: string,
  model: ModelInfo | undefined,
  input: ReadinessInput,
  missingDetail: string,
): ReadinessStep {
  if (model === undefined) {
    return { key, index, label, detail: missingDetail, ok: false, tab: key };
  }
  const state = assetState(
    model,
    reportFor(input.reports, model.model_id),
    input.selftests?.[model.model_id],
  );
  return {
    key,
    index,
    label,
    detail: `${model.name} · ${stateLabel(state)}`,
    ok: OK_STATES.has(state),
    tab: key,
  };
}

function ttsStep(input: ReadinessInput): ReadinessStep {
  const engine = input.settings['tts.engine'] ?? '';
  if (isModelFreeEngine(engine)) {
    return { key: 'tts', index: '③', label: '配音', detail: `${ttsEngineLabel(engine)} · 免装`, ok: true, tab: 'tts' };
  }
  return assetStep(
    'tts',
    '③',
    '配音',
    activeAsset(input.models, 'tts', input.settings),
    input,
    engine === '' ? '未选引擎' : `${ttsEngineLabel(engine)} · 无对应资产`,
  );
}

function asrStep(input: ReadinessInput): ReadinessStep {
  return assetStep(
    'asr',
    '①',
    '转写',
    activeAsset(input.models, 'asr', input.settings),
    input,
    '未选模型',
  );
}

function llmStep(input: ReadinessInput): ReadinessStep {
  const url = input.settings['llm.base_url'] ?? '';
  return {
    key: 'llm',
    index: '②',
    label: '文案',
    detail: url === '' ? '未配置 · 解说模式不可用' : `云端 · ${input.settings['llm.model'] ?? '已配置'}`,
    ok: url !== '',
    tab: 'llm',
  };
}

function renderStep(input: ReadinessInput): ReadinessStep {
  const ok = input.ffmpegVersion !== '';
  return {
    key: 'render',
    index: '④',
    label: '渲染',
    detail: ok ? `ffmpeg ${input.ffmpegVersion}` : '渲染引擎不可用',
    ok,
    tab: null,
  };
}

/** 四格：缺一格就红，红格带着「去哪修」。 */
export function workReadiness(input: ReadinessInput): ReadinessStep[] {
  return [asrStep(input), llmStep(input), ttsStep(input), renderStep(input)];
}
