/**
 * 配音 TTS：当前生效卡（引擎切换 + 音色 + 该引擎模型的安装态内联）→ 资产库。
 * 状态一律以 models.list 的 engine_ready/status 与 models.verify 的结论为准，前端不写死；
 * 免模型的云端引擎单独走「无需本地模型」说明，不冒充体检结果。
 */
import { Button } from 'antd';
import { useState } from 'react';
import type { ReactElement } from 'react';
import type { EngineConfig, ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { PageSection } from '../../components/layout/PageKit';
import type { DomainTabProps } from './EnginesPage';
import type { AssetState, Reports } from './assetState';
import { localDomainModels,
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
import {
  CloudConfigsPane,
  CloudSegment,
  CloudTestButton,
  MixedEnginePicker,
  activeCloudConfig,
} from './CloudDomainUI';
import { LocalRuntimeSlot } from './LocalRuntimeSlot';
import { deviceSelectProps } from './deviceOptions';
import type { MachineSpecs } from './machineFit';
import { AutoVoiceButton } from './AutoVoiceButton';
import { RefCleanButton } from './RefCleanButton';
import { RefVoiceSelect } from './RefVoiceSelect';
import { SettingSelect } from './SettingSelect';
import { TtsPreviewButton } from './TtsPreviewButton';
import { previewNotice } from './ttsPreview';
import { useDownloadProgress } from './useDownloadProgress';
import { useEngineConfigs } from './useEngineConfigs';
import { CloudNudgeCard } from './CloudNudgeCard';
import { cloudRecommendation } from './cloudRecommend';
import { useLocalRuntime } from './useLocalRuntime';
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
  cosyvoice_cloud: '云端 · 百炼按量计费',
};

const VOICE_HINT: Record<string, string> = {
  kokoro: 'Kokoro 提供 100 个中文音色（55 女 + 45 男），下拉可搜索',
  edge: '微软官方中文音色，覆盖普通话 / 东北 / 陕西 / 粤语 / 台湾',
  indextts2: '零样本克隆：选一段 3~10 秒干净人声做音色（如剧集主角台词）；截自剧集的参考带 BGM，先点「人声分离」',
  cosyvoice_cloud: '百炼预置音色，下拉可换；克隆音色在百炼控制台创建后把 id 填进自定义',
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
  const cloud = useEngineConfigs('tts_cloud', onChanged);
  const [pane, setPane] = useState<'local' | 'cloud'>('local');
  const activeCloud = activeCloudConfig(cloud.configs);
  const recommendation = cloudRecommendation(machine.gpu, cloud.configs);
  const engine = settings['tts.engine'] ?? '';
  const domainModels = localDomainModels(models, 'tts');
  const active = isModelFreeEngine(engine) ? undefined : activeAsset(models, 'tts', settings);
  const segment = <CloudSegment value={pane} onChange={setPane} />;
  const pickCloud = (config: EngineConfig): void => {
    cloud.enable(config);
  };
  const pickLocalEngine = (name: string): void => {
    cloud
      .enableLocal()
      .catch(() => undefined)
      .finally(() => {
        onSave({ 'tts.engine': name });
      });
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      {recommendation !== 'none' ? (
        <CloudNudgeCard domain="tts" kind={recommendation} onGoCloud={() => { setPane('cloud'); }} />
      ) : null}
      {activeCloud !== undefined ? (
        <CloudActiveCard
          config={activeCloud}
          settings={settings}
          configs={cloud.configs}
          onSave={onSave}
          onPickLocalEngine={pickLocalEngine}
          onPickCloud={pickCloud}
        />
      ) : (
        <ActiveCard
          active={active}
          engine={engine}
          settings={settings}
          reports={reports}
          selftests={selftests}
          machine={machine}
          onSave={onSave}
          onChanged={onChanged}
          onVerify={onVerify}
          configs={cloud.configs}
          onPickCloud={pickCloud}
        />
      )}
      {/* IndexTTS 运行环境安装槽：配音页固定显示（业主裁决 2026-09-24）——入口可见性
          不该押在「先切到 indextts2」上，资产库那行的试听/选为生效随时会撞上它。
          判据仍是 models.indextts_status：装好后槽自己消失，不是常驻横幅。
          2~6GB 的独立 Python + torch 不悄悄装——「选为生效」不代装，给显式一键引导，
          试听/自检/导出的失败文案指的就是这扇门（曾经只有文案没有门）。 */}
      <LocalRuntimeSlot scope="tts" />
      {pane === 'local' ? (
        <AssetLibrary
          models={domainModels}
          externals={externalAssets(imported, 'tts')}
          importError={importError}
          reports={reports}
          selftests={selftests}
          specs={machine}
          activeModelId={active?.model_id}
          onActivate={(model) => {
            pickLocalEngine(activateSettings(model)['tts.engine'] ?? model.engine);
          }}
          onChanged={onChanged}
          onVerify={onVerify}
          onForget={onForget}
          onImport={onImport}
          renderPreview={previewRenderer(settings, reports)}
          segment={segment}
        />
      ) : (
        <PageSectionCloud
          segment={segment}
          actions={cloud}
          onChanged={onChanged}
          note="云端合成按「配置」接入：可添加多个服务商与模型，同一时刻启用一条，切换即改生效引擎。密钥只存本机数据库、界面脱敏显示；未测通的配置可以保存，但启用前建议先测连接。"
        />
      )}
    </div>
  );
}
/** 云端生效卡：配音走启用中的云端配置；音色行沿用按引擎键（tts.voice.cosyvoice_cloud）。 */
function CloudActiveCard({
  config,
  settings,
  configs,
  onSave,
  onPickLocalEngine,
  onPickCloud,
}: {
  config: EngineConfig;
  settings: DomainTabProps['settings'];
  configs: readonly EngineConfig[];
  onSave: DomainTabProps['onSave'];
  onPickLocalEngine: (name: string) => void;
  onPickCloud: (config: EngineConfig) => void;
}): ReactElement {
  const engine = 'cosyvoice_cloud';
  const voice = settings[voiceSettingKey(engine)] ?? '';
  const card: ActiveCardProps = {
    domain: '配音 TTS',
    title: config.name,
    state: null,
    hint: `云端合成 · 按量计费 · 模型 ${config.model}`,
    picker: (
      <MixedEnginePicker
        localValue=""
        localOptions={TTS_ENGINES.map((name) => ({ label: ttsEngineLabel(name), value: name }))}
        configs={configs}
        onPickLocal={onPickLocalEngine}
        onPickCloud={onPickCloud}
      />
    ),
    actions: <CloudTestButton config={config} domain="tts_cloud" />,
    props: [
      {
        label: '音色',
        value: (
          <span style={{ display: 'inline-flex', alignItems: 'flex-start', gap: tokens.spaceSm }}>
            <VoiceSelect engine={engine} settings={settings} onSave={onSave} model={config.model} />
            <TtsPreviewButton engine={engine} voice={voice} blocked={undefined} />
          </span>
        ),
      },
      { label: '接口地址', value: config.base_url === '' ? '服务商标准端点' : config.base_url },
      { label: '密钥', value: config.api_key_masked },
      { label: '生效时机', value: '保存后下次任务' },
    ],
    footnote: `${VOICE_HINT[engine] ?? ''} · 切回本地模型用上方下拉选「本地模型」分组`,
  };
  return <ActiveEngineCard {...card} />;
}

/** 云端配置段的卡片外壳（与资产库同一张卡型，分段控件常驻卡头）。 */
function PageSectionCloud({
  segment,
  actions,
  onChanged,
  note,
}: {
  segment: ReactElement;
  actions: ReturnType<typeof useEngineConfigs>;
  onChanged: () => void;
  note: string;
}): ReactElement {
  return (
    <PageSection title="云端配置" extra={segment}>
      <CloudConfigsPane domain="tts_cloud" actions={actions} onChanged={onChanged} note={note} />
    </PageSection>
  );
}

/** 行内试听节点：音色取该引擎自己的设置值，放行判断只挡「必然听不到」的确定情况。 */
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
  machine,
  onSave,
  onChanged,
  onVerify,
  configs,
  onPickCloud,
}: {
  active: ModelInfo | undefined;
  engine: string;
  settings: DomainTabProps['settings'];
  reports: Reports;
  selftests: DomainTabProps['selftests'];
  machine: MachineSpecs;
  onSave: DomainTabProps['onSave'];
  onChanged: () => void;
  onVerify: DomainTabProps['onVerify'];
  configs: readonly EngineConfig[];
  onPickCloud: (config: EngineConfig) => void;
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
      <MixedEnginePicker
        localValue={engine}
        localOptions={TTS_ENGINES.map((name) => ({ label: ttsEngineLabel(name), value: name }))}
        configs={configs}
        onPickLocal={(value) => {
          onSave({ 'tts.engine': value });
        }}
        onPickCloud={onPickCloud}
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
      ...(engine === 'indextts2'
        ? [{ label: '人声分离', value: <SeparationBackendNote machine={machine} /> }]
        : []),
      // 云端引擎不看本机设备；只有本地引擎才摆这一行，避免「选了 CUDA 却走云端」的假选择。
      ...(engine === 'edge' || engine === 'cosyvoice_cloud'
        ? []
        : [{
            label: '运行设备',
            value: (
              <SettingSelect
                value={settings['tts.device'] ?? ''}
                options={deviceSelectProps({ engine, saved: settings['tts.device'] ?? 'auto', machine }).options}
                onChange={(value: string) => {
                  onSave({ 'tts.device': value });
                }}
              />
            ),
          }]),
      { label: '引擎类型', value: ENGINE_KIND_LABEL[engine] ?? '未登记引擎' },
      { label: '磁盘实占', value: active === undefined ? '—' : formatBytes(active.size_bytes ?? 0) },
      { label: '生效时机', value: '保存后下次任务' },
    ],
    footnote: `${VOICE_HINT[engine] ?? '换引擎后各自的音色互不覆盖'} · 试听是引擎原声，成片还要过响度归一`,
  };
  return <ActiveEngineCard {...card} />;
}

/** 分离后端只报安装期探测到的事实；实际任务用哪条路由清洗回执再确认。 */
export function SeparationBackendNote({ machine }: { machine: MachineSpecs }): ReactElement | null {
  const { installed, ortGpu, install } = useLocalRuntime();
  if (installed === null) return null;
  const style = { color: tokens.textSecondary, fontSize: tokens.text.meta.size };
  if (!installed) {
    return <span style={style}>运行环境未安装——人声分离暂不可用</span>;
  }
  // 宿主事实决定「重跑安装」有没有意义：非 NVIDIA 主机装了也不会启用 CUDA EP。
  const hostMayHaveCuda =
    machine.gpu === undefined ||
    !machine.gpu.ready ||
    machine.gpu.vendor === 'nvidia' ||
    machine.gpu.vendor === 'unknown';
  const retry = ortGpu === null || (!ortGpu.gpu && hostMayHaveCuda);
  const retryButton = retry ? (
    <Button
      size="small"
      type="link"
      style={{ padding: 0, height: 'auto' }}
      onClick={install}
    >
      重跑安装
    </Button>
  ) : null;
  if (ortGpu === null) {
    return (
      <span style={style}>
        ONNX Runtime 后端未探测：重跑本地运行环境安装
        {retryButton}
      </span>
    );
  }
  if (ortGpu.gpu) {
    const provider = ortGpu.providers[0] ?? 'CUDAExecutionProvider';
    return (
      <span style={style}>
        {`GPU（${provider}${ortGpu.version === '' ? '' : `，ORT ${ortGpu.version}`}）`}
      </span>
    );
  }
  return (
    <span style={style}>
      {`CPU${ortGpu.reason === '' ? '' : ` · ${ortGpu.reason}`}`}
      {retryButton}
    </span>
  );
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
        <AutoVoiceButton
          onSave={(voicePath) => {
            onSave({ [voiceSettingKey(engine)]: voicePath });
          }}
        />
        <RefVoiceSelect settings={settings} onSave={onSave} />
        {voice !== '' && (
          <RefCleanButton
            path={voice}
            onCleaned={(path) => {
              onSave({ [voiceSettingKey(engine)]: path });
            }}
          />
        )}
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
  model = '',
}: {
  engine: string;
  settings: DomainTabProps['settings'];
  onSave: DomainTabProps['onSave'];
  model?: string;
}): ReactElement {
  const key = voiceSettingKey(engine);
  return (
    <SettingSelect
      value={settings[key] ?? ''}
      options={voiceOptions(engine, model)}
      searchable={engine === 'kokoro'}
      onChange={(value: string) => {
        onSave({ [key]: value });
      }}
    />
  );
}
