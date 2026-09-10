/** 引擎中心：按能力域（ASR/TTS/LLM）组织本地与云端引擎。 */
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { App as AntdApp } from 'antd';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import type { ModelInfo } from '@dramaclip/protocol';
import { modelsApi, rpc } from '../../services/client';
import {
  ApiOutlined,
  AudioOutlined,
  CustomerServiceOutlined,
  DashboardOutlined,
} from '@ant-design/icons';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { OverviewTab } from './OverviewTab';
import { AsrTab } from './AsrTab';
import { TtsTab } from './TtsTab';
import { LlmTab } from './LlmTab';

export type SettingsMap = Record<string, string>;
export type EngineTab = 'overview' | 'asr' | 'tts' | 'llm';

const TAB_ICONS: Record<EngineTab, typeof DashboardOutlined> = {
  overview: DashboardOutlined,
  asr: AudioOutlined,
  tts: CustomerServiceOutlined,
  llm: ApiOutlined,
};

const TAB_LABELS: Record<EngineTab, string> = {
  overview: '总览',
  asr: '语音识别 ASR',
  tts: '配音 TTS',
  llm: '文案 LLM',
};

const TAB_ORDER: readonly EngineTab[] = ['overview', 'asr', 'tts', 'llm'];

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
    <PageShell>
      <PageHeader
        title="引擎中心"
        desc="语音识别、配音、文案三类引擎——本地引擎免费离线，云端引擎即开即用"
      />
      <div style={{ display: 'grid', gridTemplateColumns: '216px minmax(0,1fr)', gap: tokens.spaceLg, alignItems: 'start' }}>
        <TabNav tab={tab} onPick={(key) => { void navigate(`/models/${key}`); }} />
        {data === null ? (
          <PageSection>加载中…</PageSection>
        ) : tab === 'asr' ? (
          <AsrTab models={data.models} settings={data.settings} onSave={(values) => { void saveSettings(values); }} onChanged={() => { void load(); }} />
        ) : tab === 'tts' ? (
          <TtsTab models={data.models} settings={data.settings} onSave={(values) => { void saveSettings(values); }} onChanged={() => { void load(); }} />
        ) : tab === 'llm' ? (
          <LlmTab onChanged={() => { void load(); }} />
        ) : (
          <OverviewTab models={data.models} settings={data.settings} />
        )}
      </div>
    </PageShell>
  );
}

function tabFromPath(pathname: string): EngineTab {
  const match = /\/models\/(asr|tts|llm)/.exec(pathname);
  return (match?.[1] as EngineTab | undefined) ?? 'overview';
}

/** 左侧 tab：与素材列表行同构（主色左条 + 选中底色，DSS §4.2）。 */
function TabNav({ tab, onPick }: { tab: EngineTab; onPick: (key: EngineTab) => void }): React.ReactElement {
  return (
    <nav
      style={{
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        padding: tokens.spaceSm,
      }}
    >
      {TAB_ORDER.map((key) => {
        const active = tab === key;
        const Icon = TAB_ICONS[key];
        return (
          <button
            key={key}
            type="button"
            onClick={() => {
              onPick(key);
            }}
            style={{
              ...mixins.listRow(active),
              height: 38,
              width: '100%',
              border: 'none',
              borderLeft: `3px solid ${active ? tokens.colorPrimary : 'transparent'}`,
              borderRadius: tokens.radiusControl,
              color: active ? tokens.colorPrimary : tokens.textSecondary,
              fontSize: tokens.fontBody,
              fontWeight: active ? 600 : 400,
              cursor: 'pointer',
              marginBottom: 2,
            }}
          >
            <Icon style={{ fontSize: tokens.fontBodyLg }} />
            {TAB_LABELS[key]}
          </button>
        );
      })}
      <div
        style={{
          padding: `${String(tokens.spaceSm)} ${String(tokens.spaceMd)}`,
          fontSize: tokens.fontMicro,
          color: tokens.textTertiary,
        }}
      >
        云端与本地引擎随时切换
      </div>
    </nav>
  );
}
