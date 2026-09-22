/** IndexTTS 运行环境安装槽：未装时一键引导（uv→venv→torch→源码），装完消失。 */
import type { ReactElement } from 'react';
import { DownloadOutlined } from '@ant-design/icons';
import { Button, Progress } from 'antd';
import { tokens } from '../../styles/theme';
import type { RuntimeState } from './runtimeState';
import { useIndexttsRuntime } from './useIndexttsRuntime';

export function IndexttsRuntimeSlot(): ReactElement | null {
  const state = useIndexttsRuntime();
  return state.installed === false ? <RuntimeSlotView {...state} /> : null;
}

const SLOT_BOX = {
  display: 'flex',
  alignItems: 'center',
  gap: tokens.spaceMd,
  padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
  borderRadius: tokens.radiusControl,
  border: `1px solid ${tokens.border}`,
  background: tokens.warningSoft,
  fontSize: tokens.text.meta.size,
  lineHeight: tokens.text.meta.leading,
} as const;

function RuntimeSlotView(state: RuntimeState): ReactElement {
  if (state.jobId === '') {
    return (
      <div style={SLOT_BOX}>
        <span style={{ color: tokens.colorWarning }}>
          IndexTTS 运行环境未安装（torch 等约 2~6GB，含独立 Python，与安装包分离按需下载）
        </span>
        <Button
          size="small"
          type="primary"
          icon={<DownloadOutlined />}
          loading={state.busy}
          style={{ marginLeft: 'auto' }}
          onClick={state.install}
        >
          安装运行环境
        </Button>
      </div>
    );
  }
  return (
    <div style={SLOT_BOX}>
      <span style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ color: tokens.textSecondary }}>{state.stage || '准备中…'}</span>
        <Progress percent={Math.round(state.progress)} size="small" showInfo={false} />
      </span>
    </div>
  );
}
