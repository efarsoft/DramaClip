/**
 * 环境段（§10.4 第 6 段）：转写加速 GPU 卡 + 本机运行条件。
 * 归属纪律：home/EnvPanel 是工作台右栏，不搬进来（§9 非目标——搬它 = 动工作台）；
 * 两处行数据同源（system.health / gpu_info），本段只呈现引擎视角 + 修复入口。
 */
import type { ReactElement } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { GpuCard } from './GpuCard';
import { MachinePanel } from './MachinePanel';
import { useGpuInfo } from './useGpuInfo';
import type { SettingsMap } from './EnginesPage';

export function EnvSection({
  models,
  settings,
}: {
  models: readonly ModelInfo[];
  settings: SettingsMap;
}): ReactElement {
  const { info, refresh } = useGpuInfo();
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.2fr)',
        gap: tokens.spaceLg,
        alignItems: 'start',
      }}
    >
      <GpuCard info={info} device={settings['asr.device'] ?? 'auto'} onRefresh={refresh} />
      <MachinePanel models={models} />
    </div>
  );
}
