// @vitest-environment jsdom
/**
 * 按集分拆后的详情加载：默认选中集自动拉、切集拉、整页重载后补拉。
 *
 * 替身按 protocol/schemas/analysis.json 里 analysis.episode_detail 的**真实形状**写
 * （该集自己的列表），不按页面状态的映射形状写——上一版替身写成了映射，「把数组展开
 * 进映射」这个错就这样漏过了全部测试，分析页转写/高光/曲线/画面轨上线即整体失效。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Episode, EpisodeDetailResult, ProjectGetResult } from '@dramaclip/protocol';
import { useDramaSelectionStore } from '../../../stores/dramaSelection';
import { useUiStore } from '../../../stores/ui';
import { useAnalysisWorkspace } from '../useAnalysisWorkspace';

const projectApiGet = vi.fn<() => Promise<ProjectGetResult>>();
const episodeDetail = vi.fn<(episodeId: string) => Promise<EpisodeDetailResult>>();

vi.mock('../../../services/client', () => ({
  projectApi: { get: () => projectApiGet() },
  analysisApi: {
    episodes: () => Promise.resolve({ episodes: [] }),
    episodeDetail: (episodeId: string) => episodeDetail(episodeId),
    status: vi.fn(),
  },
  jobsApi: { list: () => Promise.resolve({ jobs: [] }) },
  onServiceEvent: () => (): void => undefined,
}));

function episode(id: string, number: number): Episode {
  return { id, episode_number: number, name: id, source_path: `D:/x/${id}.mp4`, status: 'done' };
}

function project(episodes: Episode[]): ProjectGetResult {
  return {
    project: {
      id: 'p1',
      name: '测试剧',
      source_path: 'D:/x',
      status: 'active',
      created_at: 0,
      episode_count: episodes.length,
      settings: {},
    },
    episodes,
  };
}

function detailOf(episodeId: string, text: string): EpisodeDetailResult {
  return {
    episode_id: episodeId,
    asr_segments: [{ start: 0, end: 1, text }],
    highlights: [{ start: 0, end: 1, score: 0.9 }],
    conflict_scores: [{ scene_index: 0, start: 0, end: 1, score: 7 }],
    prescreen: null,
    visual_track: null,
  };
}

function textOf(view: { result: { current: ReturnType<typeof useAnalysisWorkspace> } }, id: string): string | undefined {
  return view.result.current.results?.asr_segments?.[id]?.[0]?.text;
}

beforeEach(() => {
  vi.clearAllMocks();
  useDramaSelectionStore.setState({ projectId: null, episodeIds: [] });
  useUiStore.setState({ serviceState: 'ready' });
  projectApiGet.mockResolvedValue(project([episode('a', 1), episode('b', 2)]));
  episodeDetail.mockImplementation((id) => Promise.resolve(detailOf(id, `${id} 的台词`)));
});

describe('单集详情加载', () => {
  it('首屏默认选中的集不用点就有转写/高光/冲突分', async () => {
    const view = renderHook(() => useAnalysisWorkspace('p1'));
    await waitFor(() => {
      expect(textOf(view, 'a')).toBe('a 的台词');
    });
    expect(view.result.current.activeEpisodeId).toBe('a');
    expect(view.result.current.results?.highlights?.a).toHaveLength(1);
    expect(view.result.current.results?.conflict_scores?.a).toHaveLength(1);
    expect(episodeDetail).toHaveBeenCalledTimes(1);
  });

  it('切到另一集拉它的详情，先前那集的仍在', async () => {
    const view = renderHook(() => useAnalysisWorkspace('p1'));
    await waitFor(() => {
      expect(textOf(view, 'a')).toBe('a 的台词');
    });
    act(() => {
      view.result.current.setActiveEpisodeId('b');
    });
    await waitFor(() => {
      expect(textOf(view, 'b')).toBe('b 的台词');
    });
    expect(textOf(view, 'a')).toBe('a 的台词');
  });

  it('整页重载（任务完成/每完成一集）后选中集不跳走，详情自动补拉', async () => {
    const view = renderHook(() => useAnalysisWorkspace('p1'));
    await waitFor(() => {
      expect(textOf(view, 'a')).toBe('a 的台词');
    });
    act(() => {
      view.result.current.setActiveEpisodeId('b');
    });
    await waitFor(() => {
      expect(textOf(view, 'b')).toBe('b 的台词');
    });

    episodeDetail.mockImplementation((id) => Promise.resolve(detailOf(id, `${id} 重析后的台词`)));
    await act(async () => {
      await view.result.current.reload();
    });
    await waitFor(() => {
      expect(textOf(view, 'b')).toBe('b 重析后的台词');
    });
    expect(view.result.current.activeEpisodeId).toBe('b');
  });

  it('重载前发出的详情晚到就丢：不把转完之前读到的旧数据钉回去', async () => {
    let releaseOld: (value: EpisodeDetailResult) => void = () => undefined;
    episodeDetail.mockImplementationOnce(
      () => new Promise<EpisodeDetailResult>((resolve) => { releaseOld = resolve; }),
    );
    const view = renderHook(() => useAnalysisWorkspace('p1'));
    await waitFor(() => {
      expect(episodeDetail).toHaveBeenCalledTimes(1);
    });

    episodeDetail.mockImplementation((id) => Promise.resolve(detailOf(id, `${id} 的新台词`)));
    await act(async () => {
      await view.result.current.reload();
    });
    await waitFor(() => {
      expect(textOf(view, 'a')).toBe('a 的新台词');
    });
    await act(async () => {
      releaseOld(detailOf('a', 'a 的旧台词'));
      await Promise.resolve();
    });
    expect(textOf(view, 'a')).toBe('a 的新台词');
  });

  it('未转写的集（空列表）拉一次就算拉过，不循环重拉', async () => {
    episodeDetail.mockImplementation((id) =>
      Promise.resolve({ ...detailOf(id, ''), asr_segments: [], highlights: [], conflict_scores: [] }),
    );
    const view = renderHook(() => useAnalysisWorkspace('p1'));
    await waitFor(() => {
      expect(view.result.current.results?.asr_segments?.a).toEqual([]);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(episodeDetail).toHaveBeenCalledTimes(1);
  });
});
