/** useAnalysisWorkspace 的纯函数：轮询集状态合并（运行中徽章翻动的唯一通道）+ 单集详情归位。 */
import { describe, expect, it } from 'vitest';
import type { Episode, EpisodeDetailResult } from '@dramaclip/protocol';
import { mergeEpisodeDetail, mergeEpisodeStatuses } from '../useAnalysisWorkspace';

function episode(id: string, status: string): Episode {
  return {
    id,
    episode_number: 1,
    name: id,
    source_path: `D:/x/${id}.mp4`,
    status,
  };
}

describe('mergeEpisodeStatuses', () => {
  it('把轮询到的实时状态翻进列表（failed → analyzing）', () => {
    const episodes = [episode('e1', 'failed'), episode('e2', 'failed')];
    const merged = mergeEpisodeStatuses(episodes, [
      { episode_id: 'e1', status: 'analyzing' },
      { episode_id: 'e2', status: 'failed' },
    ]);
    expect(merged.map((ep) => ep.status)).toEqual(['analyzing', 'failed']);
    expect(merged[0]).not.toBe(episodes[0]); // 变化项给新引用，触发重渲染
    expect(merged[1]).toBe(episodes[1]); // 未变项保留原引用
  });

  it('全部无变化时返回原引用——React 跳过重渲染', () => {
    const episodes = [episode('e1', 'analyzing')];
    const merged = mergeEpisodeStatuses(episodes, [
      { episode_id: 'e1', status: 'analyzing' },
    ]);
    expect(merged).toBe(episodes);
  });

  it('忽略列表里没有的 episode id（不臆造条目）', () => {
    const episodes = [episode('e1', 'pending')];
    const merged = mergeEpisodeStatuses(episodes, [
      { episode_id: 'nope', status: 'done' },
    ]);
    expect(merged).toBe(episodes);
  });

  it('status 响应缺 episodes 字段时原样返回（协议可选字段兜底）', () => {
    const episodes = [episode('e1', 'pending')];
    expect(mergeEpisodeStatuses(episodes, undefined)).toBe(episodes);
  });
});

/** mergeEpisodeDetail：单集详情（该集自己的列表）→ 页面状态（集号 → 列表的映射）。 */
describe('mergeEpisodeDetail', () => {
  const detail: EpisodeDetailResult = {
    episode_id: 'e2',
    asr_segments: [{ start: 0, end: 1, text: '第一句' }, { start: 1, end: 2, text: '第二句' }],
    highlights: [{ start: 0, end: 2, score: 0.8 }],
    conflict_scores: [{ scene_index: 0, start: 0, end: 2, score: 6 }],
    prescreen: { prescreen_score: 77, recommended: 1 },
    visual_track: { engine: 'qwen3-vl-4b', frames: [] },
  };

  it('列表按集号归位——不是把数组摊成 0/1/2 下标键', () => {
    const merged = mergeEpisodeDetail({ episodes: [] }, detail);
    expect(Object.keys(merged.asr_segments ?? {})).toEqual(['e2']);
    expect(merged.asr_segments?.e2?.map((seg) => seg.text)).toEqual(['第一句', '第二句']);
    expect(merged.highlights?.e2).toHaveLength(1);
    expect(merged.conflict_scores?.e2).toHaveLength(1);
    expect(merged.prescreen?.e2?.prescreen_score).toBe(77);
    expect(merged.visual_tracks?.e2?.engine).toBe('qwen3-vl-4b');
  });

  it('已拉过的其他集与摘要原样保留', () => {
    const summary = [{
      episode_id: 'e1', episode_number: 1, status: 'done',
      asr_segment_count: 1, scene_count: 1, highlight_count: 0,
    }];
    const prev = mergeEpisodeDetail(
      { episodes: summary },
      { ...detail, episode_id: 'e1', asr_segments: [{ start: 0, end: 1, text: '别集的话' }] },
    );
    const merged = mergeEpisodeDetail(prev, detail);
    expect(merged.episodes).toBe(summary);
    expect(merged.asr_segments?.e1?.[0]?.text).toBe('别集的话');
    expect(Object.keys(merged.asr_segments ?? {}).sort()).toEqual(['e1', 'e2']);
  });

  it('空列表照样落键（拉过 ≠ 没拉），没有的项不落键、重拉变空则摘键', () => {
    const empty: EpisodeDetailResult = {
      episode_id: 'e2', asr_segments: [], highlights: [], conflict_scores: [],
      prescreen: null, visual_track: null,
    };
    const first = mergeEpisodeDetail(null, empty);
    expect(first.asr_segments?.e2).toEqual([]);
    expect(first.prescreen).toEqual({});
    expect(first.visual_tracks).toEqual({});
    // 先有画面轨，重析后没有了：旧键必须摘掉，不能残留上一轮的画面
    const stale = mergeEpisodeDetail(mergeEpisodeDetail(null, detail), empty);
    expect(stale.visual_tracks).toEqual({});
    expect(stale.prescreen).toEqual({});
  });
});
