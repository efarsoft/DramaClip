/** GPU 加速状态卡：显卡 / 驱动 / CUDA 上限 + 加速方式说明（ASR 转写用）。 */
import type { ReactElement } from 'react';
import { Button, Tooltip } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { GpuInfo } from '@dramaclip/protocol';
import { runtimeApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { useEnvStatus, type EnvStatus } from './runtimeState';

/**
 * 出词口径：卡型可得（`gpu_info`）**不等于**转写能走 GPU——还差 CUDA 运行库这一件。
 * 运行库状态取自与「本机运行条件」卡同一个 hook：同屏两张卡不许对同一件事说相反的话，
 * 所以这里只报状态、不放下载按钮（那枚按钮在运行环境那一行，全站唯一入口）。
 */
function statusOf(info: GpuInfo | null, device: string, runtime: EnvStatus): { text: string; color: string } {
  if (!info?.ready) {
    return { text: '检测中…', color: tokens.textTertiary };
  }
  if (info.vendor !== 'nvidia') {
    // 只有 none 才是「没有显卡」；amd/intel/other 有卡，只是不满足 CUDA 这一条
    return info.vendor === 'none'
      ? { text: '未检测到独立显卡 · 转写将以 CPU 运行', color: tokens.textSecondary }
      : { text: '未检测到 NVIDIA 显卡 · 转写将以 CPU 运行', color: tokens.textSecondary };
  }
  if (runtime === 'loading') {
    return { text: '显卡在位 · CUDA 运行库状态检测中…', color: tokens.textTertiary };
  }
  if (runtime === 'unknown') {
    return { text: 'CUDA 运行库状态未知 · 暂按 CPU 运行', color: tokens.textTertiary };
  }
  if (runtime === 'missing') {
    return { text: 'CUDA 运行库未安装 · 转写当前走 CPU', color: tokens.colorWarning };
  }
  if (device === 'cpu') {
    return {
      text: '已就绪 · 当前运行设备为 CPU，将运行设备切换为「自动」即可启用 GPU 加速',
      color: tokens.colorWarning,
    };
  }
  return {
    text: '已就绪 · CUDA 运行库已装 · 转写可用 GPU 加速',
    color: tokens.colorSuccess,
  };
}

/** 硬编口径按厂商点名：AI 加速仍只认 CUDA，视频导出由导出时真试编决定。 */
function encodeNote(vendor: GpuInfo['vendor']): string {
  if (vendor === 'amd') return '视频导出可用 AMD 硬件编码（AMF，导出时真试编）';
  if (vendor === 'intel') return '视频导出可用 Intel 硬件编码（QSV，导出时真试编）';
  if (vendor === 'none') return 'ASR/TTS 加速需要 NVIDIA CUDA；视频导出将真试编，全不可用回退 libx264';
  return '视频导出将真试编可用的硬件编码器';
}

function metaOf(info: GpuInfo | null): string {
  if (!info?.ready) return '';
  if (info.vendor !== 'nvidia') {
    if (info.vendor === 'none') return encodeNote('none');
    const parts = [
      info.name,
      info.driver_version !== '' ? `驱动 ${info.driver_version}` : '',
      encodeNote(info.vendor),
    ].filter((part) => part !== '');
    return parts.join(' · ');
  }
  const parts: string[] = [];
  if (info.name !== '') parts.push(info.name);
  if (info.driver_version !== '') parts.push(`驱动版本 ${info.driver_version}`);
  if (info.max_cuda_version !== '') parts.push(`CUDA 上限 ${info.max_cuda_version}`);
  return parts.join(' · ');
}

/** 与「本机运行条件」卡同一探测：同一屏不许对运行库在不在给出两个答案。 */
const probeRuntime = (): Promise<{ installed: boolean }> => runtimeApi.status();

export function GpuCard({
  info,
  device,
  onRefresh,
}: {
  info: GpuInfo | null;
  device: string;
  onRefresh: () => void;
}): ReactElement {
  const { status: runtime } = useEnvStatus(probeRuntime);
  const status = statusOf(info, device, runtime);
  const meta = metaOf(info);
  return (
    <div
      style={{
        padding: `${tokens.spaceMd} ${tokens.spaceLg}`,
        borderRadius: tokens.radiusCard,
        border: `1px solid ${tokens.borderSecondary}`,
        background: tokens.bgContainer,
      }}
    >
      <div style={{ ...mixins.sectionTitleRow(), marginBottom: tokens.spaceSm }}>
        <span style={{ ...mixins.sectionBar(), marginRight: tokens.spaceSm }} />
        <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>
          转写加速（GPU）
        </span>
        <Tooltip title="重新检测显卡与驱动" placement="top">
          <Button
            size="small"
            type="text"
            icon={<ReloadOutlined />}
            style={{ marginLeft: 'auto', color: tokens.textTertiary }}
            onClick={onRefresh}
          />
        </Tooltip>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
        <span style={mixins.statusDot(status.color)} />
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, fontWeight: 600, color: status.color }}>
          {status.text}
        </span>
      </div>
      {meta !== '' && <MetaLine text={meta} />}
    </div>
  );
}

/** 显卡型号 / 显存一行：徽标字阶的纯元信息。 */
function MetaLine({ text }: { text: string }): ReactElement {
  return (
    <div
      style={{
        marginTop: tokens.spaceXs,
        marginLeft: tokens.spaceLg,
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
        color: tokens.textTertiary,
      }}
    >
      {text}
    </div>
  );
}
