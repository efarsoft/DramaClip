/**
 * 画面理解 VL tab：生效档位卡（本地档=选档写 vision.model，云端配置启用走 vision.cloud*）
 * + 「本地模型 | 云端配置」分段资产库。
 * 管理与运行均已接线：下载/校验/选档就地完成，下次分析生效；
 * llama-server 缺失或模型未装时分析按分档跳过视觉轨（warn 留痕，不挡出片）。
 */
import { Button } from 'antd';
import { useState } from 'react';
import type { ReactElement } from 'react';
import type { EngineConfig, ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { PageSection } from '../../components/layout/PageKit';
import type { DomainTabProps } from './EnginesPage';
import type { Reports } from './assetState';
import {
  cardStateNote,
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
import { deviceSelectProps, visualCapKey } from './deviceOptions';
import { LlamaRuntimeSlot } from './LlamaRuntimeSlot';
import { SettingSelect } from './SettingSelect';
import { useDownloadState } from './useDownloadProgress';
import { useEngineConfigs } from './useEngineConfigs';

export function VisionTab({
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
  const cloud = useEngineConfigs('image', onChanged);
  const [pane, setPane] = useState<'local' | 'cloud'>('local');
  const activeCloud = activeCloudConfig(cloud.configs);
  const domainModels = models.filter((model) => model.kind === 'vision');
  const active = domainModels.find((model) => model.model_id === settings['vision.model']);
  const segment = <CloudSegment value={pane} onChange={setPane} />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      {activeCloud !== undefined ? (
        <ActiveEngineCard
          domain="画面理解 VL"
          title={activeCloud.name}
          state={null}
          hint={`云端视觉 · 按 token 计费 · 模型 ${activeCloud.model}`}
          picker={
            <MixedEnginePicker
              localValue=""
              width={210}
              localOptions={[
                { label: '关闭视觉轨', value: '__off__' },
                ...models
                  .filter((model) => model.kind === 'vision')
                  .map((model) => ({
                    label: model.name,
                    value: model.model_id,
                    disabled: !canActivate(model, reportFor(reports, model.model_id)),
                  })),
              ]}
              configs={cloud.configs}
              onPickLocal={(value) => {
                cloud
                  .enableLocal()
                  .then(() => {
                    onSave(
                      value === '__off__'
                        ? { 'vision.cloud': '', 'vision.model': '' }
                        : { 'vision.cloud': '', 'vision.model': value },
                    );
                  })
                  .catch(() => undefined);
              }}
              onPickCloud={(picked: EngineConfig) => {
                cloud.enable(picked);
              }}
            />
          }
          actions={<CloudTestButton config={activeCloud} domain="image" />}
          props={[
            { label: '接口地址', value: activeCloud.base_url },
            { label: '密钥', value: activeCloud.api_key_masked },
            { label: '生效时机', value: '保存后下次分析' },
          ]}
          footnote="云端视觉免下载免显存，按帧组发多图请求、按 token 计费；切回本地档位用上方下拉选「本地模型」分组。"
        />
      ) : (
        <ActiveCard
          models={domainModels}
          active={active}
          reports={reports}
          selftests={selftests}
          settings={settings}
          machine={machine}
          onSave={onSave}
          onVerify={onVerify}
          configs={cloud.configs}
          onPickCloud={(picked: EngineConfig) => {
            cloud.enable(picked);
          }}
        />
      )}
      {pane === 'local' && <LlamaRuntimeSlot />}
      {pane === 'local' ? (
        <AssetLibrary
          models={domainModels}
          externals={externalAssets(imported, 'vision')}
          importError={importError}
          reports={reports}
          selftests={selftests}
          specs={machine}
          activeModelId={active?.model_id}
          onActivate={(model) => {
            onSave({ 'vision.model': model.model_id });
          }}
          onChanged={onChanged}
          onVerify={onVerify}
          onForget={onForget}
          onImport={onImport}
          segment={segment}
        />
      ) : (
        <PageSection title="云端配置" extra={segment}>
          <CloudConfigsPane
            domain="image"
            actions={cloud}
            onChanged={onChanged}
            note="云端视觉按「配置」接入：可添加多个服务商与模型，同一时刻启用一条，切换即改生效引擎。密钥只存本机数据库、界面脱敏显示；未测通的配置可以保存，但启用前建议先测连接。"
          />
        </PageSection>
      )}
    </div>
  );
}

function ActiveCard({
  models,
  active,
  reports,
  selftests,
  settings,
  machine,
  onSave,
  onVerify,
  configs,
  onPickCloud,
}: {
  models: readonly ModelInfo[];
  active: ModelInfo | undefined;
  reports: Reports;
  selftests: DomainTabProps['selftests'];
  settings: DomainTabProps['settings'];
  machine: DomainTabProps['machine'];
  onSave: DomainTabProps['onSave'];
  onVerify: DomainTabProps['onVerify'];
  configs: readonly EngineConfig[];
  onPickCloud: (config: EngineConfig) => void;
}): ReactElement {
  const report = active === undefined ? undefined : reportFor(reports, active.model_id);
  const state = active === undefined ? null : assetState(active, report, selftests?.[active.model_id]);
  const download = useDownloadState(active);
  const device = settings['vision.device'] ?? 'auto';
  const card: ActiveCardProps = {
    domain: '画面理解 VL',
    title: active?.name ?? '未启用（视觉轨关闭）',
    state,
    hint: '设置里没有生效档位——下方资产库选一档即启用；关闭即回到纯台词解说',
    stateNote: cardStateNote(state, report, download),
    progress: download?.status === 'downloading' ? download.percent : undefined,
    picker: (
      <MixedEnginePicker
        width={210}
        localValue={active?.model_id ?? ''}
        localOptions={[
          { label: '关闭视觉轨', value: '__off__' },
          ...models.map((model) => ({
            label: model.name,
            value: model.model_id,
            disabled: !canActivate(model, reportFor(reports, model.model_id)),
          })),
        ]}
        configs={configs}
        onPickLocal={(value) => {
          onSave(
            value === '__off__'
              ? { 'vision.model': '' }
              : { 'vision.model': value },
          );
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
      ...(active === undefined
        ? []
        : [
            {
              label: '运行设备',
              value: (
                <SettingSelect
                  value={device}
                  options={
                    deviceSelectProps({
                      engine: active.engine,
                      capKey: visualCapKey(active.model_id),
                      saved: device,
                      machine,
                    }).options
                  }
                  onChange={(value: string) => {
                    onSave({ 'vision.device': value });
                  }}
                />
              ),
            },
          ]),
      { label: '磁盘实占', value: active === undefined ? '—' : active.size_bytes === undefined || active.size_bytes === null ? '统计中…' : formatBytes(active.size_bytes) },
      { label: '生效时机', value: '保存后下次分析' },
    ],
    footnote:
      '4B 实测（2 分钟竖屏集，16 帧分 4 组）：CPU 约 14 分钟/集；Quadro M4000 整模型卸载 4.5~5.5 分钟/集'
      + '（该测试卡散热差，过热降频会更慢）。「自动」＝llama.cpp 带 CUDA 构建、CUDA 运行库已装且显存够'
      + '（约模型体积 + 2.5GB）才卸载，起不来回退 CPU 并在任务回执里写明原因；「CUDA」是承诺，失败即报错不静默换 CPU。',
  };
  return <ActiveEngineCard {...card} />;
}
