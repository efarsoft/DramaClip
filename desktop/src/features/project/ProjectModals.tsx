import { Button, Input, Modal } from 'antd';
import { useState } from 'react';
import type { Project } from '@dramaclip/protocol';
import { pickFolder } from '../../services/client';
import { tokens } from '../../styles/theme';

/** 建剧与重命名弹窗：从 ProjectsPage 拆出，页面文件只留编排（§8 max-lines）。 */
export function RenameModal({
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

export function CreateProjectModal({
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
