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
import { pickAudioFile } from '../../services/client';
import { tokens } from '../../styles/theme';
import type { DomainTabProps } from './EnginesPage';
import type { AssetState, Reports } from './assetState';
import {
  activateSettings,
  activeAsset,
  activeStateNote,
  assetState,
  externalAssets,
  formatBytes,
  reportFor,
} from './assetState';
import { DownloadSourceButton } from './ModelDownloadPopover';
import { type ActiveCardProps, ActiveEngineCard } from './ActiveEngineCard';
import { AssetLibrary } from './AssetLibrary';
import { SettingSelect } from './SettingSelect';
import { TtsPreviewButton } from './TtsPreviewButton';
import { previewNotice } from './ttsPreview';
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
  edge: '云端 · 免费无需 API Key',
  indextts2: '本地 · 音色克隆（N 卡实时 / CPU 预生成）',
};

const VOICE_HINT: Record<string, string> = {
  kokoro: 'Kokoro 提供 100 个中文音色（55 女 + 45 男），下拉可搜索',
  edge: '微软官方中文音色，覆盖普通话 / 东北 / 陕西 / 粤语 / 台湾',
  indextts2: '零样本克隆：选一段 3~10 秒干净人声做音色（如剧集主角台词）',
};

export function TtsTab({
  models,
  imported,
  importError,
  settings,
  reports,
  selftests,
  machine,
  onSave,
  onChanged,
  onVerify,
  onForget,
  onImport,
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
        selftests={selftests}
        onSave={onSave}
        onChanged={onChanged}
        onVerify={onVerify}
      />
      <AssetLibrary
        models={domainModels}
        externals={externalAssets(imported, 'tts')}
        importError={importError}
        reports={reports}
        selftests={selftests}
        specs={machine}
        activeModelId={active?.model_id}
        onActivate={(model) => {
          onSave(activateSettings(model));
        }}
        onChanged={onChanged}
        onVerify={onVerify}
        onForget={onForget}
        onImport={onImport}
        renderPreview={previewRenderer(settings, reports)}
      />
    </div>
  );
}

/** 行内试听节点：音色取该引擎自己的设置值，放行判断照旧只挡「必然听不到」的确定情况。 */
function previewRenderer(
  settings: DomainTabProps['settings'],
  reports: Reports,
): (model: ModelInfo) => ReactElement {
  return (model) => {
    const assetVoice = settings[voiceSettingKey(model.engine)] ?? '';
    return (
      <TtsPreviewButton
        engine={model.engine}
        voice={assetVoice}
        blocked={previewNotice({
          engine: model.engine,
          voice: assetVoice,
          state: assetState(model, reportFor(reports, model.model_id)),
        })}
      />
    );
  };
}

function ActiveCard({
  active,
  engine,
  settings,
  reports,
  selftests,
  onSave,
  onChanged,
  onVerify,
}: {
  active: ModelInfo | undefined;
  engine: string;
  settings: DomainTabProps['settings'];
  reports: Reports;
  selftests: DomainTabProps['selftests'];
  onSave: DomainTabProps['onSave'];
  onChanged: () => void;
  onVerify: DomainTabProps['onVerify'];
}): ReactElement {
  const modelFree = isModelFreeEngine(engine);
  const report = active === undefined ? undefined : reportFor(reports, active.model_id);
  const state: AssetState | null =
    active === undefined
      ? (modelFree ? null : 'missing')
      : assetState(active, report, selftests?.[active.model_id]);
  const voice = settings[voiceSettingKey(engine)] ?? '';
  const card: ActiveCardProps = {
    domain: '配音 TTS',
    title: active?.name ?? (engine === '' ? '未选引擎' : ttsEngineLabel(engine)),
    state,
    hint: '云端引擎，无需本地模型 · 需联网',
    stateNote: state === null ? undefined : activeStateNote(state, report),
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
      {
        label: '音色',
        value: (
          <VoiceRow engine={engine} voice={voice} state={state} settings={settings} onSave={onSave} />
        ),
      },
      { label: '引擎类型', value: ENGINE_KIND_LABEL[engine] ?? '未登记引擎' },
      { label: '磁盘实占', value: active === undefined ? '—' : formatBytes(active.size_bytes ?? 0) },
      { label: '生效时机', value: '保存后下次任务' },
    ],
    footnote: `${VOICE_HINT[engine] ?? '换引擎后各自的音色互不覆盖'} · 试听是引擎原声，成片还要过响度归一`,
  };
  return <ActiveEngineCard {...card} />;
}

/** 音色与试听同处一格：换音色必然要再听一次，分成两格等于让人自己记着去点。 */
function VoiceRow({
  engine,
  voice,
  state,
  settings,
  onSave,
}: {
  engine: string;
  voice: string;
  state: AssetState | null;
  settings: DomainTabProps['settings'];
  onSave: DomainTabProps['onSave'];
}): ReactElement {
  if (engine === 'indextts2') {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'flex-start', gap: tokens.spaceSm }}>
        <RefVoiceSelect settings={settings} onSave={onSave} />
        <TtsPreviewButton engine={engine} voice={voice} blocked={previewNotice({ engine, voice, state })} />
      </span>
    );
  }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'flex-start', gap: tokens.spaceSm }}>
      <VoiceSelect engine={engine} settings={settings} onSave={onSave} />
      <TtsPreviewButton engine={engine} voice={voice} blocked={previewNotice({ engine, voice, state })} />
    </span>
  );
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

/** IndexTTS 的音色=参考音频：文件选择代替下拉（零样本克隆任意人声）。 */
function RefVoiceSelect({
  settings,
  onSave,
}: {
  settings: DomainTabProps['settings'];
  onSave: DomainTabProps['onSave'];
}): ReactElement {
  const key = voiceSettingKey('indextts2');
  const value = settings[key] ?? '';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spaceSm }}>
      <Button
        size="small"
        onClick={() => {
          void pickAudioFile().then((path) => {
            if (path !== null) onSave({ [key]: path });
          });
        }}
      >
        {value === '' ? '选择参考音频' : '更换参考音频'}
      </Button>
      <span
        style={{
          maxWidth: 220,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: value === '' ? tokens.colorWarning : tokens.textTertiary,
        }}
        title={value}
      >
        {value === '' ? '未选择——合成需要一段 3~10 秒人声' : value}
      </span>
    </span>
  );
}
