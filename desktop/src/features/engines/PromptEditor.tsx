/** 提示词编辑弹窗：textarea 编辑 + 填回默认（保存动作由父级执行）。 */
import { UndoOutlined } from '@ant-design/icons';
import { Button, Input, Modal } from 'antd';
import type { ReactElement } from 'react';
import type { PromptInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

export function PromptEditor({
  editing,
  draft,
  saving,
  onDraft,
  onSave,
  onClose,
}: {
  editing: PromptInfo | null;
  draft: string;
  saving: boolean;
  onDraft: (text: string) => void;
  onSave: () => void;
  onClose: () => void;
}): ReactElement {
  return (
    <Modal
      title={`编辑 · ${editing?.title ?? ''}`}
      open={editing !== null}
      width={720}
      okText="保存"
      cancelText="取消"
      okButtonProps={{ disabled: editing !== null && draft === editing.current }}
      confirmLoading={saving}
      onOk={onSave}
      onCancel={onClose}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
        <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
          {editing?.description ?? ''}
        </div>
        <Input.TextArea
          value={draft}
          onChange={(event) => {
            onDraft(event.target.value);
          }}
          rows={16}
          style={{ fontFamily: tokens.fontFamilyMono, fontSize: tokens.fontCaption }}
        />
        <Button
          icon={<UndoOutlined />}
          onClick={() => {
            onDraft(editing?.default ?? '');
          }}
        >
          填回默认内容
        </Button>
      </div>
    </Modal>
  );
}
