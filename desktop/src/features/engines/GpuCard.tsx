/** GPU 加速状态卡：显卡 / 驱动 / CUDA 上限 + 加速方式说明（ASR 转写用）。 */
import type { ReactElement } from 'react';
import { Button, Tooltip } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { GpuInfo } from '@dramaclip/protocol';
import { useEffect, useState } from 'react';
import { runtimeApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

function statusOf(info: GpuInfo | null, device: string): { text: string; color: string } {
  if (!info?.ready) {
    return { text: '检测中…', color: tokens.textTertiary };
  }
  if (info.vendor !== 'nvidia') {
    return { text: '未检测到 NVIDIA 显卡 · 转写将以 CPU 运行', color: tokens.textSecondary };
  }
  if (device === 'cpu') {
    return {
      text: '已就绪 · 当前运行设备为 CPU，将运行设备切换为「自动」即可启用 GPU 加速',
      color: tokens.colorWarning,
    };
  }
  return {
    text: '已就绪 · 首次转写时将自动启用 GPU 加速（CUDA 运行库缺失时自动回退 CPU）',
    color: tokens.colorSuccess,
  };
}

function metaOf(info: GpuInfo | null): string {
  if (!info?.ready) return '';
  if (info.vendor !== 'nvidia') return 'GPU 加速当前仅支持 NVIDIA（CUDA）';
  const parts: string[] = [];
  if (info.name !== '') parts.push(info.name);
  if (info.driver_version !== '') parts.push(`驱动版本 ${info.driver_version}`);
  if (info.max_cuda_version !== '') parts.push(`CUDA 上限 ${info.max_cuda_version}`);
  return parts.join(' · ');
}

/** CUDA 运行库安装状态探测：未装标记 + 安装中 2s 轮询直到装好。 */
function useRuntimeProbe(): { runtimeMissing: boolean; installing: boolean; onInstall: () => void } {
  const [runtimeMissing, setRuntimeMissing] = useState(false);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    let stopped = false;
    const probe = (): void => {
      void runtimeApi
        .status()
        .then((s) => {
          if (!stopped) setRuntimeMissing(!s.installed);
          if (s.installed && installing) setInstalling(false);
        })
        .catch(() => undefined);
    };
    probe();
    if (!installing) return () => {
      stopped = true;
    };
    const timer = setInterval(probe, 2000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [installing]);

  const onInstall = (): void => {
    void runtimeApi.install().then(() => { setInstalling(true); }).catch(() => undefined);
  };
  return { runtimeMissing, installing, onInstall };
}

export function GpuCard({
  info,
  device,
  onRefresh,
}: {
  info: GpuInfo | null;
  device: string;
  onRefresh: () => void;
}): ReactElement {
  const status = statusOf(info, device);
  const meta = metaOf(info);
  const { runtimeMissing, installing, onInstall } = useRuntimeProbe();

  const showRuntime =
    info?.ready === true && info.vendor === 'nvidia' && device !== 'cpu' && runtimeMissing;
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
      {showRuntime && <RuntimeRow installing={installing} onInstall={onInstall} />}
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

function RuntimeRow({ installing, onInstall }: { installing: boolean; onInstall: () => void }): ReactElement {
  return (
    <div
      style={{
        marginTop: tokens.spaceSm,
        marginLeft: tokens.spaceLg,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
      }}
    >
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.colorWarning }}>
        {installing ? 'CUDA 运行库下载中…（约 600MB，完成后重启服务生效）' : 'CUDA 运行库未安装 · 转写将以 CPU 运行'}
      </span>
      {!installing && (
        <Button size="small" type="primary" onClick={onInstall}>
          下载运行库
        </Button>
      )}
    </div>
  );
}
