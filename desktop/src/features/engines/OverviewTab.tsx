/** 引擎中心·总览：三类能力卡片 + 本地/云端起步路线 + 本机运行条件。 */
import { AudioOutlined, EditOutlined, RightOutlined, SoundOutlined } from '@ant-design/icons';
import { Card } from 'antd';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import type { SettingsMap } from './EnginesPage';
import { MachinePanel } from './MachinePanel';

function SectionCard({
  onClick,
  children,
}: {
  onClick?: () => void;
  children: ReactNode;
}): React.ReactElement {
  return (
    <Card
      size="small"
      hoverable={onClick !== undefined}
      onClick={onClick}
      styles={{
        body: { padding: `${tokens.spaceMd} ${tokens.spaceLg}`, height: '100%' },
      }}
    >
      {children}
    </Card>
  );
}

interface Capability {
  readonly name: string;
  readonly tab: 'asr' | 'tts' | 'llm';
  readonly icon: ReactNode;
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
      icon: <AudioOutlined />,
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
      icon: <SoundOutlined />,
      current:
        ttsEngine === 'kokoro'
          ? kokoroReady
            ? '本地 · Kokoro 已就绪'
            : '本地 · 缺模型'
          : ttsEngine === 'sherpa_melo'
            ? '本地 · sherpa-onnx 已就绪'
            : '云端 · Edge 免费即用',
      ok: ttsEngine !== 'kokoro' || kokoroReady,
    },
    {
      name: '文案 LLM',
      tab: 'llm',
      icon: <EditOutlined />,
      current: llmReady ? `云端 · ${settings['llm.model'] ?? ''}` : '未配置 · 解说模式不可用',
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: tokens.spaceLg }}>
        {capabilities.map((item) => (
          <CapabilityCard key={item.name} item={item} onGo={() => void navigate(`/engines/${item.tab}`)} />
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: tokens.spaceLg }}>
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
      <MachinePanel models={models} />
    </div>
  );
}

function CapabilityCard({ item, onGo }: { item: Capability; onGo: () => void }): React.ReactElement {
  const tint = item.ok ? tokens.colorSuccess : tokens.colorWarning;
  return (
    <SectionCard onClick={onGo}>
      <div style={{ display: 'flex', gap: tokens.spaceMd, height: '100%' }}>
        <span
          style={{
            width: 38,
            height: 38,
            borderRadius: tokens.radiusControl,
            background: tokens.accentSoft,
            color: tokens.colorPrimary,
            fontSize: tokens.fontChipIcon,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          {item.icon}
        </span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
            <span style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>{item.name}</span>
            <span
              style={{
                marginLeft: 'auto',
                width: 8,
                height: 8,
                borderRadius: tokens.radiusThumb,
                background: tint,
                boxShadow: `0 0 6px ${tint}`,
                flexShrink: 0,
              }}
            />
          </div>
          <div style={{ fontSize: tokens.fontCaption, color: tint }}>{item.current}</div>
          <div
            style={{
              marginTop: 'auto',
              display: 'flex',
              alignItems: 'center',
              gap: tokens.spaceXs,
              fontSize: tokens.fontCaption,
              color: tokens.colorPrimary,
            }}
          >
            去调整
            <RightOutlined style={{ fontSize: tokens.fontIcon }} />
          </div>
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
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceLg }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>{title}</div>
          <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary, marginTop: 3 }}>{desc}</div>
        </div>
        <span
          style={{
            marginLeft: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: tokens.spaceXs,
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

