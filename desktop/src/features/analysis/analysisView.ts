/** 分析工作台纯逻辑（卷二 #5 / 09-10 §2.3①②）：缺音轨告警、金色覆盖度告警、转写档位——不发 RPC。 */
import type { AnalysisResults, Episode } from '@dramaclip/protocol';

/** 项目级设置键：转写档位（project.settings 覆盖，project.update_settings 持久化）。 */
export const TIER_KEY = 'analysis.transcribe_tier';

export type TranscribeTier = 'all' | 'recommended';

export interface TierOption {
  readonly value: TranscribeTier | 'coarse';
  readonly label: string;
  /** 不可选档位的原因原文；可选档位为空串。 */
  readonly disabledReason: string;
}

/** 档位三选（09-10 §4.3② 硬要求）。第三档「粗档」服务端没有低精度 ASR 档位——
 * 灰掉并写明原因，不摆没人听的开关（宁灰勿假绿）。 */
export const TIER_OPTIONS: readonly TierOption[] = [
  { value: 'all', label: '全部精转（默认推荐）', disabledReason: '' },
  { value: 'recommended', label: '仅推荐集精转', disabledReason: '' },
  {
    value: 'coarse',
    label: '未精转集走粗档',
    disabledReason: '低精度 ASR 粗档尚未在服务端实现——落地前不放假开关',
  },
];

/** 设置值 → 档位；认不出的值（含 null/脏值）一律回默认 'all'，不猜。 */
export function parseTier(raw: unknown): TranscribeTier {
  return raw === 'recommended' ? 'recommended' : 'all';
}

/** 缺音频轨的集（has_audio === false）；null/缺省 = 未重扫的旧集，取不到 ≠ 没有，不计入。 */
export function missingAudioEpisodes(episodes: readonly Episode[]): Episode[] {
  return episodes.filter((episode) => episode.has_audio === false);
}

export interface PrescreenCoverage {
  /** 预筛过的集数（recommended 非 null）。 */
  readonly prescreened: number;
  readonly recommended: number;
  readonly notRecommended: number;
}

/** 金色覆盖度告警的数据源：预筛只放行了一部分集，其余集的台词没进模型视野——不许静默。 */
export function prescreenCoverage(results: AnalysisResults | null): PrescreenCoverage | null {
  if (results === null) return null;
  const screened = results.episodes.filter((entry) => entry.recommended !== null && entry.recommended !== undefined);
  if (screened.length === 0) return null;
  const recommended = screened.filter((entry) => entry.recommended === true).length;
  return {
    prescreened: screened.length,
    recommended,
    notRecommended: screened.length - recommended,
  };
}
