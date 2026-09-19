/**
 * 导入本地模型向导（D-P3）：① 选来源 → ② 识别与体检 → ③ 落位方式 → ④ 完成。
 *
 * 本文件只有弹窗壳与按钮：闸门判据在 importWizard.ts，流水账在 useImportFlow.ts，
 * 四步各摆什么在 ImportWizard* 两件里。第 ② 步不通过就进不了第 ③ 步——按钮禁用，
 * 理由原样贴在卡壳上，说的都是业主还没做的选择。
 */
import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';
import { Alert, Button, Modal, Steps } from 'antd';
import { tokens } from '../../styles/theme';
import { useImportFlow } from './useImportFlow';
import { IdentifyStep, SourceStep } from './ImportWizardSteps';
import { DoneStep, LandStep } from './ImportWizardLanding';

const STEPS = ['来源', '体检', '落位', '完成'];

export interface ImportModelModalProps {
  open: boolean;
  onClose: () => void;
  /** 落位一结束就刷新资产库：新行要立刻看得见，不等弹窗关掉。 */
  onChanged: () => void;
  /** 「选为生效」只交 model_id：写回哪几个设置键由资产库那行的判据说了算。 */
  onActivate: (modelId: string) => void;
}

export function ImportModelModal({
  open,
  onClose,
  onChanged,
  onActivate,
}: ImportModelModalProps): ReactElement {
  /**
   * rc-dialog 在关闭时把弹窗内容冻在原地（Panel 的 MemoChildren 只在可见时才吃新的 children），
   * 所以「关窗即清场」不能指望条件渲染，得换钥匙：一关就 +1，再打开时旧的第 ④ 步残局被卸载，
   * 从第 ① 步重挂。
   */
  const [session, setSession] = useState(0);
  useEffect(() => {
    if (!open) setSession((count) => count + 1);
  }, [open]);
  return (
    <Modal open={open} title="导入本地模型" width={720} footer={null} onCancel={onClose}>
      <WizardBody key={session} onClose={onClose} onChanged={onChanged} onActivate={onActivate} />
    </Modal>
  );
}

type BodyProps = Omit<ImportModelModalProps, 'open'>;

function WizardBody({ onClose, onChanged, onActivate }: BodyProps): ReactElement {
  const flow = useImportFlow(onChanged);
  const { step, report, draft, scanning, state, percent, placed, error, block } = flow;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <Steps size="small" current={step} items={STEPS.map((title) => ({ title }))} />
      {step === 0 && (
        <SourceStep
          scanning={scanning}
          onPick={() => {
            flow.choose();
          }}
        />
      )}
      {report !== null && step === 1 && (
        <IdentifyStep report={report} draft={draft} onChange={flow.setDraft} />
      )}
      {report !== null && step === 2 && <LandStep report={report} draft={draft} onChange={flow.setDraft} />}
      {/* 作业自己说「没跑完」时不摆完成页：第 ④ 步只说实测到的事。 */}
      {report !== null && step === 3 && state !== 'failed' && (
        <DoneStep
          report={report}
          placed={placed}
          percent={percent}
          running={state === 'running'}
          onActivate={(modelId) => {
            onActivate(modelId);
            onClose();
          }}
        />
      )}
      {error !== '' && <Alert type="error" showIcon title={error} />}
      {step === 1 && block !== undefined && <Alert type="error" showIcon title={block} />}
      <Footer flow={flow} onClose={onClose} />
    </div>
  );
}

/** 底部按钮：第 ②③ 步的「下一步 / 开始导入」共用同一条闸门与同一句理由。 */
function Footer({ flow, onClose }: { flow: ReturnType<typeof useImportFlow>; onClose: () => void }): ReactElement {
  const { step, state, submitting, block, goTo, land } = flow;
  const blocked = block !== undefined;
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: tokens.spaceSm }}>
      <Button onClick={onClose}>{step === 3 && state === 'done' ? '返回资产库' : '取消'}</Button>
      {step > 0 && step < 3 && (
        <Button
          onClick={() => {
            goTo(step - 1);
          }}
        >
          上一步
        </Button>
      )}
      {step === 1 && (
        <Button
          type="primary"
          disabled={blocked}
          title={block}
          onClick={() => {
            goTo(step + 1);
          }}
        >
          下一步
        </Button>
      )}
      {step === 2 && (
        <Button type="primary" disabled={blocked} title={block} loading={submitting} onClick={land}>
          开始导入
        </Button>
      )}
    </div>
  );
}
