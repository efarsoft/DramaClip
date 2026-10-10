/**
 * 画面理解 VL tab：生效档位卡（选档即写 vision.model）+ 三档资产库。
 * 管理与运行均已接线：下载/校验/选档就地完成，下次分析生效；
 * llama-server 缺失或模型未装时分析按分档跳过视觉轨（warn 留痕，不挡出片）。
 */
import { Button } from 'antd';
import type { ReactElement } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import type { DomainTabProps } from './EnginesPage';
import type { Reports } from './assetState';
import {
  activeStateNote,
  assetState,
  canActivate,
  externalAssets,
  formatBytes,
  reportFor,
} from './assetState';
import { type ActiveCardProps, ActiveEngineCard } from './ActiveEngineCard';
import { AssetLibrary } from './AssetLibrary';
import { SettingSelect } from './SettingSelect';
import { useDownloadProgress } from './useDownloadProgress';

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
  const domainModels = models.filter((model) => model.kind === 'vision');
  const active = domainModels.find((model) => model.model_id === settings['vision.model']);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <ActiveCard
        models={domainModels}
        active={active}
        reports={reports}
        selftests={selftests}
        onSave={onSave}
        onVerify={onVerify}
      />
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
      />
    </div>
  );
}

function ActiveCard({
  models,
  active,
  reports,
  selftests,
  onSave,
  onVerify,
}: {
  models: readonly ModelInfo[];
  active: ModelInfo | undefined;
  reports: Reports;
  selftests: DomainTabProps['selftests'];
  onSave: DomainTabProps['onSave'];
  onVerify: DomainTabProps['onVerify'];
}): ReactElement {
  const report = active === undefined ? undefined : reportFor(reports, active.model_id);
  const state = active === undefined ? null : assetState(active, report, selftests?.[active.model_id]);
  const card: ActiveCardProps = {
    domain: '画面理解 VL',
    title: active?.name ?? '未启用（视觉轨关闭）',
    state,
    hint: '设置里没有生效档位——下方资产库选一档即启用；关闭即回到纯台词解说',
    stateNote: state === null ? undefined : activeStateNote(state, report),
    progress: useDownloadProgress(active),
    picker: <TierPicker models={models} reports={reports} value={active?.model_id} onSave={onSave} />,
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
      { label: '磁盘实占', value: active === undefined ? '—' : formatBytes(active.size_bytes ?? 0) },
      { label: '生效时机', value: '保存后下次分析' },
    ],
    footnote:
      'CPU 实测（拼图 16 帧/集）：2B 约 2.5 分钟、4B 约 5.4 分钟、8B 约 6.6 分钟；'
      + '8B 质量最佳（龙袍/帝王级识别）仅比 4B 慢 25%，32GB+ 内存建议直接上 8B。',
  };
  return <ActiveEngineCard {...card} />;
}

/** 换档下拉：坏掉的资产直接禁选，理由在卡上的状态与资产库的体检里说。 */
function TierPicker({
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
      placeholder="选择档位（含关闭）"
      value={value}
      options={[
        { label: '关闭视觉轨', value: '' },
        ...models.map((model) => ({
          label: model.name,
          value: model.model_id,
          disabled: !canActivate(model, reportFor(reports, model.model_id)),
        })),
      ]}
      onChange={(modelId: string) => {
        onSave({ 'vision.model': modelId });
      }}
    />
  );
}
