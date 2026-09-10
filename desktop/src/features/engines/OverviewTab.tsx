/** 引擎中心·总览：三类能力卡片 + 本地/云端起步路线。 */
import { Card } from 'antd';
import { tokens } from '../../styles/theme';

function SectionCard({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <Card
      size="small"
      hoverable
      onClick={onClick}
      styles={{
        body: { padding: `${String(tokens.spaceMd)} ${String(tokens.spaceLg)}`, height: '100%' },
      }}
    >
      {children}
    </Card>
  );
}

import { RightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ModelInfo } from '@dramaclip/protocol';
import type { SettingsMap } from './EnginesPage';

interface Capability {
  readonly name: string;
  readonly tab: 'asr' | 'tts' | 'llm';
  readonly icon: string;
  readonly current: string;
  readonly ok: boolean;
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
      icon: '🎙️',
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
      icon: '🔊',
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
      icon: '✍️',
      current: llmReady ? `云端 · ${settings['llm.model'] ?? ''}` : '未配置（关键词降级）',
      ok: llmReady,
    },
  ];
}

/** 总览 tab。 */
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
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
        {capabilities.map((item) => (
          <CapabilityCard key={item.name} item={item} onGo={() => void navigate(`/engines/${item.tab}`)} />
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <PathCard
          title="本地优先 · 免费离线"
          desc="下载语音识别与配音模型，数据不出本机，速度取决于电脑性能"
          action="去下载"
          onClick={() => {
            void navigate('/engines/asr');
          }}
        />
        <PathCard
          title="云端即开 · 免下载"
          desc="配置 LLM API Key 即可开始，配音默认走微软 Edge（免费）"
          action="去配置"
          onClick={() => {
            void navigate('/engines/llm');
          }}
        />
      </div>
    </div>
  );
}

function CapabilityCard({ item, onGo }: { item: Capability; onGo: () => void }): React.ReactElement {
  const tint = item.ok ? tokens.colorSuccess : tokens.colorWarning;
  return (
    <SectionCard onClick={onGo}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>{item.name}</span>
          <span
            style={{
              marginLeft: 'auto',
              width: 8,
              height: 8,
              borderRadius: tokens.radiusThumb,
              background: tint,
              boxShadow: `0 0 6px ${tint}`,
            }}
          />
        </div>
        <div style={{ fontSize: tokens.fontCaption, color: tint }}>{item.current}</div>
        <div
          style={{
            marginTop: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            fontSize: tokens.fontCaption,
            color: tokens.colorPrimary,
          }}
        >
          去调整
          <RightOutlined style={{ fontSize: tokens.fontIcon }} />
        </div>
      </div>
    </SectionCard>
  );
}

function PathCard({
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
    <SectionCard onClick={onClick}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>{title}</div>
          <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary, marginTop: 3 }}>{desc}</div>
        </div>
        <span
          style={{
            marginLeft: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '6px 14px',
            borderRadius: tokens.radiusControl,
            border: `1px solid ${tokens.border}`,
            background: tokens.bgElevated,
            color: tokens.textPrimary,
            fontSize: tokens.fontCaption,
            cursor: 'pointer',
            flexShrink: 0,
          }}
        >
          {action}
          <RightOutlined style={{ fontSize: tokens.fontIcon }} />
        </span>
      </div>
    </SectionCard>
  );
}
