/** 项目列表数据操作（数据获取与 CRUD 与 UI 解耦）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { projectApi } from '../../services/client';

export interface ProjectsController {
  projects: Project[] | null;
  create: (name: string, folder: string) => Promise<void>;
  remove: (project: Project) => Promise<void>;
  rename: (project: Project, name: string) => Promise<void>;
  duplicate: (project: Project) => Promise<void>;
}

export function useProjects(): ProjectsController {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [projects, setProjects] = useState<Project[] | null>(null);

  const load = useCallback(async () => {
    setProjects(await projectApi.list());
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = useCallback(
    async (name: string, folder: string) => {
      const project = await projectApi.create(name, folder);
      await projectApi.scanEpisodes(project.id);
      message.success(`已创建「${name}」`);
      await navigate(`/projects/${project.id}/analysis`);
    },
    [message, navigate],
  );

  const remove = useCallback(
    async (project: Project) => {
      await projectApi.remove(project.id);
      message.success('已删除');
      await load();
    },
    [load, message],
  );

  const rename = useCallback(
    async (project: Project, name: string) => {
      await projectApi.rename(project.id, name);
      message.success('已重命名');
      await load();
    },
    [load, message],
  );

  const duplicate = useCallback(
    async (project: Project) => {
      const copy = await projectApi.duplicate(project.id);
      message.success(`已创建副本「${copy.name}」`);
      await load();
    },
    [load, message],
  );

  return { projects, create, remove, rename, duplicate };
}
