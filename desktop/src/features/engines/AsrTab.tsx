/**
 * 语音识别 ASR tab：当前生效卡（本地模型 / 云端配置混排切换）→「本地模型 | 云端配置」分段资产库。
 * 云端生效时参数换形（计费 / 上次连通替换运行设备 / 磁盘实占），判据永远是设置与配置表，前端不写死。
 */
import { Button } from 'antd';
import { useState } from 'react';
import type { DefaultOptionType } from 'antd/es/select';
import type { ReactElement } from 'react';
import type { EngineConfig, ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { PageSection } from '../../components/layout/PageKit';
import type { DomainTabProps } from './EnginesPage';
import type { Reports } from './assetState';
import {
  activateSettings,
  activeAsset,
  activeStateNote,
  assetState,
  canActivate,
  externalAssets,
  formatBytes,
  reportFor,
} from './assetState';
import { type ActiveCardProps, ActiveEngineCard } from './ActiveEngineCard';
import { AssetLibrary } from './AssetLibrary';
import {
  CloudConfigsPane,
  CloudSegment,
  CloudTestButton,
  MixedEnginePicker,
  activeCloudConfig,
} from './CloudDomainUI';
import { SettingSelect } from './SettingSelect';
import { useDownloadProgress } from './useDownloadProgress';
import { useEngineConfigs } from './useEngineConfigs';

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
  {
    key: 'asr.diarization',
    label: '说话人分离',
    options: [
      { label: '自动（按引擎能力）', value: 'auto' },
      { label: '强制开启', value: 'true' },
      { label: '关闭', value: 'false' },
    ],
  },
];

const CLOUD_NOTE =
  '云端转写按「配置」接入：可添加多个服务商与模型，同一时刻启用一条，切换即改生效引擎。'
  + '密钥只存本机数据库、界面脱敏显示，分析日志与导出物不含密钥；未测通的配置可以保存，但启用前建议先测连接。';

export function AsrTab({
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
  const cloud = useEngineConfigs('asr_cloud', onChanged);
  const [pane, setPane] = useState<'local' | 'cloud'>('local');
  const activeCloud = activeCloudConfig(cloud.configs);
  const domainModels = models.filter((model) => model.kind === 'asr');
  const active = activeAsset(models, 'asr', settings);
  const segment = <CloudSegment value={pane} onChange={setPane} />;
  const pickCloud = (config: EngineConfig): void => {
    cloud.enable(config);
  };
  const pickLocal = (model: ModelInfo): void => {
    cloud
      .enableLocal()
      .catch(() => undefined)
      .finally(() => {
        onSave(activateSettings(model));
      });
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      {activeCloud !== undefined ? (
        <ActiveEngineCard
          domain="语音识别 ASR"
          title={activeCloud.name}
          state={null}
          hint={`云端转写 · 按量计费 · 模型 ${activeCloud.model}`}
          picker={
            <MixedEnginePicker
              width={210}
              localValue={active?.model_id ?? ''}
              localOptions={domainModels.map((model) => ({
                label: model.name,
                value: model.model_id,
                disabled: !canActivate(model, reportFor(reports, model.model_id)),
              }))}
              configs={cloud.configs}
              onPickLocal={(value) => {
                const picked = domainModels.find((model) => model.model_id === value);
                if (picked !== undefined) pickLocal(picked);
              }}
              onPickCloud={pickCloud}
            />
          }
          actions={<CloudTestButton config={activeCloud} domain="asr_cloud" />}
          props={[
            ...paramProps(settings, onSave, ['asr.language', 'asr.diarization']),
            { label: '接口地址', value: activeCloud.base_url === '' ? '服务商标准端点' : activeCloud.base_url },
            { label: '密钥', value: activeCloud.api_key_masked },
            { label: '生效时机', value: '保存后下次分析' },
          ]}
          footnote="云端转写免下载免显存，按音频时长计费（转写为异步任务，耗时与音频时长同量级）；切回本地模型用上方下拉选「本地模型」分组。"
        />
      ) : (
        <ActiveCard
          models={domainModels}
          active={active}
          settings={settings}
          reports={reports}
          selftests={selftests}
          onSave={onSave}
          onVerify={onVerify}
          configs={cloud.configs}
          onPickCloud={pickCloud}
        />
      )}
      {pane === 'local' ? (
        <AssetLibrary
          models={domainModels}
          externals={externalAssets(imported, 'asr')}
          importError={importError}
          reports={reports}
          selftests={selftests}
          specs={machine}
          activeModelId={active?.model_id}
          onActivate={pickLocal}
          onChanged={onChanged}
          onVerify={onVerify}
          onForget={onForget}
          onImport={onImport}
          segment={segment}
        />
      ) : (
        <PageSection title="云端配置" extra={segment}>
          <CloudConfigsPane domain="asr_cloud" actions={cloud} onChanged={onChanged} note={CLOUD_NOTE} />
        </PageSection>
      )}
    </div>
  );
}

function ActiveCard({
  models,
  active,
  settings,
  reports,
  selftests,
  onSave,
  onVerify,
  configs,
  onPickCloud,
}: {
  models: readonly ModelInfo[];
  active: ModelInfo | undefined;
  settings: DomainTabProps['settings'];
  reports: Reports;
  selftests: DomainTabProps['selftests'];
  onSave: DomainTabProps['onSave'];
  onVerify: DomainTabProps['onVerify'];
  configs: readonly EngineConfig[];
  onPickCloud: (config: EngineConfig) => void;
}): ReactElement {
  const report = active === undefined ? undefined : reportFor(reports, active.model_id);
  const state = active === undefined ? null : assetState(active, report, selftests?.[active.model_id]);
  const card: ActiveCardProps = {
    domain: '语音识别 ASR',
    title: active?.name ?? '未选择模型',
    state,
    hint: '设置里没有可用的识别模型，去下方资产库选一个；或切「云端配置」接云端转写',
    stateNote: state === null ? undefined : activeStateNote(state, report),
    progress: useDownloadProgress(active),
    picker: (
      <MixedEnginePicker
        width={210}
        localValue={active?.model_id}
        localOptions={models.map((model) => ({
          label: model.name,
          value: model.model_id,
          disabled: !canActivate(model, reportFor(reports, model.model_id)),
        }))}
        configs={configs}
        onPickLocal={(value) => {
          const picked = models.find((model) => model.model_id === value);
          if (picked !== undefined) onSave(activateSettings(picked));
        }}
        onPickCloud={onPickCloud}
      />
    ),
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
      ...paramProps(settings, onSave, ['asr.device', 'asr.language', 'asr.diarization']),
      { label: '磁盘实占', value: active === undefined ? '—' : formatBytes(active.size_bytes ?? 0) },
      { label: '生效时机', value: '保存后下次分析' },
    ],
    footnote: '「自动」＝检测到可用 GPU 即启用，否则回退 CPU；显卡与运行库的实际情况见「环境」段的转写加速卡。',
  };
  return <ActiveEngineCard {...card} />;
}

function paramProps(
  settings: DomainTabProps['settings'],
  onSave: DomainTabProps['onSave'],
  keys: readonly string[],
): ActiveCardProps['props'] {
  return PARAMS.filter((param) => keys.includes(param.key)).map((param) => ({
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
