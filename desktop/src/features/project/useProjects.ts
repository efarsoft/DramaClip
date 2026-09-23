/** 项目列表数据操作（数据获取与 CRUD 与 UI 解耦）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { projectApi } from '../../services/client';

export interface ProjectsController {
  projects: Project[] | null;
  /** 列表加载失败的原因原文；null = 没失败过。页面据此渲染失败态而不是永久转圈。 */
  loadError: string | null;
  reload: () => Promise<void>;
  create: (name: string, folder: string) => Promise<void>;
  remove: (project: Project) => Promise<void>;
  rename: (project: Project, name: string) => Promise<void>;
  duplicate: (project: Project) => Promise<void>;
}

export function useProjects(): ProjectsController {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    // 请求失败必须留痕：不接这个 catch 就是未处理 rejection，projects 永远停在
    // null，页面把「取不到」渲染成「一直在取」（附录 A 行 2 的永久转圈根因）。
    try {
      setProjects(await projectApi.list());
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error && error.message !== '' ? error.message : String(error));
    }
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

  const reload = useCallback(async () => {
    await load();
  }, [load]);

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

  return { projects, loadError, reload, create, remove, rename, duplicate };
}
