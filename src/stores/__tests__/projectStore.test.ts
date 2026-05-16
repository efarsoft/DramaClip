import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useProjectStore } from '@/stores/projectStore';

// 创建 mock 项目数据
const mockProject = {
  id: 'proj-1',
  name: '测试项目',
  path: '/tmp/test-project',
  created_at: '2025-01-01T00:00:00',
  updated_at: '2025-01-01T00:00:00',
  episode_count: 2,
  status: 'idle' as const,
};

const mockVideos = [
  {
    id: 'vid-1',
    name: '测试视频1',
    path: '/tmp/test-video-1.mp4',
    duration: 120,
    size: 1024,
    format: 'mp4',
  },
  {
    id: 'vid-2',
    name: '测试视频2',
    path: '/tmp/test-video-2.mp4',
    duration: 60,
    size: 512,
    format: 'mp4',
  },
];

// Mock 整个 ipc 模块
vi.mock('@/services/ipc', () => ({
  projectApi: {
    list: vi.fn(),
    create: vi.fn(),
    open: vi.fn(),
    delete: vi.fn(),
    importVideos: vi.fn(),
    rename: vi.fn(),
    getVideos: vi.fn(),
  },
}));

import { projectApi } from '@/services/ipc';

describe('projectStore', () => {
  // 每个测试前重置 store 状态
  beforeEach(() => {
    useProjectStore.setState({
      projects: [],
      currentProject: null,
      currentVideos: [],
      selectedEpisodeIds: [],
      isLoading: false,
      error: null,
    });
    vi.clearAllMocks();
  });

  // ===== 初始状态 =====
  it('应使用默认初始状态', () => {
    const state = useProjectStore.getState();
    expect(state.projects).toEqual([]);
    expect(state.currentProject).toBeNull();
    expect(state.currentVideos).toEqual([]);
    expect(state.selectedEpisodeIds).toEqual([]);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  // ===== loadProjects =====
  it('loadProjects 应加载项目列表并清除错误', async () => {
    vi.mocked(projectApi.list).mockResolvedValue([mockProject]);

    await useProjectStore.getState().loadProjects();

    const state = useProjectStore.getState();
    expect(state.projects).toHaveLength(1);
    expect(state.projects[0]).toEqual(mockProject);
    expect(state.isLoading).toBe(false);
    expect(projectApi.list).toHaveBeenCalledOnce();
  });

  it('loadProjects 失败时应设置错误状态', async () => {
    vi.mocked(projectApi.list).mockRejectedValue(new Error('Network error'));

    await useProjectStore.getState().loadProjects();

    const state = useProjectStore.getState();
    expect(state.projects).toEqual([]);
    expect(state.error).toBe('Network error');
    expect(state.isLoading).toBe(false);
  });

  // ===== createProject =====
  it('createProject 应创建并切换到新项目', async () => {
    vi.mocked(projectApi.create).mockResolvedValue(mockProject);

    const result = await useProjectStore.getState().createProject('测试项目', '/tmp');

    expect(result).toEqual(mockProject);
    const state = useProjectStore.getState();
    expect(state.projects).toContainEqual(mockProject);
    expect(state.currentProject).toEqual(mockProject);
    expect(projectApi.create).toHaveBeenCalledWith('测试项目', '/tmp');
  });

  it('createProject 失败时应保留原有项目列表', async () => {
    useProjectStore.setState({ projects: [mockProject] });
    vi.mocked(projectApi.create).mockRejectedValue(new Error('权限不足'));

    await expect(
      useProjectStore.getState().createProject('新项目', '/tmp')
    ).rejects.toThrow('权限不足');

    const state = useProjectStore.getState();
    expect(state.projects).toHaveLength(1); // 原项目不变
    expect(state.error).toBe('权限不足');
  });

  // ===== openProject =====
  it('openProject 应加载项目及其视频', async () => {
    vi.mocked(projectApi.open).mockResolvedValue({
      ...mockProject,
      videos: mockVideos,
    });

    const result = await useProjectStore.getState().openProject('proj-1');

    expect(result).toEqual({ ...mockProject, videos: mockVideos });
    const state = useProjectStore.getState();
    expect(state.currentProject?.id).toBe('proj-1');
    expect(state.currentVideos).toEqual(mockVideos);
  });

  it('openProject 失败时应清除加载状态', async () => {
    vi.mocked(projectApi.open).mockRejectedValue(new Error('项目不存在'));

    await expect(
      useProjectStore.getState().openProject('proj-none')
    ).rejects.toThrow('项目不存在');

    const state = useProjectStore.getState();
    expect(state.isLoading).toBe(false);
    expect(state.currentProject).toBeNull();
  });

  // ===== deleteProject =====
  it('deleteProject 应从列表移除项目', async () => {
    useProjectStore.setState({
      projects: [mockProject, { ...mockProject, id: 'proj-2', name: '项目2' }],
      currentProject: mockProject,
    });
    vi.mocked(projectApi.delete).mockResolvedValue({ success: true });

    await useProjectStore.getState().deleteProject('proj-1');

    const state = useProjectStore.getState();
    expect(state.projects).toHaveLength(1);
    expect(state.projects[0].id).toBe('proj-2');
    expect(state.currentProject).toBeNull();
    expect(projectApi.delete).toHaveBeenCalledWith('proj-1', false);
  });

  it('deleteProject 删除文件时应传递 keepFiles=true', async () => {
    useProjectStore.setState({ projects: [mockProject] });
    vi.mocked(projectApi.delete).mockResolvedValue({ success: true });

    await useProjectStore.getState().deleteProject('proj-1', true);

    expect(projectApi.delete).toHaveBeenCalledWith('proj-1', true);
  });

  it('deleteProject 失败时应抛出错误', async () => {
    useProjectStore.setState({ projects: [mockProject] });
    vi.mocked(projectApi.delete).mockRejectedValue(new Error('删除失败'));

    await expect(
      useProjectStore.getState().deleteProject('proj-1')
    ).rejects.toThrow('删除失败');

    // 项目列表应保持不变
    const state = useProjectStore.getState();
    expect(state.projects).toHaveLength(1);
  });

  // ===== importVideos =====
  it('importVideos 应追加视频并更新计数', async () => {
    useProjectStore.setState({
      currentProject: mockProject,
      currentVideos: [mockVideos[0]],
    });
    vi.mocked(projectApi.importVideos).mockResolvedValue([mockVideos[1]]);

    await useProjectStore.getState().importVideos('proj-1', ['/new-video.mp4']);

    const state = useProjectStore.getState();
    expect(state.currentVideos).toHaveLength(2);
    expect(state.currentProject?.episode_count).toBe(2);
  });

  // ===== renameProject =====
  it('renameProject 应更新项目名称', async () => {
    useProjectStore.setState({
      projects: [mockProject],
      currentProject: mockProject,
    });
    const renamed = { ...mockProject, name: '重命名项目' };
    vi.mocked(projectApi.rename).mockResolvedValue(renamed);

    await useProjectStore.getState().renameProject('proj-1', '重命名项目');

    const state = useProjectStore.getState();
    expect(state.projects[0].name).toBe('重命名项目');
    expect(state.currentProject?.name).toBe('重命名项目');
  });

  // ===== loadProjectVideos =====
  it('loadProjectVideos 应刷新视频列表并正确处理 isLoading 状态', async () => {
    vi.mocked(projectApi.getVideos).mockResolvedValue(mockVideos);
    const { loadProjectVideos } = useProjectStore.getState();

    const pendingPromise = loadProjectVideos('proj-1');

    // 异步调用期间 isLoading 应为 true
    expect(useProjectStore.getState().isLoading).toBe(true);

    await pendingPromise;

    const state = useProjectStore.getState();
    expect(state.isLoading).toBe(false);
    expect(state.currentVideos).toEqual(mockVideos);
    expect(projectApi.getVideos).toHaveBeenCalledWith('proj-1');
  });

  it('loadProjectVideos 失败时应重置 isLoading 并抛出错误', async () => {
    vi.mocked(projectApi.getVideos).mockRejectedValue(new Error('获取视频失败'));

    await expect(
      useProjectStore.getState().loadProjectVideos('proj-1')
    ).rejects.toThrow('获取视频失败');

    const state = useProjectStore.getState();
    expect(state.isLoading).toBe(false);
  });

  // ===== sync actions =====

  // ===== sync actions =====
  it('setSelectedEpisodeIds 应更新选中列表', () => {
    useProjectStore.getState().setSelectedEpisodeIds(['vid-1', 'vid-2']);
    expect(useProjectStore.getState().selectedEpisodeIds).toEqual(['vid-1', 'vid-2']);
  });

  it('setCurrentProject 应清空视频列表', () => {
    useProjectStore.setState({ currentVideos: mockVideos });
    useProjectStore.getState().setCurrentProject(null);
    const state = useProjectStore.getState();
    expect(state.currentProject).toBeNull();
    expect(state.currentVideos).toEqual([]);
  });

  it('clearError 应清除错误', () => {
    useProjectStore.setState({ error: '出错了' });
    useProjectStore.getState().clearError();
    expect(useProjectStore.getState().error).toBeNull();
  });
});
