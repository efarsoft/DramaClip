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
  const serviceState = useUiStore((state) => state.serviceState);

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

  // 服务就绪前 ensureCovers/get 会失败；ready 后再执行一次
  useEffect(() => {
    if (serviceState !== 'ready') return;
    void loadProject().catch(() => undefined);
    void projectApi
      .ensureCovers()
      .then(loadProject)
      .catch(() => undefined);
  }, [loadProject, serviceState]);

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
