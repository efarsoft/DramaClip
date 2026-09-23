// @vitest-environment node
/** analysisView 纯逻辑：档位解析、缺音轨筛选（三态）、预筛覆盖度（金色告警数据源）。 */
import { describe, expect, it } from 'vitest';
import type { AnalysisResults, Episode, EpisodeAnalysisResult } from '@dramaclip/protocol';
import { missingAudioEpisodes, parseTier, prescreenCoverage, TIER_OPTIONS } from '../analysisView';

function episode(id: string, hasAudio?: boolean | null): Episode {
  return {
    id,
    episode_number: 1,
    name: id,
    source_path: `D:/x/${id}.mp4`,
    status: 'pending',
    ...(hasAudio === undefined ? {} : { has_audio: hasAudio }),
  };
}

function entry(recommended: boolean | null): EpisodeAnalysisResult {
  return {
    episode_id: 'e',
    episode_number: 1,
    status: 'done',
    asr_segment_count: 0,
    scene_count: 0,
    highlight_count: 0,
    recommended,
  };
}

describe('转写档位', () => {
  it('认得出 recommended；其余一切值（含 null/脏值/粗档残值）回默认 all', () => {
    expect(parseTier('recommended')).toBe('recommended');
    expect(parseTier('all')).toBe('all');
    expect(parseTier(undefined)).toBe('all');
    expect(parseTier('coarse')).toBe('all');
    expect(parseTier(42)).toBe('all');
  });

  it('三选齐备；粗档灰掉且写明原因——不摆没人听的开关', () => {
    expect(TIER_OPTIONS.map((option) => option.value)).toEqual(['all', 'recommended', 'coarse']);
    const coarse = TIER_OPTIONS[2];
    expect(coarse?.disabledReason).toContain('尚未在服务端实现');
    expect(TIER_OPTIONS[0]?.disabledReason).toBe('');
    expect(TIER_OPTIONS[1]?.disabledReason).toBe('');
  });
});

describe('缺音轨筛选（三态纪律）', () => {
  it('只有 has_audio === false 计入；null/缺省 = 未知不告警', () => {
    const episodes = [episode('a', false), episode('b', true), episode('c', null), episode('d')];
    expect(missingAudioEpisodes(episodes).map((item) => item.id)).toEqual(['a']);
  });
});

describe('预筛覆盖度（静默清单第 1 条：输入覆盖度）', () => {
  it('没预筛过任何集：null（不发告警）', () => {
    expect(prescreenCoverage(null)).toBeNull();
    const results: AnalysisResults = { episodes: [entry(null), entry(null)] };
    expect(prescreenCoverage(results)).toBeNull();
  });

  it('预筛过：推荐/未推荐分开计数', () => {
    const results: AnalysisResults = {
      episodes: [entry(true), entry(true), entry(false), entry(null)],
    };
    expect(prescreenCoverage(results)).toEqual({ prescreened: 3, recommended: 2, notRecommended: 1 });
  });

  it('全部推荐：notRecommended 为 0（界面据此不渲染告警）', () => {
    const results: AnalysisResults = { episodes: [entry(true), entry(true)] };
    expect(prescreenCoverage(results)).toEqual({ prescreened: 2, recommended: 2, notRecommended: 0 });
  });
});
