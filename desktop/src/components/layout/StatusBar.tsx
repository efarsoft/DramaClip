/** 底部状态栏：服务状态 / 内置依赖 / 应用版本。 */
import { useEffect, useState } from 'react';
import { appVersion } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';

const STATE_META: Record<string, { label: string; color: string }> = {
  starting: { label: '启动中', color: tokens.colorWarning },
  ready: { label: '运行中', color: tokens.colorSuccess },
  restarting: { label: '重启中', color: tokens.colorWarning },
  unavailable: { label: '不可用', color: tokens.colorError },
};

export function StatusBar(): React.ReactElement {
  const serviceState = useUiStore((state) => state.serviceState);
  const [version, setVersion] = useState('');
  useEffect(() => {
    void appVersion().then(setVersion);
  }, []);
  const meta = STATE_META[serviceState] ?? { label: serviceState, color: tokens.textTertiary };
  return (
    <div
      style={{
        height: 26,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '0 14px',
        background: tokens.bgSidebar,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        fontSize: 11,
        color: tokens.textTertiary,
      }}
    >
      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 3,
            background: meta.color,
            boxShadow: `0 0 6px ${meta.color}`,
          }}
        />
        Python 服务 · {meta.label}
      </span>
      <span>FFmpeg · 内置</span>
      <span style={{ marginLeft: 'auto' }}>
        DramaClip {version === '' ? '' : `v${version}`}
      </span>
    </div>
  );
}
