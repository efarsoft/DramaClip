import { App as AntdApp, Alert, Button, Card, Input, Modal } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { dramaEntryPath } from '../../app/routes';
import { rememberDrama } from '../../stores/lastDrama';
import { pickFolder, projectApi } from '../../services/client';
import { PageHeader, PageShell } from '../../components/layout/PageKit';
import { FolderAddOutlined } from '@ant-design/icons';
import { tokens } from '../../styles/theme';
import { useProjects } from './useProjects';
import { ProjectCard } from './ProjectCard';
import { useEffect } from 'react';

/** 项目管理页（docs/desktop/03 §7.2）：卡片网格 + 新建 + 重命名/复制/删除。 */
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

export function ProjectsPage() {
  const navigate = useNavigate();
  const { modal, message } = AntdApp.useApp();
  const controller = useProjects();
  const [createOpen, setCreateOpen] = useState(false);
  // message.warning 返回 thenable，直接当 (text)=>void 传会被 lint 判成误用 Promise——包一层
  useCoverBackfill(controller.reload, (text) => {
    message.warning(text);
  });
  const [renameTarget, setRenameTarget] = useState<Project | null>(null);

  const confirmDelete = (project: Project): void => {
    confirmDeleteProject(modal, project, () => controller.remove(project));
  };

  return (
    <PageShell>
      <PageHeader
        title="项目管理"
        desc="素材已在本地：选文件夹建剧，分析完成后进入出片"
        actions={
          <Button type="primary" icon={<FolderAddOutlined />} onClick={() => { setCreateOpen(true); }}>
            新建项目
          </Button>
        }
      />
      <ProjectGrid
        projects={controller.projects}
        loadError={controller.loadError}
        onRetry={() => {
          void controller.reload();
        }}
        onOpen={(project) => {
          rememberDrama(project.id, project.name);
          void navigate(dramaEntryPath(project.id));
        }}
        onRename={setRenameTarget}
        onDuplicate={(project) => {
          void controller.duplicate(project);
        }}
        onDelete={confirmDelete}
      />

      <CreateProjectModal
        open={createOpen}
        onClose={() => {
          setCreateOpen(false);
        }}
        onCreate={controller.create}
      />

      <RenameModal
        target={renameTarget}
        onClose={() => {
          setRenameTarget(null);
        }}
        onRename={(name) => {
          if (renameTarget !== null) void controller.rename(renameTarget, name);
          setRenameTarget(null);
        }}
      />
    </PageShell>
  );
}



function RenameModal({
  target,
  onClose,
  onRename,
}: {
  target: Project | null;
  onClose: () => void;
  onRename: (name: string) => void;
}) {
  const [name, setName] = useState('');
  const initial = target?.name ?? '';
  return (
    <Modal
      title="重命名项目"
      open={target !== null}
      okButtonProps={{ disabled: name.trim() === '' }}
      onOk={() => { onRename(name.trim()); }}
      onCancel={onClose}
      afterOpenChange={(opened) => {
        if (opened) setName(initial);
      }}
    >
      <Input
        value={name}
        onChange={(event) => {
          setName(event.target.value);
        }}
      />
    </Modal>
  );
}

function ProjectGrid({
  projects,
  loadError,
  onRetry,
  onOpen,
  onRename,
  onDuplicate,
  onDelete,
}: {
  projects: Project[] | null;
  loadError: string | null;
  onRetry: () => void;
  onOpen: (project: Project) => void;
  onRename: (project: Project) => void;
  onDuplicate: (project: Project) => void;
  onDelete: (project: Project) => void;
}) {
  // 失败态优先于一切：原文上屏 + 真重试按钮。已有旧数据时横幅压顶、网格保留（数据旧但可看）。
  const banner =
    loadError !== null ? (
      <Alert
        type="error"
        showIcon
        style={{ marginBottom: tokens.spaceLg }}
        title={`项目列表加载失败：${loadError}`}
        description={projects === null ? '取到列表之前这里无法渲染；重试会重新拉取。' : '显示的是上一次取到的列表，可能已过期；重试会重新拉取。'}
        action={
          <Button size="small" danger onClick={onRetry}>
            重试
          </Button>
        }
      />
    ) : undefined;
  if (projects === null) {
    return loadError !== null ? <div>{banner}</div> : <Card loading />;
  }
  return (
    <div>
      {banner}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(236px, 1fr))', gap: tokens.spaceLg }}>
        {projects.map((project) => (
          <ProjectCard
            key={project.id}
            project={project}
            onOpen={onOpen}
            onRename={onRename}
            onDuplicate={onDuplicate}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  );
}

function CreateProjectForm({
  name,
  folder,
  onName,
  onPick,
}: {
  name: string;
  folder: string;
  onName: (value: string) => void;
  onPick: () => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <label style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textSecondary }}>项目名称</span>
        <Input
          value={name}
          onChange={(event) => {
            onName(event.target.value);
          }}
          placeholder="如：复仇千金"
        />
      </label>
      <label style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textSecondary }}>剧集文件夹</span>
        <div style={{ display: 'flex', gap: tokens.spaceSm }}>
          <Input value={folder} readOnly placeholder="选择包含视频文件的文件夹" />
          <Button onClick={onPick}>选择文件夹</Button>
        </div>
      </label>
    </div>
  );
}

function CreateProjectModal({
  open,
  onClose,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (name: string, folder: string) => Promise<void>;
}) {
  const [name, setName] = useState('');
  const [folder, setFolder] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const onPick = async () => {
    const picked = await pickFolder();
    if (picked !== null) {
      setFolder(picked);
      if (name.trim() === '') {
        setName(picked.replaceAll('\\', '/').split('/').pop() ?? '');
      }
    }
  };

  const onSubmit = async () => {
    setSubmitting(true);
    try {
      await onCreate(name.trim(), folder);
      setName('');
      setFolder('');
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="新建项目"
      open={open}
      onOk={() => void onSubmit()}
      okText="创建并扫描"
      okButtonProps={{ disabled: name.trim() === '' || folder === '', loading: submitting }}
      onCancel={onClose}
    >
      <CreateProjectForm
        name={name}
        folder={folder}
        onName={setName}
        onPick={() => void onPick()}
      />
    </Modal>
  );
}
