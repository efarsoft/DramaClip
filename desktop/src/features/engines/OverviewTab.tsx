/** 引擎中心·总览：三类能力就绪状态 + 本地/云端路线。 */
import { Card } from 'antd';
import { RightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import type { SettingsMap } from './EnginesPage';

interface Capability {
  readonly name: string;
  readonly tab: 'asr' | 'tts' | 'llm';
  readonly current: string;
  readonly ok: boolean;
}

export function OverviewTab({
  models,
  settings,
}: {
  models: ModelInfo[];
  settings: SettingsMap;
}): React.ReactElement {
  const navigate = useNavigate();
  const capabilities = buildCapabilities(models, settings);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Card size="small" styles={{ body: { padding: '8px 16px' } }}>
        {capabilities.map((item) => (
          <CapabilityRow
            key={item.name}
            item={item}
            onGo={() => {
              void navigate(`/models/${item.tab}`);
            }}
          />
        ))}
      </Card>
      <Card size="small" title="两条起步路线（任选其一）">
        <PathRow
          title="本地优先 · 免费离线"
          desc="下载语音识别与配音模型，数据不出本机，速度取决于电脑性能"
          action="去下载"
          onClick={() => {
            void navigate('/models/asr');
          }}
        />
        <PathRow
          title="云端即开 · 免下载"
          desc="配置 LLM API Key 即可开始，配音默认走微软 Edge（免费）"
          action="去配置"
          onClick={() => {
            void navigate('/models/llm');
          }}
        />
      </Card>
    </div>
  );
}

function buildCapabilities(models: ModelInfo[], settings: SettingsMap): Capability[] {
  const asr = models.find((m) => m.required);
  const kokoro = models.find((m) => m.model_id.includes('kokoro'));
  const kokoroReady = kokoro?.status === 'installed';
  const ttsEngine = settings['tts.engine'] ?? 'edge';
  const llmReady = (settings['llm.base_url'] ?? '') !== '';
  return [
    {
      name: '语音识别 ASR',
      tab: 'asr',
      current:
        asr === undefined
          ? '未安装模型'
          : asr.status === 'installed'
            ? `本地 · ${asr.name}`
            : '本地 · 缺模型',
      ok: asr?.status === 'installed',
    },
    {
      name: '配音 TTS',
      tab: 'tts',
      current:
        ttsEngine === 'kokoro'
          ? kokoroReady
            ? '本地 · Kokoro 已就绪'
            : '本地 · 缺模型'
          : '云端 · Edge 免费即用',
      ok: ttsEngine !== 'kokoro' || kokoroReady,
    },
    {
      name: '文案 LLM',
      tab: 'llm',
      current:
        llmReady ? `云端 · ${settings['llm.model'] ?? ''}` : '未配置（关键词降级）',
      ok: llmReady,
    },
  ];
}

function CapabilityRow({ item, onGo }: { item: Capability; onGo: () => void }): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '11px 0',
        borderBottom: `1px solid ${tokens.borderSecondary}`,
        fontSize: 13,
      }}
    >
      <span style={{ width: 120, color: tokens.textSecondary }}>{item.name}</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: 4,
            background: item.ok ? tokens.colorSuccess : tokens.colorWarning,
          }}
        />
        <span style={{ color: item.ok ? tokens.textSecondary : tokens.colorWarning }}>{item.current}</span>
      </span>
      <button
        type="button"
        onClick={onGo}
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: 3,
          background: 'none',
          border: 'none',
          color: tokens.colorPrimary,
          fontSize: 12.5,
          cursor: 'pointer',
          padding: 0,
        }}
      >
        去调整
        <RightOutlined style={{ fontSize: 9 }} />
      </button>
    </div>
  );
}

function PathRow({
  title,
  desc,
  action,
  onClick,
}: {
  title: string;
  desc: string;
  action: string;
  onClick: () => void;
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '13px 0',
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <div>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: tokens.textPrimary }}>{title}</div>
        <div style={{ fontSize: 12.5, color: tokens.textTertiary, marginTop: 3 }}>{desc}</div>
      </div>
      <button
        type="button"
        onClick={onClick}
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: '6px 14px',
          borderRadius: 8,
          border: `1px solid ${tokens.border}`,
          background: tokens.bgElevated,
          color: tokens.textPrimary,
          fontSize: 12.5,
          cursor: 'pointer',
        }}
      >
        {action}
        <RightOutlined style={{ fontSize: 9 }} />
      </button>
    </div>
  );
}
