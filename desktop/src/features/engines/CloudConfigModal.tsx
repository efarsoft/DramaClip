/** 端点配置弹窗：新增/编辑表单 + 保存前连通性测试；失败原文进内联横幅，不闪一次就消失。
 * 传 presets（按域的服务商预设）时表单顶部出预设下拉——选中即填地址与默认模型。 */
import { App as AntdApp, Alert, Button, Input, Modal, Select } from 'antd';
import { useState, type ChangeEvent, type ReactElement } from 'react';
import { engineConfigsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

export interface FormState {
  readonly name: string;
  readonly base_url: string;
  readonly api_key: string;
  readonly model: string;
}

/** 服务商预设：选中自动填 API 地址与默认模型（自定义=手填）。 */
export interface CloudPreset {
  readonly label: string;
  readonly base_url: string;
  readonly model: string;
}

const FIELDS = [
  { key: 'name', label: '名称', placeholder: '如 DashScope qwen-plus' },
  { key: 'base_url', label: 'API 地址', placeholder: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { key: 'api_key', label: 'API Key', placeholder: 'sk-…', secret: true },
  { key: 'model', label: '模型名', placeholder: 'qwen-plus' },
] as const;

/** 连通性测试：按当前草稿直测端点（保存前即可验证）；失败原因进弹窗内横幅。
 * editingId 存在时随请求带上——出参已无明文 key，编辑态草稿里 key 留空，
 * 由服务端按 id 取库中现值，否则空 key 一定测挂。 */
function useConnectionTest(draft: FormState, domain: string, editingId?: string): {
  readonly testing: boolean;
  readonly testError: string | null;
  readonly test: () => void;
} {
  const { message } = AntdApp.useApp();
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const test = (): void => {
    if (draft.model.trim() === '') {
      setTestError('先填写模型名：为空时无从测起');
      return;
    }
    setTesting(true);
    setTestError(null);
    engineConfigsApi
      .test({
        id: editingId,
        domain,
        base_url: draft.base_url.trim(),
        api_key: draft.api_key.trim(),
        model: draft.model.trim(),
      })
      .then((res) => {
        if (res.ok) {
          message.success(`连接正常 · 延迟 ${String(res.latency_s ?? 0)}s`);
          return;
        }
        setTestError(res.error ?? '端点拒绝连接，未给出原因');
      })
      .catch((error: unknown) => {
        setTestError(error instanceof Error && error.message !== '' ? error.message : '连接失败');
      })
      .finally(() => {
        setTesting(false);
      });
  };
  return { testing, testError, test };
}

export function ConfigModal({
  initial,
  saving,
  saveError,
  presets,
  domain = 'llm',
  editingId,
  onSave,
  onClose,
}: {
  initial: FormState;
  saving: boolean;
  saveError: string | null;
  /** 按域的服务商预设：不传 = 纯手填（LLM 域现状）。 */
  presets?: readonly CloudPreset[];
  domain?: string;
  /** 编辑态的建档 id：决定「测试连接」是否走服务端取密钥、密钥框留空语义。 */
  editingId?: string;
  onSave: (form: FormState) => void;
  onClose: () => void;
}): ReactElement {
  const [draft, setDraft] = useState<FormState>(initial);
  const { testing, testError, test } = useConnectionTest(draft, domain, editingId);
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
        <FailureBanners saveError={saveError} testError={testError} />
        {presets !== undefined && (
          <label style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
            <span style={{ width: 64, flexShrink: 0, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
              服务商
            </span>
            <Select
              size="small"
              style={{ flex: 1 }}
              placeholder="选预设自动填地址与默认模型"
              options={presets.map((preset) => ({ label: preset.label, value: preset.label }))}
              onChange={(label: string) => {
                const preset = presets.find((item) => item.label === label);
                if (preset === undefined) return;
                setDraft({
                  ...draft,
                  name: draft.name === '' ? preset.label : draft.name,
                  base_url: preset.base_url,
                  model: preset.model,
                });
              }}
            />
          </label>
        )}
        {FIELDS.map((spec) => (
          <LabeledInput
            key={spec.key}
            label={spec.label}
            placeholder={
              spec.key === 'api_key' && editingId !== undefined
                ? '留空即保持库中现值'
                : spec.placeholder
            }
            type={'secret' in spec ? 'password' : 'text'}
            {...field(spec.key)}
          />
        ))}
      </div>
    </Modal>
  );
}

/** 失败横幅组：常驻弹窗内直到下一次动作，各说清后果边界（卷二 P-A）。 */
function FailureBanners({
  saveError,
  testError,
}: {
  saveError: string | null;
  testError: string | null;
}): ReactElement | null {
  if (saveError === null && testError === null) return null;
  return (
    <>
      {saveError !== null && (
        <Alert
          type="error"
          showIcon
          title={`保存失败：${saveError}`}
          description="草稿仍在表单里，改完可直接再存；本次修改尚未生效。"
        />
      )}
      {testError !== null && (
        <Alert
          type="warning"
          showIcon
          title={`连接测试未通过：${testError}`}
          description="测试只验当前草稿；仍可保存，但该端点在被选中前不会产文案。"
        />
      )}
    </>
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
