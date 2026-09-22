/** 底部状态栏：服务状态 / GPU / 内置依赖 / 应用版本。 */
import { useEffect, useState } from 'react';
import { appVersion, systemApi } from '../../services/client';
import type { GpuInfo } from '@dramaclip/protocol';
import { useUiStore } from '../../stores/ui';
import { mixins } from '../../styles/mixins';
import { layout, tokens } from '../../styles/theme';

const STATE_META: Record<string, { label: string; color: string }> = {
  starting: { label: '启动中', color: tokens.colorWarning },
  ready: { label: '运行中', color: tokens.colorSuccess },
  restarting: { label: '重启中', color: tokens.colorWarning },
  unavailable: { label: '不可用', color: tokens.colorError },
};

function gpuLabel(info: GpuInfo | undefined): string {
  if (!info?.ready) return '待检测';
  if (info.vendor !== 'nvidia') return '无独立显卡 · CPU 模式';
  const short = info.name.replace(/^NVIDIA\s+/i, '');
  return `${short !== '' ? short : 'NVIDIA'} · 驱动 ${info.driver_version || '未知'}`;
}

export function StatusBar(): React.ReactElement {
  const serviceState = useUiStore((state) => state.serviceState);
  const [version, setVersion] = useState('');
  const [gpu, setGpu] = useState<GpuInfo | undefined>(undefined);
  useEffect(() => {
    void appVersion().then(setVersion);
  }, []);
  useEffect(() => {
    if (serviceState !== 'ready') return;
    const load = (): void => {
      void systemApi
        .health()
        .then((health) => {
          setGpu(health.gpu_info);
        })
        .catch(() => undefined);
    };
    load();
    const timer = setInterval(load, 60_000);
    return () => {
      clearInterval(timer);
    };
  }, [serviceState]);
  const meta = STATE_META[serviceState] ?? { label: serviceState, color: tokens.textTertiary };
  return (
    <div
      style={{
        height: layout.statusBar.height,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceLg,
        padding: `0 ${layout.statusBar.paddingX}`,
        background: tokens.bgSidebar,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
        color: tokens.textTertiary,
      }}
    >
      <span style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
        <span style={mixins.statusDot(meta.color)} />
        Python 服务 · {meta.label}
      </span>
      <span>FFmpeg · 内置</span>
      <span>GPU · {gpuLabel(gpu)}</span>
      <span style={{ marginLeft: 'auto' }}>
        DramaClip {version === '' ? '' : `v${version}`}
      </span>
    </div>
  );
}
