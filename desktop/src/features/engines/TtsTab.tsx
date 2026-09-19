/**
 * 配音 TTS：当前生效卡（引擎切换 + 音色 + 该引擎模型的安装态内联）→ 资产库。
 *
 * 旧的三张平铺引擎卡上有写死的 `ok: true`（P1 缺陷本体）；这里一律以
 * models.list 的 engine_ready/status 与 models.verify 的结论为准，
 * 免模型的云端引擎单独走「无需本地模型」这条说明，不冒充体检结果。
 */
import { Button, Segmented } from 'antd';
import type { ReactElement } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import type { DomainTabProps } from './EnginesPage';
import type { AssetState, Reports } from './assetState';
import {
  activateSettings,
  activeAsset,
  assetState,
  failureNote,
  formatBytes,
  reportFor,
} from './assetState';
import { DownloadSourceButton } from './ModelDownloadPopover';
import { type ActiveCardProps, ActiveEngineCard } from './ActiveEngineCard';
import { AssetLibrary } from './AssetLibrary';
import { SettingSelect } from './SettingSelect';
import { useDownloadProgress } from './useDownloadProgress';
import {
  TTS_ENGINES,
  isModelFreeEngine,
  ttsEngineLabel,
  voiceOptions,
  voiceSettingKey,
} from './ttsVoices';

const ENGINE_KIND_LABEL: Record<string, string> = {
  kokoro: '本地 · 免费离线',
  sherpa_melo: '本地 · 免费离线',
  edge: '云端 · 免费无需 API Key',
};

const VOICE_HINT: Record<string, string> = {
  kokoro: 'Kokoro 提供 100 个中文音色（55 女 + 45 男），下拉可搜索',
  sherpa_melo: 'melo 模型为单说话人，音色固定',
  edge: '微软官方中文音色，覆盖普通话 / 东北 / 陕西 / 粤语 / 台湾',
};

export function TtsTab({
  models,
  settings,
  reports,
  machine,
  onSave,
  onChanged,
  onVerify,
}: DomainTabProps): ReactElement {
  const engine = settings['tts.engine'] ?? '';
  const domainModels = models.filter((model) => model.kind === 'tts');
  const active = isModelFreeEngine(engine) ? undefined : activeAsset(models, 'tts', settings);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <ActiveCard
        active={active}
        engine={engine}
        settings={settings}
        reports={reports}
        onSave={onSave}
        onChanged={onChanged}
        onVerify={onVerify}
      />
      <AssetLibrary
        models={domainModels}
        reports={reports}
        specs={machine}
        activeModelId={active?.model_id}
        onActivate={(model) => {
          onSave(activateSettings(model));
        }}
        onChanged={onChanged}
        onVerify={onVerify}
      />
    </div>
  );
}

function ActiveCard({
  active,
  engine,
  settings,
  reports,
  onSave,
  onChanged,
  onVerify,
}: {
  active: ModelInfo | undefined;
  engine: string;
  settings: DomainTabProps['settings'];
  reports: Reports;
  onSave: DomainTabProps['onSave'];
  onChanged: () => void;
  onVerify: DomainTabProps['onVerify'];
}): ReactElement {
  const modelFree = isModelFreeEngine(engine);
  const report = active === undefined ? undefined : reportFor(reports, active.model_id);
  const state: AssetState | null =
    active === undefined ? (modelFree ? null : 'missing') : assetState(active, report);
  const card: ActiveCardProps = {
    domain: '配音 TTS',
    title: active?.name ?? (engine === '' ? '未选引擎' : ttsEngineLabel(engine)),
    state,
    hint: '云端引擎，无需本地模型 · 需联网',
    stateNote: failureNote(report),
    progress: useDownloadProgress(active),
    picker: (
      <Segmented
        size="small"
        value={engine}
        options={TTS_ENGINES.map((name) => ({ label: ttsEngineLabel(name), value: name }))}
        onChange={(value) => {
          onSave({ 'tts.engine': value });
        }}
      />
    ),
    actions: cardActions(active, state, onChanged, onVerify),
    props: [
      { label: '音色', value: <VoiceSelect engine={engine} settings={settings} onSave={onSave} /> },
      { label: '引擎类型', value: ENGINE_KIND_LABEL[engine] ?? '未登记引擎' },
      { label: '磁盘实占', value: active === undefined ? '—' : formatBytes(active.size_bytes ?? 0) },
      { label: '生效时机', value: '保存后下次任务' },
    ],
    footnote: VOICE_HINT[engine] ?? '换引擎后各自的音色互不覆盖',
  };
  return <ActiveEngineCard {...card} />;
}

function cardActions(
  active: ModelInfo | undefined,
  state: AssetState | null,
  onChanged: () => void,
  onVerify: (modelId: string) => void,
): ReactElement | undefined {
  if (active === undefined) return undefined;
  if (state === 'missing') return <DownloadSourceButton model={active} onChanged={onChanged} />;
  return (
    <Button
      size="small"
      onClick={() => {
        onVerify(active.model_id);
      }}
    >
      校验资产
    </Button>
  );
}

function VoiceSelect({
  engine,
  settings,
  onSave,
}: {
  engine: string;
  settings: DomainTabProps['settings'];
  onSave: DomainTabProps['onSave'];
}): ReactElement {
  const key = voiceSettingKey(engine);
  return (
    <SettingSelect
      value={settings[key] ?? ''}
      options={voiceOptions(engine)}
      searchable={engine === 'kokoro'}
      onChange={(value: string) => {
        onSave({ [key]: value });
      }}
    />
  );
}
