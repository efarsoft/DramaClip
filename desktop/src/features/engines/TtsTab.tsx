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
  { label: '云健 · 男声（激情）', value: 'zh-CN-YunjianNeural' },
  { label: '云夏 · 男声（少年）', value: 'zh-CN-YunxiaNeural' },
  { label: '晓晓 · 女声（温暖）', value: 'zh-CN-XiaoxiaoNeural' },
  { label: '晓北 · 女声（东北）', value: 'zh-CN-liaoning-XiaobeiNeural' },
  { label: '晓妮 · 女声（陕西）', value: 'zh-CN-shaanxi-XiaoniNeural' },
  { label: '曉佳 · 女声（粤语）', value: 'zh-HK-HiuGaaiNeural' },
  { label: '雲龍 · 男声（粤语）', value: 'zh-HK-WanLungNeural' },
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
  const engine = ['kokoro', 'sherpa_melo'].includes(settings['tts.engine'] ?? '')
    ? settings['tts.engine']
    : 'edge';
  const ttsModels = models.filter((m) => m.kind === 'tts');
  const kokoro = ttsModels.find((m) => m.model_id.includes('kokoro'));
  const voices = engine === 'kokoro' || engine === 'sherpa_melo' ? KOKORO_VOICES : EDGE_VOICES;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: tokens.spaceLg }}>
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
          title="本地 · sherpa-onnx melo-zh"
          desc="VITS melo 中文模型，CPU 推理 RTF~0.69，44.1kHz 高音质。"
          active={engine === 'sherpa_melo'}
          ok={true}
          onClick={() => {
            onSave({ 'tts.engine': 'sherpa_melo' });
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
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
        <strong style={{ fontSize: tokens.fontBody, color: tokens.textPrimary }}>{title}</strong>
        {active && (
          <Tag color="blue" style={{ marginRight: 0 }}>
            使用中
          </Tag>
        )}
        <span style={{ marginLeft: 'auto', fontSize: tokens.fontCaption, color: ok ? tokens.colorSuccess : tokens.colorWarning }}>
          ● {ok ? '就绪' : '缺模型'}
        </span>
      </div>
      <div style={{ marginTop: tokens.spaceSm, fontSize: tokens.fontCaption, lineHeight: '19px', color: tokens.textTertiary }}>
        {desc}
      </div>
    </StyledCard>
  );
}
