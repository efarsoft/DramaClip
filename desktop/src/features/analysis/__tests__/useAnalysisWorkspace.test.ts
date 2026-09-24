/** mergeEpisodeStatuses：轮询实时集状态合并——运行中徽章翻动的唯一通道（此前整轮冻结）。 */
import { describe, expect, it } from 'vitest';
import type { Episode } from '@dramaclip/protocol';
import { mergeEpisodeStatuses } from '../useAnalysisWorkspace';

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
