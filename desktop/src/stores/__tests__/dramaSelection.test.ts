// @vitest-environment node
/** 壳级勾选集 store（卷二 §6.5）：跨页/重载保勾选、换剧换集、默认勾选口径、重扫对账。 */
import { beforeEach, describe, expect, it } from 'vitest';
import { syncSelectionOnEpisodes, useDramaSelectionStore } from '../dramaSelection';

function reset(): void {
  useDramaSelectionStore.setState({ projectId: null, episodeIds: [] });
}

function ep(id: string, status: string): { id: string; status: string } {
  return { id, status };
}

beforeEach(reset);

describe('toggleEpisode', () => {
  it('勾选/取消勾选，不重复加入', () => {
    const { toggleEpisode } = useDramaSelectionStore.getState();
    toggleEpisode('p1', 'e1', true);
    toggleEpisode('p1', 'e2', true);
    toggleEpisode('p1', 'e1', true);
    expect(useDramaSelectionStore.getState().episodeIds).toEqual(['e1', 'e2']);
    toggleEpisode('p1', 'e1', false);
    expect(useDramaSelectionStore.getState().episodeIds).toEqual(['e2']);
  });

  it('换剧即换勾选集：旧剧的选择对新剧没有意义', () => {
    const { toggleEpisode } = useDramaSelectionStore.getState();
    toggleEpisode('p1', 'e1', true);
    toggleEpisode('p2', 'e9', true);
    const state = useDramaSelectionStore.getState();
    expect(state.projectId).toBe('p2');
    expect(state.episodeIds).toEqual(['e9']);
  });
});

describe('syncSelectionOnEpisodes（重载对账）', () => {
  it('首进本剧：默认勾全部未完成集，done 不勾', () => {
    syncSelectionOnEpisodes('p1', [ep('a', 'pending'), ep('b', 'done'), ep('c', 'failed')]);
    expect(useDramaSelectionStore.getState().episodeIds).toEqual(['a', 'c']);
  });

  it('同剧重载：保留用户意愿（含用户取消过的 done 集不被重新勾上）', () => {
    syncSelectionOnEpisodes('p1', [ep('a', 'pending'), ep('b', 'pending')]);
    useDramaSelectionStore.getState().toggleEpisode('p1', 'a', false);
    // 作业完成后刷新：a 已 done，b 还在跑——不得把 a 悄悄勾回来
    syncSelectionOnEpisodes('p1', [ep('a', 'done'), ep('b', 'pending')]);
    expect(useDramaSelectionStore.getState().episodeIds).toEqual(['b']);
  });

  it('重扫描后 id 重建：只剔除已消失的集，存活的勾选原样保留', () => {
    syncSelectionOnEpisodes('p1', [ep('a', 'pending'), ep('b', 'pending'), ep('c', 'pending')]);
    useDramaSelectionStore.getState().toggleEpisode('p1', 'c', false);
    syncSelectionOnEpisodes('p1', [ep('a2', 'pending'), ep('b', 'pending')]);
    expect(useDramaSelectionStore.getState().episodeIds).toEqual(['b']);
  });

  it('没有集消失时不写 store（引用稳定，不触发无谓重渲染）', () => {
    syncSelectionOnEpisodes('p1', [ep('a', 'pending')]);
    const before = useDramaSelectionStore.getState().episodeIds;
    syncSelectionOnEpisodes('p1', [ep('a', 'done')]);
    expect(useDramaSelectionStore.getState().episodeIds).toBe(before);
  });
});
