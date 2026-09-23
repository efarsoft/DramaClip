// @vitest-environment jsdom
/**
 * 勾选集提升到壳级 store 的行为证明（卷二 §6.5）：
 * 离开分析页再回来（跨页导航），勾选原样还在；作业完成刷新不冲掉用户意愿。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Episode, ProjectGetResult } from '@dramaclip/protocol';
import { useDramaSelectionStore } from '../../../stores/dramaSelection';
import { useUiStore } from '../../../stores/ui';
import { useAnalysisWorkspace } from '../useAnalysisWorkspace';

const projectApiGet = vi.fn<() => Promise<ProjectGetResult>>();
const analysisResults = vi.fn<() => Promise<{ episodes: never[] }>>();
const jobsList = vi.fn<() => Promise<{ jobs: never[] }>>();

vi.mock('../../../services/client', () => ({
  projectApi: { get: () => projectApiGet() },
  analysisApi: {
    results: () => analysisResults(),
    status: vi.fn(),
  },
  jobsApi: { list: () => jobsList() },
  onServiceEvent: () => (): void => undefined,
}));

function episode(id: string, status: Episode['status']): Episode {
  return {
    id,
    episode_number: 1,
    name: id,
    source_path: `D:/x/${id}.mp4`,
    status,
  };
}

function detail(episodes: Episode[]): ProjectGetResult {
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

beforeEach(() => {
  vi.clearAllMocks();
  useDramaSelectionStore.setState({ projectId: null, episodeIds: [] });
  useUiStore.setState({ serviceState: 'ready' });
  projectApiGet.mockResolvedValue(detail([episode('a', 'pending'), episode('b', 'done')]));
  analysisResults.mockResolvedValue({ episodes: [] });
  jobsList.mockResolvedValue({ jobs: [] });
});

describe('跨页导航保勾选', () => {
  it('首进默认勾未完成集；离开再回来，勾选原样还在', async () => {
    const first = renderHook(() => useAnalysisWorkspace('p1'));
    await waitFor(() => {
      expect(first.result.current.selectedIds).toEqual(['a']);
    });

    act(() => {
      first.result.current.toggleSelected('b', true);
    });
    expect(first.result.current.selectedIds).toEqual(['a', 'b']);
    first.unmount(); // 导航去出片页

    const second = renderHook(() => useAnalysisWorkspace('p1')); // 导航回来
    await waitFor(() => {
      expect(second.result.current.episodes).toHaveLength(2);
    });
    expect(second.result.current.selectedIds).toEqual(['a', 'b']);
  });

  it('作业完成后刷新（loadAll）不冲掉用户的取消勾选', async () => {
    const view = renderHook(() => useAnalysisWorkspace('p1'));
    await waitFor(() => {
      expect(view.result.current.selectedIds).toEqual(['a']);
    });
    act(() => {
      view.result.current.toggleSelected('a', false);
    });
    // a 转写完成后的整页重载：不得把用户取消的 a 悄悄勾回来
    projectApiGet.mockResolvedValue(detail([episode('a', 'done'), episode('b', 'done')]));
    await act(async () => {
      await view.result.current.reload();
    });
    expect(view.result.current.selectedIds).toEqual([]);
  });
});
