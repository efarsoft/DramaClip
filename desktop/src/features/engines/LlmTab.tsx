/** LLM 引擎：OpenAI 兼容端点（云端服务或本地 Ollama/LM Studio 同协议）。 */
import { App as AntdApp, Button, Input } from 'antd';
import { PageSection } from '../../components/layout/PageKit';
import { useEffect, useState } from 'react';
import { tokens } from '../../styles/theme';
import { LlmTestButton } from './LlmTestButton';
import type { SettingsMap } from './EnginesPage';

const FIELDS = [
  { key: 'llm.base_url', label: 'API 地址', placeholder: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { key: 'llm.api_key', label: 'API Key', placeholder: 'sk-…' },
  { key: 'llm.model', label: '模型名', placeholder: 'qwen-plus' },
] as const;

/** 文案 LLM tab（草稿编辑 + 保存 + 连通性测试）。 */
export function LlmTab({
  settings,
  onSave,
}: {
  settings: SettingsMap;
  onSave: (values: SettingsMap) => Promise<void>;
}): React.ReactElement {
  const { message } = AntdApp.useApp();
  const [draft, setDraft] = useState<SettingsMap>(pickLlm(settings));

  useEffect(() => {
    setDraft(pickLlm(settings));
  }, [settings]);

  const dirty = FIELDS.some((field) => (draft[field.key] ?? '') !== (settings[field.key] ?? ''));
  const save = (): void => {
    const values = Object.fromEntries(
      FIELDS.filter((field) => (draft[field.key] ?? '') !== (settings[field.key] ?? '')).map(
        (field) => [field.key, draft[field.key] ?? ''],
      ),
    );
    if (Object.keys(values).length === 0) return;
    onSave(values).catch((error: unknown) => {
      message.error(error instanceof Error ? error.message : String(error));
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <PageSection title="云端 / 本地端点（OpenAI 兼容）">
        <div style={{ fontSize: 12.5, color: tokens.textTertiary, marginBottom: 14 }}>
          云端：填 DashScope 等兼容服务；本地：Ollama 填 http://127.0.0.1:11434/v1、LM Studio 填其服务地址。
          未配置时剧情与文案生成自动降级为关键词模式。
        </div>
        <FieldRows draft={draft} onChange={(next) => { setDraft(next); }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14 }}>
          <Button type="primary" disabled={!dirty} onClick={save}>
            保存
          </Button>
          <span style={{ fontSize: 12, color: tokens.textTertiary }}>测试连接按已保存配置执行</span>
          <span style={{ marginLeft: 'auto' }}>
            <LlmTestButton />
          </span>
        </div>
      </PageSection>
      <PageSection title="本地大模型">
        <div style={{ fontSize: 12.5, color: tokens.textTertiary }}>
          本地 LLM 引擎（如内置 Qwen 之类）规划在后续版本；当前可经 Ollama / LM Studio 的 OpenAI 兼容端点接入本地模型。
        </div>
      </PageSection>
    </div>
  );
}

function FieldRows({
  draft,
  onChange,
}: {
  draft: SettingsMap;
  onChange: (next: SettingsMap) => void;
}): React.ReactElement {
  return (
    <>
      {FIELDS.map((field) => (
        <div key={field.key} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '7px 0' }}>
          <span style={{ width: 90, flexShrink: 0, fontSize: 13, color: tokens.textSecondary }}>
            {field.label}
          </span>
          <Input
            style={{ width: 420 }}
            value={draft[field.key] ?? ''}
            placeholder={field.placeholder}
            type={field.key === 'llm.api_key' ? 'password' : 'text'}
            onChange={(event) => {
              onChange({ ...draft, [field.key]: event.target.value });
            }}
          />
        </div>
      ))}
    </>
  );
}

function pickLlm(settings: SettingsMap): SettingsMap {
  return {
    'llm.base_url': settings['llm.base_url'] ?? '',
    'llm.api_key': settings['llm.api_key'] ?? '',
    'llm.model': settings['llm.model'] ?? '',
  };
}
