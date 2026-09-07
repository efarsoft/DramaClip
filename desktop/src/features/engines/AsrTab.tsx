/** ASR 引擎：本地 faster-whisper（模型管理 + 参数）；云端暂未接入。 */
import { Card, Select } from 'antd';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { ModelRow } from './ModelRow';
import type { SettingsMap } from './EnginesPage';

const OPTIONS: Record<string, { label: string; options: { label: string; value: string }[] }> = {
  'asr.model': {
    label: '默认模型',
    options: [
      { label: 'small · 更准', value: 'small' },
      { label: 'base · 更快', value: 'base' },
    ],
  },
  'asr.device': {
    label: '设备',
    options: [{ label: 'CPU', value: 'cpu' }],
  },
  'asr.language': {
    label: '语言',
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Card size="small" title="云端识别">
        <div style={{ fontSize: 12.5, color: tokens.textTertiary }}>
          暂未接入云端 ASR——本地 faster-whisper 已覆盖转写需求，云端引擎规划在后续版本。
        </div>
      </Card>
      <Card size="small" title="引擎参数（即改即存）">
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap' }}>
          {Object.entries(OPTIONS).map(([key, spec]) => (
            <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 12, color: tokens.textTertiary }}>{spec.label}</span>
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
      </Card>
      <Card size="small" title="本地模型">
        {asrModels.map((model) => (
          <ModelRow key={model.model_id} model={model} recommended={model.required} onChanged={onChanged} />
        ))}
      </Card>
    </div>
  );
}
