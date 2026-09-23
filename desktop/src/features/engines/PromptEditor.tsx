/** 提示词编辑弹窗：textarea 编辑 + 填回默认（保存动作由父级执行，失败原文进内联横幅）。 */
import { UndoOutlined } from '@ant-design/icons';
import { Alert, Button, Input, Modal } from 'antd';
import type { ReactElement } from 'react';
import type { PromptInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

export function PromptEditor({
  editing,
  draft,
  saving,
  saveError,
  onDraft,
  onSave,
  onClose,
}: {
  editing: PromptInfo | null;
  draft: string;
  saving: boolean;
  saveError: string | null;
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
        <SaveFailureBanner saveError={saveError} />
        <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          {editing?.description ?? ''}
        </div>
        <Input.TextArea
          value={draft}
          onChange={(event) => {
            onDraft(event.target.value);
          }}
          rows={16}
          style={{ fontFamily: tokens.fontFamilyMono, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading }}
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

/** 保存失败横幅：原文常驻到下一次动作，草稿不丢的后果说在原地（卷二 P-A）。 */
function SaveFailureBanner({ saveError }: { saveError: string | null }): ReactElement | null {
  if (saveError === null) return null;
  return (
    <Alert
      type="error"
      showIcon
      title={`保存失败：${saveError}`}
      description="草稿仍在编辑框里，重试不会丢内容；本次修改尚未生效。"
    />
  );
}
