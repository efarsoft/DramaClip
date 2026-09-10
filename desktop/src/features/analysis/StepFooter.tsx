/** 底部步骤操作栏：上一步 / 状态提示 / 下一步。 */
import { Button, Tooltip } from 'antd';
import { RightOutlined } from '@ant-design/icons';
import { tokens } from '../../styles/theme';

export function StepFooter({
  step,
  total,
  canProceed,
  proceedHint,
  nextLabel,
  onPrev,
  onNext,
}: {
  step: number;
  total: number;
  canProceed: boolean;
  proceedHint: string;
  nextLabel: string;
  onPrev: () => void;
  onNext: () => void;
}): React.ReactElement {
  return (
    <div
      style={{
        height: 46,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '0 16px',
        background: tokens.bgSidebar,
        borderTop: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <Button icon={<RightOutlined style={{ transform: 'rotate(180deg)' }} />} disabled={step <= 1} onClick={onPrev}>
        上一步
      </Button>
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
        步骤 {String(step)} / {String(total)} · {proceedHint}
      </span>
      <Tooltip title={canProceed ? '' : '完成至少一集分析后解锁'}>
        <Button
          type="primary"
          style={{ marginLeft: 'auto' }}
          disabled={!canProceed}
          onClick={onNext}
        >
          下一步：{nextLabel}
          <RightOutlined style={{ fontSize: tokens.fontMicro }} />
        </Button>
      </Tooltip>
    </div>
  );
}
