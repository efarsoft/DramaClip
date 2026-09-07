/** 引擎中心：按能力域（ASR/TTS/LLM）组织本地与云端引擎。 */
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { App as AntdApp, Card } from 'antd';
import {
  ApiOutlined,
  AudioOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { ModelInfo } from '@dramaclip/protocol';
import { modelsApi, rpc } from '../../services/client';
import { tokens } from '../../styles/theme';
import { OverviewTab } from './OverviewTab';
import { AsrTab } from './AsrTab';
import { TtsTab } from './TtsTab';
import { LlmTab } from './LlmTab';

export type SettingsMap = Record<string, string>;
export type EngineTab = 'overview' | 'asr' | 'tts' | 'llm';

const TABS = [
  { key: 'overview', label: '总览', icon: DashboardOutlined },
  { key: 'asr', label: '语音识别 ASR', icon: AudioOutlined },
  { key: 'tts', label: '配音 TTS', icon: ThunderboltOutlined },
  { key: 'llm', label: '文案 LLM', icon: ApiOutlined },
] as const;

interface EnginesData {
  readonly models: ModelInfo[];
  readonly settings: SettingsMap;
}

/** 引擎中心页（导航「引擎」）。 */
export function EnginesPage() {
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<EnginesData | null>(null);
  const tab = tabFromPath(location.pathname);

  const load = useCallback(async () => {
    const [models, settings] = await Promise.all([
      modelsApi.list(),
      rpc<SettingsMap>('settings.get'),
    ]);
    setData({ models, settings });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveSettings = useCallback(
    (values: SettingsMap): Promise<void> =>
      rpc('settings.update', { values }).then(() => {
        message.success('已保存');
        void load();
      }),
    [load, message],
  );

  return (
    <div style={{ maxWidth: 1160, margin: '0 auto' }}>
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: tokens.textPrimary }}>引擎中心</h1>
        <div style={{ fontSize: 13, color: tokens.textTertiary, marginTop: 6 }}>
          语音识别、配音、文案三类引擎——本地引擎免费离线，云端引擎即开即用
        </div>
      </header>
      <div style={{ display: 'grid', gridTemplateColumns: '216px minmax(0,1fr)', gap: 16, alignItems: 'start' }}>
        <TabNav tab={tab} onPick={(key) => { void navigate(`/models/${key}`); }} />
        {data === null ? (
          <Card loading />
        ) : tab === 'asr' ? (
          <AsrTab models={data.models} settings={data.settings} onSave={(values) => { void saveSettings(values); }} onChanged={() => { void load(); }} />
        ) : tab === 'tts' ? (
          <TtsTab models={data.models} settings={data.settings} onSave={(values) => { void saveSettings(values); }} onChanged={() => { void load(); }} />
        ) : tab === 'llm' ? (
          <LlmTab settings={data.settings} onSave={saveSettings} />
        ) : (
          <OverviewTab models={data.models} settings={data.settings} />
        )}
      </div>
    </div>
  );
}

function tabFromPath(hash: string): EngineTab {
  const match = /\/models\/(asr|tts|llm)/.exec(hash);
  return (match?.[1] as EngineTab | undefined) ?? 'overview';
}

function TabNav({ tab, onPick }: { tab: EngineTab; onPick: (key: EngineTab) => void }) {
  return (
    <Card styles={{ body: { padding: 8 } }}>
      {TABS.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => {
            onPick(item.key);
          }}
          style={{
            width: '100%',
            height: 38,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            paddingLeft: 12,
            marginBottom: 2,
            borderRadius: 8,
            border: 'none',
            background: tab === item.key ? tokens.accentSoft : 'transparent',
            color: tab === item.key ? tokens.colorPrimary : tokens.textSecondary,
            fontSize: 13,
            fontWeight: tab === item.key ? 600 : 400,
            cursor: 'pointer',
          }}
        >
          <item.icon style={{ fontSize: 14 }} />
          {item.label}
        </button>
      ))}
      <div style={{ padding: '10px 12px 4px', fontSize: 11, color: tokens.textTertiary }}>
        <CloudServerOutlined style={{ marginRight: 6 }} />
        云端与本地引擎随时切换
      </div>
    </Card>
  );
}
