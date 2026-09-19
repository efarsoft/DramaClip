/** 引擎中心：按能力域（ASR/TTS/LLM）组织本地与云端引擎，数据一次拉齐后各 tab 共用。 */
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { App as AntdApp } from 'antd';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import type { ModelInfo } from '@dramaclip/protocol';
import { modelsApi, rpc, systemApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { OverviewTab } from './OverviewTab';
import { AsrTab } from './AsrTab';
import { TtsTab } from './TtsTab';
import { LlmTab } from './LlmTab';
import { EngineTabNav } from './EngineTabNav';
import { type Reports, reportsOf } from './assetState';
import { type MachineSpecs, specsFromHealth } from './machineFit';

export type SettingsMap = Record<string, string>;
export type EngineTabKey = 'overview' | 'asr' | 'tts' | 'llm';

/** ASR / TTS 两域同构：同一份数据、同一批回调（切骨架不切数据流，P3）。 */
export interface DomainTabProps {
  readonly models: ModelInfo[];
  readonly settings: SettingsMap;
  readonly reports: Reports;
  readonly machine: MachineSpecs;
  readonly onSave: (values: SettingsMap) => void;
  readonly onChanged: () => void;
  readonly onVerify: (modelId: string) => void;
}

interface EnginesData {
  readonly models: ModelInfo[];
  readonly settings: SettingsMap;
  readonly reports: Reports;
  readonly ffmpegVersion: string;
  readonly machine: MachineSpecs;
}

/** 引擎中心页（导航「引擎」）。 */
export function EnginesPage() {
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<EnginesData | null>(null);
  const tab = tabFromPath(location.pathname);

  const load = useCallback(async () => {
    const [models, settings, reports, health] = await Promise.all([
      modelsApi.list(),
      rpc<SettingsMap>('settings.get'),
      modelsApi.verify(),
      systemApi.health(),
    ]);
    setData({
      models,
      settings,
      reports: reportsOf(reports),
      ffmpegVersion: health.ffmpeg_version,
      machine: specsFromHealth(health),
    });
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

  /** 就地体检：结果并进 reports，页面上的「就绪/不完整」随即改口。 */
  const verifyOne = useCallback(async (modelId: string): Promise<void> => {
    const report = (await modelsApi.verify(modelId))[0];
    if (report === undefined) return;
    setData((current) =>
      current === null ? current : { ...current, reports: new Map(current.reports).set(modelId, report) },
    );
  }, []);

  return (
    <PageShell>
      <PageHeader title="引擎中心" desc="语音识别、配音、文案三类引擎——本地引擎免费离线，云端引擎即开即用" />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '216px minmax(0,1fr)',
          gap: tokens.spaceLg,
          alignItems: 'start',
        }}
      >
        <EngineTabNav tab={tab} onPick={(key) => { void navigate(`/engines/${key}`); }} />
        {data === null ? <PageSection>加载中…</PageSection> : (
          <TabBody tab={tab} data={data} onSave={saveSettings} onLoaded={load} onVerify={verifyOne} />
        )}
      </div>
    </PageShell>
  );
}

function TabBody({
  tab,
  data,
  onSave,
  onLoaded,
  onVerify,
}: {
  tab: EngineTabKey;
  data: EnginesData;
  onSave: (values: SettingsMap) => Promise<void>;
  onLoaded: () => Promise<void>;
  onVerify: (modelId: string) => Promise<void>;
}) {
  const domain: DomainTabProps = {
    models: data.models,
    settings: data.settings,
    reports: data.reports,
    machine: data.machine,
    onSave: (values) => {
      void onSave(values);
    },
    onChanged: () => {
      void onLoaded();
    },
    onVerify: (modelId) => {
      void onVerify(modelId);
    },
  };
  if (tab === 'asr') return <AsrTab {...domain} />;
  if (tab === 'tts') return <TtsTab {...domain} />;
  if (tab === 'llm') return <LlmTab onChanged={domain.onChanged} />;
  return (
    <OverviewTab
      models={data.models}
      settings={data.settings}
      reports={data.reports}
      ffmpegVersion={data.ffmpegVersion}
    />
  );
}

function tabFromPath(pathname: string): EngineTabKey {
  const match = /\/engines\/(asr|tts|llm)/.exec(pathname);
  return (match?.[1] as EngineTabKey | undefined) ?? 'overview';
}
