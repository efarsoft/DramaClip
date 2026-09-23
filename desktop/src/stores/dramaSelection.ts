import { create } from 'zustand';

/** 单剧勾选集（壳级 store，卷二 §6.5：从分析页 useState 提出来）。
 * 提升的唯一收益 = 跨页导航（分析 ↔ 出片）与作业完成刷新后保住勾选。
 * 红线：出片取材池由服务端硬取全部已完成集，勾选集不驱动出片取材——
 * 界面文案不得假装「勾选出片」。 */
interface DramaSelectionState {
  projectId: string | null;
  episodeIds: readonly string[];
  setSelection: (projectId: string, episodeIds: readonly string[]) => void;
  toggleEpisode: (projectId: string, episodeId: string, checked: boolean) => void;
}

export const useDramaSelectionStore = create<DramaSelectionState>((set) => ({
  projectId: null,
  episodeIds: [],
  setSelection: (projectId, episodeIds) => {
    set({ projectId, episodeIds });
  },
  toggleEpisode: (projectId, episodeId, checked) => {
    set((state) => {
      // 换剧即换勾选集：旧剧的选择对新剧没有意义
      const current = state.projectId === projectId ? state.episodeIds : [];
      if (checked) {
        return {
          projectId,
          episodeIds: current.includes(episodeId) ? current : [...current, episodeId],
        };
      }
      return { projectId, episodeIds: current.filter((id) => id !== episodeId) };
    });
  },
}));

/** 重载对账：首进本剧 = 默认勾全部未完成集（保持原默认）；同剧重载 = 保留用户意愿，
 * 只剔除已消失的集（重扫描后 id 重建）。重扫新出现的集不自动勾——全选框一步到位，
 * 比悄悄替用户做决定诚实。 */
export function syncSelectionOnEpisodes(
  projectId: string,
  episodes: readonly { id: string; status: string }[],
): void {
  const state = useDramaSelectionStore.getState();
  if (state.projectId !== projectId) {
    state.setSelection(
      projectId,
      episodes.filter((episode) => episode.status !== 'done').map((episode) => episode.id),
    );
    return;
  }
  const alive = new Set(episodes.map((episode) => episode.id));
  const kept = state.episodeIds.filter((id) => alive.has(id));
  if (kept.length !== state.episodeIds.length) state.setSelection(projectId, kept);
}
