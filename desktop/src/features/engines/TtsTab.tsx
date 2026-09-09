/** TTS 引擎：本地 Kokoro / 云端 Edge 二选一，音色与模型就近配置。 */
import { Card as StyledCard, Select, Tag } from 'antd';
import { PageSection } from '../../components/layout/PageKit';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { ModelList } from './ModelList';
import type { SettingsMap } from './EnginesPage';

const EDGE_VOICES = [
  { label: '云希 · 男声', value: 'zh-CN-YunxiNeural' },
  { label: '晓伊 · 女声', value: 'zh-CN-XiaoyiNeural' },
  { label: '云扬 · 男声（播音）', value: 'zh-CN-YunyangNeural' },
];

const KOKORO_VOICES = [
  { label: 'zf_001 · 女声', value: 'zf_001' },
  { label: 'zf_003 · 女声', value: 'zf_003' },
  { label: 'zm_001 · 男声', value: 'zm_001' },
  { label: 'zm_003 · 男声', value: 'zm_003' },
];

export function TtsTab({
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
  const engine = settings['tts.engine'] === 'kokoro' ? 'kokoro' : 'edge';
  const kokoro = models.find((m) => m.model_id.includes('kokoro'));
  const voices = engine === 'kokoro' ? KOKORO_VOICES : EDGE_VOICES;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <EngineCard
          title="本地 · Kokoro 82M 中文"
          desc="模型下载到本机运行，免费、离线、数据不出本机；速度取决于 CPU。"
          active={engine === 'kokoro'}
          ok={kokoro?.status === 'installed'}
          onClick={() => {
            onSave({ 'tts.engine': 'kokoro' });
          }}
        />
        <EngineCard
          title="云端 · Edge（微软）"
          desc="免费云端服务，无需 API Key，音质佳；需联网，不计费。"
          active={engine === 'edge'}
          ok={true}
          onClick={() => {
            onSave({ 'tts.engine': 'edge' });
          }}
        />
      </div>
      <PageSection title="默认音色">
        <Select
          style={{ width: 240 }}
          value={settings['tts.voice'] ?? ''}
          options={voices}
          onChange={(value) => {
            onSave({ 'tts.voice': value });
          }}
        />
      </PageSection>
      {engine === 'kokoro' && kokoro !== undefined && (
        <PageSection title="本地模型">
          <ModelList models={[kokoro]} onChanged={onChanged} />
        </PageSection>
      )}
    </div>
  );
}

function EngineCard({
  title,
  desc,
  active,
  ok,
  onClick,
}: {
  title: string;
  desc: string;
  active: boolean;
  ok: boolean;
  onClick: () => void;
}): React.ReactElement {
  return (
    <StyledCard
      size="small"
      hoverable
      onClick={onClick}
      style={{
        borderColor: active ? tokens.colorPrimary : tokens.border,
        background: active ? tokens.accentSoft : undefined,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <strong style={{ fontSize: 13.5, color: tokens.textPrimary }}>{title}</strong>
        {active && (
          <Tag color="blue" style={{ marginRight: 0 }}>
            使用中
          </Tag>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: ok ? tokens.colorSuccess : tokens.colorWarning }}>
          ● {ok ? '就绪' : '缺模型'}
        </span>
      </div>
      <div style={{ marginTop: 8, fontSize: 12.5, lineHeight: '19px', color: tokens.textTertiary }}>
        {desc}
      </div>
    </StyledCard>
  );
}
