/** 端点配置弹窗：新增/编辑表单 + 保存前连通性测试。 */
import { App as AntdApp, Button, Input, Modal } from 'antd';
import { useState, type ChangeEvent, type ReactElement } from 'react';
import { engineConfigsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

export interface FormState {
  readonly name: string;
  readonly base_url: string;
  readonly api_key: string;
  readonly model: string;
}

const FIELDS = [
  { key: 'name', label: '名称', placeholder: '如 DashScope qwen-plus' },
  { key: 'base_url', label: 'API 地址', placeholder: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { key: 'api_key', label: 'API Key', placeholder: 'sk-…', secret: true },
  { key: 'model', label: '模型名', placeholder: 'qwen-plus' },
] as const;

/** 连通性测试：按当前草稿直测端点（保存前即可验证）。 */
function useConnectionTest(draft: FormState): { readonly testing: boolean; readonly test: () => void } {
  const { message } = AntdApp.useApp();
  const [testing, setTesting] = useState(false);
  const test = (): void => {
    if (draft.base_url.trim() === '' || draft.model.trim() === '') {
      message.warning('先填写 API 地址与模型名');
      return;
    }
    setTesting(true);
    engineConfigsApi
      .test({
        base_url: draft.base_url.trim(),
        api_key: draft.api_key.trim(),
        model: draft.model.trim(),
      })
      .then((res) => {
        if (res.ok) message.success(`连接正常 · 延迟 ${String(res.latency_s ?? 0)}s`);
        else message.error(res.error ?? '连接失败');
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error && error.message !== '' ? error.message : '连接失败');
      })
      .finally(() => {
        setTesting(false);
      });
  };
  return { testing, test };
}

export function ConfigModal({
  initial,
  saving,
  onSave,
  onClose,
}: {
  initial: FormState;
  saving: boolean;
  onSave: (form: FormState) => void;
  onClose: () => void;
}): ReactElement {
  const [draft, setDraft] = useState<FormState>(initial);
  const { testing, test } = useConnectionTest(draft);
  const field = (key: keyof FormState) => ({
    value: draft[key],
    onChange: (event: ChangeEvent<HTMLInputElement>) => {
      setDraft({ ...draft, [key]: event.target.value });
    },
  });
  return (
    <Modal
      title="端点配置（OpenAI 兼容）"
      open
      onCancel={onClose}
      footer={[
        <Button key="test" loading={testing} onClick={test}>
          测试连接
        </Button>,
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="save" type="primary" loading={saving} onClick={() => { onSave(draft); }}>
          保存
        </Button>,
      ]}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd, paddingTop: tokens.spaceSm }}>
        {FIELDS.map((spec) => (
          <LabeledInput
            key={spec.key}
            label={spec.label}
            placeholder={spec.placeholder}
            type={'secret' in spec ? 'password' : 'text'}
            {...field(spec.key)}
          />
        ))}
      </div>
    </Modal>
  );
}

function LabeledInput({
  label,
  type = 'text',
  value,
  onChange,
  placeholder,
}: {
  label: string;
  type?: 'text' | 'password';
  value: string;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  placeholder: string;
}): ReactElement {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
      <span style={{ width: 64, flexShrink: 0, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
        {label}
      </span>
      <Input size="small" type={type} value={value} onChange={onChange} placeholder={placeholder} />
    </label>
  );
}
