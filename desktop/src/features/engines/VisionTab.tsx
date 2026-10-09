/**
 * 画面理解 VL tab（管理先行）：三档 Qwen3-VL 资产库——下载/校验/导入就地管，
 * 运行接入在视觉轨 P2b 收尾时接上（本机 CPU 实测 4B 一张拼图约 15~30 秒）。
 * 域内暂无「生效卡」：激活语义（写 settings 供分析取用）随运行接入一起到。
 */
import { Alert } from 'antd';
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';
import type { DomainTabProps } from './EnginesPage';
import { externalAssets } from './assetState';
import { AssetLibrary } from './AssetLibrary';

export function VisionTab({
  models,
  imported,
  importError,
  reports,
  selftests,
  machine,
  onChanged,
  onVerify,
  onForget,
  onImport,
}: DomainTabProps): ReactElement {
  const domainModels = models.filter((model) => model.kind === 'vision');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <Alert
        type="info"
        showIcon
        title="管理先行：三档模型（轻量 2B / 均衡 4B / 高配 8B）可先下载储备；画面理解的运行接入随视觉轨 P2b 收尾接上，接上后在本页选生效档位"
      />
      <AssetLibrary
        models={domainModels}
        externals={externalAssets(imported, 'vision')}
        importError={importError}
        reports={reports}
        selftests={selftests}
        specs={machine}
        activeModelId={undefined}
        onActivate={() => undefined}
        onChanged={onChanged}
        onVerify={onVerify}
        onForget={onForget}
        onImport={onImport}
      />
    </div>
  );
}
