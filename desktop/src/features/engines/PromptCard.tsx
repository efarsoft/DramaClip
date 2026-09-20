/** 提示词卡片：标题/描述 + 内容预览 + 编辑/重置动作。 */
import { EditOutlined, UndoOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import type { ReactElement } from 'react';
import type { PromptInfo } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

export function PromptCard({
  info,
  onEdit,
  onReset,
}: {
  info: PromptInfo;
  onEdit: (info: PromptInfo) => void;
  onReset: (info: PromptInfo) => void;
}): ReactElement {
  return (
    <PageSection
      title={info.title}
      extra={
        <span style={{ display: 'flex', gap: tokens.spaceSm }}>
          {info.overridden && (
            <span style={{ fontSize: tokens.fontMicro, color: tokens.colorWarning, alignSelf: 'center' }}>
              已修改
            </span>
          )}
          {info.overridden && (
            <Button
              size="small"
              icon={<UndoOutlined />}
              onClick={() => {
                onReset(info);
              }}
            >
              重置
            </Button>
          )}
          <EditButton onEdit={onEdit} info={info} />
        </span>
      }
    >
      <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary, marginBottom: tokens.spaceSm }}>
        {info.description}
      </div>
      <div
        style={{
          ...mixins.cardBody(),
          fontFamily: tokens.fontFamilyMono,
          fontSize: tokens.fontMicro,
          color: tokens.textSecondary,
          whiteSpace: 'pre-wrap',
          maxHeight: 96,
          overflow: 'hidden',
          lineHeight: '18px',
        }}
      >
        {info.current}
      </div>
    </PageSection>
  );
}

function EditButton({
  onEdit,
  info,
}: {
  onEdit: (info: PromptInfo) => void;
  info: PromptInfo;
}): ReactElement {
  return (
    <Button
      size="small"
      icon={<EditOutlined />}
      onClick={() => {
        onEdit(info);
      }}
    >
      编辑
    </Button>
  );
}

/** tab 顶部使用说明。 */
export function PromptHint(): ReactElement {
  return (
    <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
      这些指令喂给出片链路里的每一次 LLM 调用。改坏了一条，点「重置」立即回代码默认；
      保存后下一次出片生效，不影响已生成的成片。
    </div>
  );
}
