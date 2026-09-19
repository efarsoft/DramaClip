/**
 * 语音识别 ASR：当前生效卡（参数即改即存 + 该模型的安装态内联）→ 转写加速卡 → 资产库。
 *
 * P6 的修法是结构性的：选择与安装态同在一张卡上，不再一个在页首、一个在页尾。
 * 设备语义归本 tab 的「转写加速」卡，容量语义归总览的「本机运行条件」卡（P7）。
 */
import { Button } from 'antd';
import type { DefaultOptionType } from 'antd/es/select';
import type { ReactElement } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { GpuCard } from './GpuCard';
import { useGpuInfo } from './useGpuInfo';
import type { DomainTabProps } from './EnginesPage';
import type { Reports } from './assetState';
import {
  activateSettings,
  activeAsset,
  assetState,
  canActivate,
  failureNote,
  formatBytes,
  reportFor,
} from './assetState';
import { type ActiveCardProps, type ActiveProp, ActiveEngineCard } from './ActiveEngineCard';
import { AssetLibrary } from './AssetLibrary';
import { SettingSelect } from './SettingSelect';
import { useDownloadProgress } from './useDownloadProgress';

const PARAMS: readonly { key: string; label: string; options: DefaultOptionType[] }[] = [
  {
    key: 'asr.device',
    label: '运行设备',
    options: [
      { label: '自动（检测 GPU）', value: 'auto' },
      { label: 'CPU', value: 'cpu' },
      { label: 'CUDA（NVIDIA）', value: 'cuda' },
    ],
  },
  {
    key: 'asr.language',
    label: '识别语言',
    options: [
      { label: '中文', value: 'zh' },
      { label: '英文', value: 'en' },
    ],
  },
];

export function AsrTab({
  models,
  settings,
  reports,
  machine,
  onSave,
  onChanged,
  onVerify,
}: DomainTabProps): ReactElement {
  const { info: gpu, refresh } = useGpuInfo();
  const domainModels = models.filter((model) => model.kind === 'asr');
  const active = activeAsset(models, 'asr', settings);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <ActiveCard
        models={domainModels}
        active={active}
        settings={settings}
        reports={reports}
        onSave={onSave}
        onVerify={onVerify}
      />
      <GpuCard info={gpu} device={settings['asr.device'] ?? 'auto'} onRefresh={refresh} />
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
  models,
  active,
  settings,
  reports,
  onSave,
  onVerify,
}: {
  models: readonly ModelInfo[];
  active: ModelInfo | undefined;
  settings: DomainTabProps['settings'];
  reports: Reports;
  onSave: DomainTabProps['onSave'];
  onVerify: DomainTabProps['onVerify'];
}): ReactElement {
  const report = active === undefined ? undefined : reportFor(reports, active.model_id);
  const card: ActiveCardProps = {
    domain: '语音识别 ASR',
    title: active?.name ?? '未选择模型',
    state: active === undefined ? null : assetState(active, report),
    hint: '设置里没有可用的识别模型，去下方资产库选一个',
    stateNote: failureNote(report),
    progress: useDownloadProgress(active),
    picker: <ModelPicker models={models} reports={reports} value={active?.model_id} onSave={onSave} />,
    actions:
      active === undefined ? undefined : (
        <Button
          size="small"
          onClick={() => {
            onVerify(active.model_id);
          }}
        >
          校验资产
        </Button>
      ),
    props: [
      ...paramProps(settings, onSave),
      { label: '磁盘实占', value: active === undefined ? '—' : formatBytes(active.size_bytes ?? 0) },
      { label: '生效时机', value: '保存后下次分析' },
    ],
    footnote: '「自动」＝检测到可用 GPU 即启用，否则回退 CPU；显卡与运行库的实际情况见下方转写加速卡。',
  };
  return <ActiveEngineCard {...card} />;
}

/** 换模型下拉：坏掉的资产直接禁选，理由在卡上的状态与资产库的体检里说。 */
function ModelPicker({
  models,
  reports,
  value,
  onSave,
}: {
  models: readonly ModelInfo[];
  reports: Reports;
  value: string | undefined;
  onSave: DomainTabProps['onSave'];
}): ReactElement {
  return (
    <SettingSelect
      variant="outlined"
      width={190}
      placeholder="更换模型"
      value={value}
      options={models.map((model) => ({
        label: model.name,
        value: model.model_id,
        disabled: !canActivate(model, reportFor(reports, model.model_id)),
      }))}
      onChange={(modelId: string) => {
        const picked = models.find((model) => model.model_id === modelId);
        if (picked !== undefined) onSave(activateSettings(picked));
      }}
    />
  );
}

function paramProps(settings: DomainTabProps['settings'], onSave: DomainTabProps['onSave']): ActiveProp[] {
  return PARAMS.map((param) => ({
    label: param.label,
    value: (
      <SettingSelect
        value={settings[param.key] ?? ''}
        options={param.options}
        onChange={(value: string) => {
          onSave({ [param.key]: value });
        }}
      />
    ),
  }));
}
