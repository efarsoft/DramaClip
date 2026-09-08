import { App as AntdApp, Button, Card, Input, Modal } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { pickFolder, projectApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { useProjects } from './useProjects';
import { ProjectCard } from './ProjectCard';
import { useEffect } from 'react';

/** 项目管理页（docs/desktop/03 §7.2）：卡片网格 + 新建 + 重命名/复制/删除。 */
export function ProjectsPage() {
  const navigate = useNavigate();
  const { modal } = AntdApp.useApp();
  const controller = useProjects();
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    void projectApi.ensureCovers().then(() => controller.reload()).catch(() => undefined);
    // 仅挂载时补一次封面
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [renameTarget, setRenameTarget] = useState<Project | null>(null);

  const confirmDelete = (project: Project) => {
    modal.confirm({
      title: `删除项目「${project.name}」？`,
      content: '将删除项目与分析记录（不删除源视频文件），操作不可撤销。',
      okButtonProps: { danger: true },
      okText: '删除',
      onOk: async () => {
        await controller.remove(project);
      },
    });
  };

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        onOpenCreate={() => {
          setCreateOpen(true);
        }}
      />
      <ProjectGrid
        projects={controller.projects}
        onOpen={(project) => {
          void navigate(`/projects/${project.id}/analysis`);
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
    </div>
  );
}

function PageHeader({ onOpenCreate }: { onOpenCreate: () => void }) {
  return (
    <header style={{ display: 'flex', alignItems: 'center', marginBottom: 20 }}>
      <h1 style={{ margin: 0, fontSize: 20, color: tokens.textPrimary }}>项目管理</h1>
      <Button
        type="primary"
        style={{ marginLeft: 'auto' }}
        onClick={onOpenCreate}
      >
        新建项目
      </Button>
    </header>
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
  onOpen,
  onRename,
  onDuplicate,
  onDelete,
}: {
  projects: Project[] | null;
  onOpen: (project: Project) => void;
  onRename: (project: Project) => void;
  onDuplicate: (project: Project) => void;
  onDelete: (project: Project) => void;
}) {
  if (projects === null) return <Card loading />;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(236px, 1fr))', gap: 16 }}>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={{ fontSize: 13, color: tokens.textSecondary }}>项目名称</span>
        <Input
          value={name}
          onChange={(event) => {
            onName(event.target.value);
          }}
          placeholder="如：复仇千金"
        />
      </label>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={{ fontSize: 13, color: tokens.textSecondary }}>剧集文件夹</span>
        <div style={{ display: 'flex', gap: 8 }}>
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
