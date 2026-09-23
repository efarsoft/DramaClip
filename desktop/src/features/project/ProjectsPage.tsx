import { App as AntdApp, Button } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { dramaEntryPath } from '../../app/routes';
import { rememberDrama } from '../../stores/lastDrama';
import { projectApi } from '../../services/client';
import { PageHeader, PageShell } from '../../components/layout/PageKit';
import { FolderAddOutlined } from '@ant-design/icons';
import { LibraryGrid } from './LibraryGrid';
import { CreateProjectModal, RenameModal } from './ProjectModals';
import { useLibraryFacts } from './useLibraryFacts';
import { useProjects, type ProjectsController } from './useProjects';

/** 项目管理页（docs/desktop/03 §7.2 + 卷三图 2）：五要素剧卡 + 聚合筛选/搜索/排序 + 首启三步。 */
type AppModal = ReturnType<typeof AntdApp.useApp>['modal'];

function confirmDeleteProject(modal: AppModal, project: Project, remove: () => Promise<void>): void {
  modal.confirm({
    title: `删除项目「${project.name}」？`,
    content: '将删除项目与分析记录（不删除源视频文件），操作不可撤销。',
    okButtonProps: { danger: true },
    okText: '删除',
    onOk: remove,
  });
}

/** 挂载时补拍一次封面；失败要说出现象与后果，不静默吞（附录 A 行 2 的另一半）。 */
function useCoverBackfill(reload: () => Promise<void>, warn: (text: string) => void): void {
  useEffect(() => {
    void projectApi
      .ensureCovers()
      .then(() => reload())
      .catch(() => {
        warn('部分封面补拍未完成：列表照常可用，缺封面项显示占位图');
      });
    // 仅挂载时补一次封面
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

/** 重命名流：目标剧 + 开/关/提交三动作收拢，页面函数只剩编排。 */
function useRenameFlow(controller: ProjectsController): {
  target: Project | null;
  open: (project: Project) => void;
  close: () => void;
  submit: (name: string) => void;
} {
  const [target, setTarget] = useState<Project | null>(null);
  return {
    target,
    open: setTarget,
    close: () => {
      setTarget(null);
    },
    submit: (name) => {
      if (target !== null) void controller.rename(target, name);
      setTarget(null);
    },
  };
}

export function ProjectsPage() {
  const navigate = useNavigate();
  const { modal, message } = AntdApp.useApp();
  const controller = useProjects();
  const facts = useLibraryFacts();
  const [createOpen, setCreateOpen] = useState(false);
  const rename = useRenameFlow(controller);
  // message.warning 返回 thenable，直接当 (text)=>void 传会被 lint 判成误用 Promise——包一层
  useCoverBackfill(controller.reload, (text) => {
    message.warning(text);
  });

  const openCreate = (): void => {
    setCreateOpen(true);
  };
  const gotoDrama = (route: string, project: Project): void => {
    rememberDrama(project.id, project.name);
    void navigate(route);
  };
  // 空态下 primary 归 FirstRunEmpty——DSS §3.1 每屏至多 1 个 primary
  const isEmpty = controller.projects !== null && controller.projects.length === 0;

  return (
    <PageShell>
      <PageHeader
        title="项目管理"
        desc="素材已在本地：选文件夹建剧，分析完成后进入出片"
        actions={
          isEmpty ? undefined : (
            <Button type="primary" icon={<FolderAddOutlined />} onClick={openCreate}>
              新建项目
            </Button>
          )
        }
      />
      <LibraryGrid
        projects={controller.projects}
        loadError={controller.loadError}
        facts={facts}
        onRetry={() => { void controller.reload(); }}
        onRetryFacts={() => { void facts.reload(); }}
        onOpen={(project) => { gotoDrama(dramaEntryPath(project.id), project); }}
        onGoto={gotoDrama}
        onRename={rename.open}
        onDuplicate={(project) => { void controller.duplicate(project); }}
        onDelete={(project) => { confirmDeleteProject(modal, project, () => controller.remove(project)); }}
        onCreate={openCreate}
      />
      <CreateProjectModal
        open={createOpen}
        onClose={() => { setCreateOpen(false); }}
        onCreate={controller.create}
      />
      <RenameModal target={rename.target} onClose={rename.close} onRename={rename.submit} />
    </PageShell>
  );
}
