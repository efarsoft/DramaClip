/** 项目详情数据：加载 + 封面补齐（挂载触发，幂等）+ 刷新。 */
import { useCallback, useEffect, useState } from 'react';
import type { Project } from '@dramaclip/protocol';
import { projectApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';

export function useProjectDetail(projectId: string): {
  project: Project | null;
  reloadProject: () => Promise<void>;
} {
  const [project, setProject] = useState<Project | null>(null);
  const setCurrentProjectId = useUiStore((state) => state.setCurrentProjectId);

  useEffect(() => {
    setCurrentProjectId(projectId === '' ? null : projectId);
    return () => {
      setCurrentProjectId(null);
    };
  }, [projectId, setCurrentProjectId]);

  const loadProject = useCallback(async (): Promise<void> => {
    const detail = await projectApi.get(projectId);
    setProject(detail.project);
  }, [projectId]);

  useEffect(() => {
    void loadProject().catch(() => {
      setProject(null);
    });
    // 挂载即补齐缺失封面（项目 + 各集），完成后刷新一次
    void projectApi
      .ensureCovers()
      .then(loadProject)
      .catch(() => undefined);
  }, [loadProject]);

  const reloadProject = useCallback(async (): Promise<void> => {
    await loadProject();
  }, [loadProject]);

  return { project, reloadProject };
}

/** 拖拽排序落库后刷新项目信息。 */
export function useEpisodeReorder(
  projectId: string,
  reloadProject: () => Promise<void>,
): (orderedIds: string[]) => void {
  return useCallback(
    (orderedIds: string[]): void => {
      void projectApi
        .reorderEpisodes(projectId, orderedIds)
        .then(reloadProject)
        .catch(() => undefined);
    },
    [projectId, reloadProject],
  );
}
