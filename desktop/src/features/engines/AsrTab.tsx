/** ASR 引擎：识别参数（即改即存）+ 本地模型库（推荐 / 档位 / 搜索）。 */
import { Select } from 'antd';
import { PageSection } from '../../components/layout/PageKit';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { ModelBrowser } from './ModelBrowser';
import type { SettingsMap } from './EnginesPage';

const OPTIONS: Record<string, { label: string; options: { label: string; value: string }[] }> = {
  'asr.model': {
    label: '默认模型',
    options: [
      { label: 'base · 最快', value: 'base' },
      { label: 'small · 均衡（推荐）', value: 'small' },
      { label: 'medium · 高精度', value: 'medium' },
      { label: 'large-v3 · 最高精度', value: 'large-v3' },
    ],
  },
  'asr.device': {
    label: '运行设备',
    options: [{ label: 'CPU', value: 'cpu' }],
  },
  'asr.language': {
    label: '识别语言',
    options: [
      { label: '中文', value: 'zh' },
      { label: '英文', value: 'en' },
    ],
  },
};

export function AsrTab({
  models,
  settings,
  onSave,
  onChanged,
}: {
  models: ModelInfo[];
  settings: SettingsMap;
  onSave: (values: SettingsMap) => void;
  onChanged: () => void;
}): React.ReactElement {
  const asrModels = models.filter((m) => m.kind === 'asr');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <PageSection title="识别参数（即改即存）">
        <div style={{ display: 'flex', gap: tokens.space2xl, flexWrap: 'wrap' }}>
          {Object.entries(OPTIONS).map(([key, spec]) => (
            <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>{spec.label}</span>
              <Select
                style={{ width: 180 }}
                value={settings[key] ?? ''}
                options={spec.options}
                onChange={(value) => {
                  onSave({ [key]: value });
                }}
              />
            </div>
          ))}
        </div>
      </PageSection>
      <PageSection title="模型库">
        <ModelBrowser models={asrModels} onChanged={onChanged} />
      </PageSection>
    </div>
  );
}
