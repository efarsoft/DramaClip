/** 引擎中心：按能力域（ASR/TTS/LLM）组织本地与云端引擎，数据一次拉齐后各 tab 共用。 */
import { useLocation, useNavigate } from 'react-router-dom';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import type { ImportRecord, ModelInfo, SelftestResults } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { OverviewTab } from './OverviewTab';
import { AsrTab } from './AsrTab';
import { TtsTab } from './TtsTab';
import { LlmTab } from './LlmTab';
import { PromptsTab } from './PromptsTab';
import { EngineTabNav } from './EngineTabNav';
import { ImportModelModal } from './ImportModelModal';
import type { Reports } from './assetState';
import type { MachineSpecs } from './machineFit';
import { type EnginesData, useEnginesData } from './useEnginesData';
import { useModelImport } from './useModelImport';

export type SettingsMap = Record<string, string>;
export type EngineTabKey = 'overview' | 'asr' | 'tts' | 'llm' | 'prompts';

/** ASR / TTS 两域同构：同一份数据、同一批回调（切骨架不切数据流，P3）。 */
export interface DomainTabProps {
  readonly models: ModelInfo[];
  /** 「本地导入」登记本原样交下来：哪几条属于本域，由 externalAssets 判，tab 里不重写。 */
  readonly imported: ImportRecord[];
  /** 登记本读坏了的原话，空串 = 读通了；坏了不等于库里没货。 */
  readonly importError: string;
  readonly settings: SettingsMap;
  readonly reports: Reports;
  /** 自检账本：就绪 = 校验过 + 自检过（§10.1），能力层那一半从这里来。 */
  readonly selftests?: SelftestResults;
  readonly machine: MachineSpecs;
  readonly onSave: (values: SettingsMap) => void;
  readonly onChanged: () => void;
  readonly onVerify: (modelId: string) => void;
  readonly onForget: (path: string) => void;
  readonly onImport: () => void;
}

/** 引擎中心页（导航「引擎」）。 */
export function EnginesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { data, load, saveSettings, verifyOne } = useEnginesData();
  const tab = tabFromPath(location.pathname);

  const hub = useModelImport(data?.models ?? [], load, saveSettings);

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
          <TabBody
            tab={tab}
            data={data}
            onSave={saveSettings}
            onLoaded={load}
            onVerify={verifyOne}
            onForget={hub.forget}
            onImport={hub.open}
          />
        )}
      </div>
      <ImportModelModal
        open={hub.importing}
        onClose={hub.close}
        onChanged={() => {
          void load();
        }}
        onActivate={hub.activateLanded}
      />
    </PageShell>
  );
}

function TabBody({
  tab,
  data,
  onSave,
  onLoaded,
  onVerify,
  onForget,
  onImport,
}: {
  tab: EngineTabKey;
  data: EnginesData;
  onSave: (values: SettingsMap) => Promise<void>;
  onLoaded: () => Promise<void>;
  onVerify: (modelId: string) => Promise<void>;
  onForget: (path: string) => void;
  onImport: () => void;
}) {
  const domain: DomainTabProps = {
    models: data.models,
    imported: data.imported,
    importError: data.importError,
    settings: data.settings,
    reports: data.reports,
    selftests: data.selftests,
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
    onForget,
    onImport,
  };
  if (tab === 'asr') return <AsrTab {...domain} />;
  if (tab === 'tts') return <TtsTab {...domain} />;
  if (tab === 'llm') return <LlmTab onChanged={domain.onChanged} />;
  if (tab === 'prompts') return <PromptsTab />;
  return (
    <OverviewTab
      models={data.models}
      settings={data.settings}
      reports={data.reports}
      selftests={data.selftests}
      ffmpegVersion={data.ffmpegVersion}
    />
  );
}

function tabFromPath(pathname: string): EngineTabKey {
  const match = /\/engines\/(asr|tts|llm|prompts)/.exec(pathname);
  return (match?.[1] as EngineTabKey | undefined) ?? 'overview';
}
