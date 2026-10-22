/** 本地智能运行环境安装槽（E-2）：按页判缺组，一键引导（uv→venv→torch→依赖组），装完消失。 */
import type { ReactElement } from 'react';
import { DownloadOutlined } from '@ant-design/icons';
import { Button, Progress } from 'antd';
import { tokens , layout } from '../../styles/theme';
import { useLocalRuntime } from './useLocalRuntime';

export type RuntimeScope = 'tts' | 'asr';

const SCOPE_GROUP: Record<RuntimeScope, string> = { tts: 'kokoro', asr: 'funasr' };
const SCOPE_GROUP_LABEL: Record<RuntimeScope, string> = {
  tts: 'kokoro（本地配音）',
  asr: 'funasr（本地识别）',
};

export function LocalRuntimeSlot({ scope }: { scope: RuntimeScope }): ReactElement | null {
  const state = useLocalRuntime();
  if (state.installed === null) return null; // 探测中不闪槽
  const groupMissing = !state.groups[SCOPE_GROUP[scope]];
  const doubleStackMissing = !state.installed; // 组件外层已拦探测中（null），此处 false=已装
  const slotDue = scope === 'asr' ? groupMissing : doubleStackMissing || groupMissing;
  return slotDue ? <SlotView state={state} scope={scope} /> : null;
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

function SlotView({
  state,
  scope,
}: {
  state: ReturnType<typeof useLocalRuntime>;
  scope: RuntimeScope;
}): ReactElement {
  if (state.jobId === '') {
    const upgrading = state.installed === true;
    const copy = upgrading
      ? `本地智能运行环境待更新：本页依赖组 ${SCOPE_GROUP_LABEL[scope]} 待补装（约数百 MB，与已装内容共存）`
      : '本地智能运行环境未安装（本地识别 / IndexTTS / CosyVoice / Kokoro / 人声分离共用；torch 等约 2~6GB，含独立 Python，与安装包分离按需下载）';
    return (
      <div style={SLOT_BOX}>
        <span style={{ color: tokens.colorWarning }}>{copy}</span>
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
      <span style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: layout.stack.tight }}>
        <span style={{ color: tokens.textSecondary }}>{state.stage || '准备中…'}</span>
        <Progress percent={Math.round(state.progress)} size="small" showInfo={false} />
      </span>
    </div>
  );
}
