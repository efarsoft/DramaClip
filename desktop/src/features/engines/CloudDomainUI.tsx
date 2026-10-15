/**
 * 云端配置段（ASR/TTS/VL 三域共用）：配置列表 + 单启用 + 测连接 + 添加/编辑弹层。
 * 心智与文案 LLM 域的多端点配置同构——本地是固定模型清单，云端是多样化配置。
 * 生效语义：启用某条配置即镜像写设置键（服务端），切回本地由生效卡下拉的本地分支清启用。
 */
import { App as AntdApp, Alert, Button, Segmented, Select } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useState, type ReactElement } from 'react';
import type { EngineConfig } from '@dramaclip/protocol';
import { engineConfigsApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { ConfigModal, type CloudPreset, type FormState } from './CloudConfigModal';
import type { EngineConfigActions } from './useEngineConfigs';

/** 按域的服务商预设：选中即填接口地址与默认模型；自定义=手填。 */
export const CLOUD_PRESETS: Record<string, readonly CloudPreset[]> = {
  asr_cloud: [
    { label: '阿里百炼 Qwen-Audio 3.1 ASR（默认·说话人分离）', base_url: 'https://dashscope.aliyuncs.com', model: 'qwen-audio-3.1-asr-flash' },
    { label: '阿里百炼 Fun-ASR Flash（方言强）', base_url: 'https://dashscope.aliyuncs.com', model: 'fun-asr-flash-2026-06-15' },
    { label: '自定义', base_url: '', model: '' },
  ],
  tts_cloud: [
    { label: '阿里百炼 CosyVoice v3 Flash（新代·情感与方言）', base_url: 'https://dashscope.aliyuncs.com', model: 'cosyvoice-v3-flash' },
    { label: '阿里百炼 CosyVoice v2（稳定）', base_url: 'https://dashscope.aliyuncs.com', model: 'cosyvoice-v2' },
    { label: '阿里百炼 Qwen-Audio TTS Flash（新代）', base_url: 'https://dashscope.aliyuncs.com', model: 'qwen-audio-3.0-tts-flash' },
    { label: '自定义', base_url: '', model: '' },
  ],
  image: [
    { label: '阿里百炼 qwen3.8-max（旗舰）', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen3.8-max' },
    { label: '阿里百炼 qwen3.8-flash（轻量）', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen3.8-flash' },
    { label: '阿里百炼 qwen3-vl-plus（旧版）', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen3-vl-plus' },
    { label: '自定义', base_url: '', model: '' },
  ],
};

/** 域 tab → engine_configs 的 domain 名。 */
export function cloudDomainOf(tab: 'asr' | 'tts' | 'vision'): string {
  if (tab === 'asr') return 'asr_cloud';
  if (tab === 'tts') return 'tts_cloud';
  return 'image';
}

const EMPTY_FORM: FormState = { name: '', base_url: '', api_key: '', model: '' };

interface TestState {
  readonly ok: boolean;
  readonly text: string;
}

/** 生效下拉的云端分支判定：该域启用中的配置（存在即云端生效）。 */
export function activeCloudConfig(configs: readonly EngineConfig[]): EngineConfig | undefined {
  return configs.find((config) => config.enabled === 1);
}

/** 生效卡「测连接」按钮（云端生效时替换「校验资产」位）。 */
export function CloudTestButton({ config, domain }: { config: EngineConfig; domain: string }): ReactElement {
  const { message } = AntdApp.useApp();
  const [testing, setTesting] = useState(false);
  const onTest = (): void => {
    setTesting(true);
    engineConfigsApi
      .test({ domain, base_url: config.base_url, api_key: config.api_key, model: config.model })
      .then((res) => {
        if (res.ok) message.success(`连接正常 · ${String(res.latency_s ?? 0)}s`);
        else message.error(res.error ?? '连接失败');
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : '连接失败');
      })
      .finally(() => {
        setTesting(false);
      });
  };
  return (
    <Button size="small" loading={testing} onClick={onTest}>
      测连接
    </Button>
  );
}

/** 生效分段：「本地模型 | 云端配置」（受控值由域 Tab 持有）。 */
export function CloudSegment({
  value,
  onChange,
}: {
  value: 'local' | 'cloud';
  onChange: (next: 'local' | 'cloud') => void;
}): ReactElement {
  return (
    <Segmented
      size="small"
      value={value}
      onChange={(next) => {
        onChange(next as 'local' | 'cloud');
      }}
      options={[
        { label: '本地模型', value: 'local' },
        { label: '云端配置', value: 'cloud' },
      ]}
    />
  );
}

const CLOUD_PREFIX = 'cloud:';

/** 生效下拉：本地模型 + 云端配置两组混排——切换引擎的一只手（两只分支互斥）。 */
export function MixedEnginePicker({
  width = 200,
  localOptions,
  localValue,
  configs,
  onPickLocal,
  onPickCloud,
}: {
  width?: number;
  /** 本地分支：现有 ModelPicker 的 options（label/value 已带禁用态）。 */
  localOptions: readonly { label: string; value: string; disabled?: boolean }[];
  localValue: string | undefined;
  configs: readonly EngineConfig[];
  onPickLocal: (value: string) => void;
  onPickCloud: (config: EngineConfig) => void;
}): ReactElement {
  const cloudValue = activeCloudConfig(configs);
  const value =
    cloudValue !== undefined ? `${CLOUD_PREFIX}${cloudValue.id}` : (localValue ?? undefined);
  return (
    <Select
      size="small"
      style={{ width }}
      value={value}
      placeholder="更换引擎"
      onChange={(next: string) => {
        if (next.startsWith(CLOUD_PREFIX)) {
          const picked = configs.find((config) => config.id === next.slice(CLOUD_PREFIX.length));
          if (picked !== undefined) onPickCloud(picked);
          return;
        }
        onPickLocal(next);
      }}
      options={[
        {
          label: '本地模型',
          options: localOptions.map((option) => ({ ...option })),
        },
        {
          label: '云端配置',
          options: configs.map((config) => ({
            label: `云端 · ${config.name}`,
            value: `${CLOUD_PREFIX}${config.id}`,
          })),
        },
      ]}
    />
  );
}

/** 云端配置段内容：三条动作（启用/测连接/删除）+ 编辑 + 添加（预设弹层）。 */
export function CloudConfigsPane({
  domain,
  actions,
  onChanged,
  note,
}: {
  domain: string;
  actions: EngineConfigActions;
  onChanged?: () => void;
  note: string;
}): ReactElement {
  const [tests, setTests] = useState<Readonly<Record<string, TestState>>>({});
  const presets = CLOUD_PRESETS[domain];
  const onTest = (config: EngineConfig): void => {
    setTests((prev) => ({ ...prev, [config.id]: { ok: true, text: '测试中…' } }));
    engineConfigsApi
      .test({ domain, base_url: config.base_url, api_key: config.api_key, model: config.model })
      .then((res) => {
        setTests((prev) => ({
          ...prev,
          [config.id]: res.ok
            ? { ok: true, text: `连通正常 · ${String(res.latency_s ?? 0)}s` }
            : { ok: false, text: res.error ?? '连接失败' },
        }));
      })
      .catch((error: unknown) => {
        setTests((prev) => ({
          ...prev,
          [config.id]: { ok: false, text: error instanceof Error ? error.message : '连接失败' },
        }));
      });
  };
  const onEnable = (config: EngineConfig): void => {
    actions.enable(config);
    onChanged?.();
  };
  return (
    <div>
      {actions.configs.length === 0 && (
        <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary, marginBottom: tokens.spaceMd }}>
          还没有云端配置——点下方「添加配置」，选服务商预设、填 API Key 即可接入。
        </div>
      )}
      {actions.configs.map((config) => (
        <ConfigRow
          key={config.id}
          config={config}
          test={tests[config.id]}
          onEnable={onEnable}
          onTest={onTest}
          onEdit={actions.openEdit}
          onRemove={actions.remove}
        />
      ))}
      <Button
        block
        type="dashed"
        icon={<PlusOutlined />}
        onClick={actions.openAdd}
        style={{ marginTop: tokens.spaceSm }}
      >
        添加配置（服务商 / 接口地址 / 密钥 / 模型）
      </Button>
      <Alert
        type="info"
        showIcon
        title={note}
        style={{ marginTop: tokens.spaceMd }}
      />
      {(actions.adding || actions.editing !== null) && (
        <ConfigModal
          initial={actions.editing?.form ?? EMPTY_FORM}
          saving={actions.saving}
          saveError={actions.saveError}
          presets={presets}
          domain={domain}
          onSave={actions.save}
          onClose={actions.close}
        />
      )}
    </div>
  );
}

/** 配置条目：名称/端点 meta/测连接结果 + 四个动作（启用/测连接/编辑/删除）。 */
function ConfigRow({
  config,
  test,
  onEnable,
  onTest,
  onEdit,
  onRemove,
}: {
  config: EngineConfig;
  test: TestState | undefined;
  onEnable: (config: EngineConfig) => void;
  onTest: (config: EngineConfig) => void;
  onEdit: (config: EngineConfig) => void;
  onRemove: (config: EngineConfig) => void;
}): ReactElement {
  const active = config.enabled === 1;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
        borderRadius: tokens.radiusControl,
        border: `1px solid ${active ? tokens.colorPrimary : tokens.borderSecondary}`,
        background: active ? tokens.accentSoft : tokens.bgLayout,
        marginBottom: tokens.spaceSm,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, fontWeight: 600, color: tokens.textPrimary }}>
          {config.name}
          {active && (
            <span style={{ marginLeft: tokens.spaceSm, fontSize: tokens.text.badge.size, color: tokens.colorInfo }}>
              使用中
            </span>
          )}
        </div>
        <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
          {config.model} · {config.base_url === '' ? '服务商标准端点' : config.base_url}
          {config.api_key !== '' && ` · ${config.api_key_masked}`}
        </div>
        {test !== undefined && (
          <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: test.ok ? tokens.colorSuccess : tokens.colorWarning }}>
            {test.text}
          </div>
        )}
      </div>
      <Button
        size="small"
        type={active ? 'default' : 'primary'}
        disabled={active}
        onClick={() => {
          onEnable(config);
        }}
      >
        {active ? '使用中' : '启用'}
      </Button>
      <Button
        size="small"
        onClick={() => {
          onTest(config);
        }}
      >
        测连接
      </Button>
      <Button
        size="small"
        icon={<EditOutlined />}
        onClick={() => {
          onEdit(config);
        }}
      />
      <Button
        size="small"
        icon={<DeleteOutlined />}
        danger
        onClick={() => {
          onRemove(config);
        }}
      />
    </div>
  );
}
