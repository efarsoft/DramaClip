/** TTS 引擎：本地 Kokoro / sherpa / 云端 Edge，音色目录与设置键按引擎独立。 */
import { Card as StyledCard, Select, Tag } from 'antd';
import { PageSection } from '../../components/layout/PageKit';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { ModelList } from './ModelList';
import type { SettingsMap } from './EnginesPage';
import { TTS_ENGINES, TTS_VOICE_OPTIONS, voiceSettingKey } from './ttsVoices';
import type { TtsEngineName } from './ttsVoices';

const ENGINE_META: Record<TtsEngineName, { title: string; desc: string }> = {
  kokoro: {
    title: '本地 · Kokoro 82M 中文',
    desc: '模型下载到本机运行，免费、离线、数据不出本机；速度取决于 CPU。',
  },
  sherpa_melo: {
    title: '本地 · sherpa-onnx melo-zh',
    desc: 'VITS melo 中文模型，CPU 推理 RTF~0.69，44.1kHz 高音质。',
  },
  edge: {
    title: '云端 · Edge（微软）',
    desc: '免费云端服务，无需 API Key，音质佳；需联网，不计费。',
  },
};

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
  const engine: TtsEngineName = TTS_ENGINES.includes(settings['tts.engine'] as TtsEngineName)
    ? (settings['tts.engine'] as TtsEngineName)
    : 'edge';
  const ttsModels = models.filter((m) => m.kind === 'tts');
  const kokoroReady = ttsModels.some((m) => m.model_id.includes('kokoro') && m.status === 'installed');
  const engineReady: Record<TtsEngineName, boolean> = {
    kokoro: kokoroReady,
    sherpa_melo: true,
    edge: true,
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: tokens.spaceLg }}>
        {TTS_ENGINES.map((name) => (
          <EngineCard
            key={name}
            title={ENGINE_META[name].title}
            desc={ENGINE_META[name].desc}
            active={engine === name}
            ok={engineReady[name]}
            onClick={() => {
              onSave({ 'tts.engine': name });
            }}
          />
        ))}
      </div>
      <PageSection title="默认音色">
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceLg }}>
          <VoicePicker
            engine={engine}
            value={settings[voiceSettingKey(engine)] ?? ''}
            onSave={onSave}
          />
          <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
            {VOICE_HINT[engine]}
          </span>
        </div>
      </PageSection>
      <PageSection title="本地模型库">
        <div style={{ fontSize: tokens.fontCaption, color: tokens.colorWarning, marginBottom: tokens.spaceLg }}>
          注意：IndexTTS2 / VibeVoice 当前仅支持下载存储，合成引擎尚未接入（排期 P-2）——
          当前可用的配音引擎为上方 Kokoro / sherpa / Edge。
        </div>
        <ModelList models={ttsModels} onChanged={onChanged} />
      </PageSection>
    </div>
  );
}

const VOICE_HINT: Record<TtsEngineName, string> = {
  kokoro: 'Kokoro 提供 100 个中文音色（55 女 + 45 男），下拉可搜索',
  sherpa_melo: 'melo 模型为单说话人，音色固定',
  edge: '微软官方中文音色，覆盖普通话 / 东北 / 陕西 / 粤语 / 台湾',
};

function VoicePicker({
  engine,
  value,
  onSave,
}: {
  engine: TtsEngineName;
  value: string;
  onSave: (values: SettingsMap) => void;
}): React.ReactElement {
  const key = voiceSettingKey(engine);
  return (
    <Select
      style={{ width: 280 }}
      showSearch={engine === 'kokoro' ? { optionFilterProp: 'label' } : false}
      value={value}
      options={TTS_VOICE_OPTIONS[engine]}
      onChange={(next) => {
        onSave({ [key]: next });
      }}
    />
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
        position: 'relative',
        borderColor: active ? tokens.colorPrimary : tokens.border,
        background: active ? tokens.accentSoft : undefined,
      }}
    >
      <span
        style={{
          position: 'absolute', top: tokens.spaceMd, right: tokens.spaceMd,
          fontSize: tokens.fontCaption, color: ok ? tokens.colorSuccess : tokens.colorWarning,
        }}
      >
        ● {ok ? '就绪' : '缺模型'}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, paddingRight: 52 }}>
        <strong
          style={{
            fontSize: tokens.fontBody, color: tokens.textPrimary,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}
        >
          {title}
        </strong>
        {active && (
          <Tag color="blue" style={{ marginRight: 0, flexShrink: 0 }}>
            使用中
          </Tag>
        )}
      </div>
      <div style={{ marginTop: tokens.spaceSm, fontSize: tokens.fontCaption, lineHeight: '19px', color: tokens.textTertiary }}>
        {desc}
      </div>
    </StyledCard>
  );
}
