/** 视觉推理运行时安装槽（0.2.5 主题一 1.1）：llama.cpp 未装时在视觉页给一键下载，装完消失。 */
import type { ReactElement } from 'react';
import { DownloadOutlined } from '@ant-design/icons';
import { Button, Progress } from 'antd';
import { tokens, layout } from '../../styles/theme';
import { useLlamaRuntime } from './useLlamaRuntime';

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

export function LlamaRuntimeSlot(): ReactElement | null {
  const state = useLlamaRuntime();
  if (state.installed === true) return null;
  if (state.installed === null) {
    // 探测中不闪槽；探测失败必须如实说「状态未知」，不冒充「未安装」催用户重下。
    if (state.problem === '') return null;
    return (
      <div style={SLOT_BOX}>
        <span style={{ color: tokens.colorWarning }}>
          {`视觉推理运行时状态未知：探测失败（${state.problem}）`}
        </span>
        <Button size="small" style={{ marginLeft: 'auto' }} onClick={state.retryProbe}>
          重试探测
        </Button>
      </div>
    );
  }
  if (state.jobId !== '') {
    return (
      <div style={SLOT_BOX}>
        <span style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: layout.stack.tight }}>
          <span style={{ color: tokens.textSecondary }}>{state.stage || '准备中…'}</span>
          <Progress percent={Math.round(state.progress)} size="small" showInfo={false} />
        </span>
      </div>
    );
  }
  return (
    <div style={SLOT_BOX}>
      <span style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: layout.stack.tight }}>
        <span style={{ color: tokens.colorWarning }}>
          视觉推理运行时未安装（llama.cpp，画面理解本地档依赖；变体按显卡自动选——
          N 卡含 CUDA 运行库约 694MB，其余机型 CPU 构建约 24MB）
        </span>
        {state.problem !== '' && <span style={{ color: tokens.errorText }}>{state.problem}</span>}
      </span>
      <Button
        size="small"
        type="primary"
        icon={<DownloadOutlined />}
        loading={state.busy}
        style={{ marginLeft: 'auto' }}
        onClick={state.install}
      >
        {state.problem === '' ? '下载运行时' : '重试下载'}
      </Button>
    </div>
  );
}
