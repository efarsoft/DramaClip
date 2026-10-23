/** 本地智能运行环境安装槽（E-2）：按页判缺组，一键引导（uv→venv→torch→依赖组），装完消失。 */
import type { ReactElement } from 'react';
import { DownloadOutlined } from '@ant-design/icons';
import { Button, Progress } from 'antd';
import { tokens, layout } from '../../styles/theme';
import { useLocalRuntime } from './useLocalRuntime';

export type RuntimeScope = 'tts' | 'asr';

const SCOPE_GROUP: Record<RuntimeScope, string> = { tts: 'kokoro', asr: 'funasr' };
const SCOPE_GROUP_LABEL: Record<RuntimeScope, string> = {
  tts: 'kokoro（本地配音）',
  asr: 'funasr（本地识别）',
};

export function LocalRuntimeSlot({ scope }: { scope: RuntimeScope }): ReactElement | null {
  const state = useLocalRuntime();
  if (state.installed === null) {
    // 探测中不闪槽；探测取不到必须闪一槽「未知」——把它当探测中吞掉，
    // 用户看到的是「什么都没装过」，而真相是「这一屏答不上来」（规格 H3 §3.2.1）。
    return state.probeProblem === '' ? null : <UnknownView state={state} />;
  }
  const groupMissing = !state.groups[SCOPE_GROUP[scope]];
  const doubleStackMissing = !state.installed; // 组件外层已拦探测中（null），此处 false=已装
  const slotDue = scope === 'asr' ? groupMissing : doubleStackMissing || groupMissing;
  return slotDue ? <SlotView state={state} scope={scope} /> : null;
}

/** 探测失败的槽位：只说「状态未知 + 原话 + 重探」，绝不写「未安装」、绝不挂安装按钮。 */
function UnknownView({ state }: { state: ReturnType<typeof useLocalRuntime> }): ReactElement {
  return (
    <div style={SLOT_BOX}>
      <span style={{ color: tokens.colorWarning }}>
        {`本地智能运行环境状态未知：探测失败（${state.probeProblem}）`}
      </span>
      <Button size="small" style={{ marginLeft: 'auto' }} onClick={state.retryProbe}>
        重试探测
      </Button>
    </div>
  );
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
        <span style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: layout.stack.tight }}>
          <span style={{ color: tokens.colorWarning }}>{copy}</span>
          {state.installProblem !== '' && (
            <span style={{ color: tokens.errorText }}>{state.installProblem}</span>
          )}
        </span>
        <Button
          size="small"
          type="primary"
          icon={<DownloadOutlined />}
          loading={state.busy}
          style={{ marginLeft: 'auto' }}
          onClick={state.install}
        >
          {state.installProblem === '' ? '安装运行环境' : '重试安装'}
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
