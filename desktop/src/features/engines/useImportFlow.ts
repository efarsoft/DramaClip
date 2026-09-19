/**
 * 导入向导的流水账：选目录 → 只读体检 → 提交落位作业 → 收尾。
 *
 * 这里只记「走到哪一步、还差什么选择」，一条判据都不实现：闸门读 gateBlock，
 * 体检结果出自 models.import_inspect，落位收尾出自 useImportLanding（作业 + 登记本）。
 * 弹窗一关即卸载，下次打开自然是第 ① 步的干净局面。
 */
import { useCallback, useState } from 'react';
import type { ImportInspection } from '@dramaclip/protocol';
import { modelsApi, pickFolder } from '../../services/client';
import { type ImportDraft, commitPayload, emptyDraft, gateBlock } from './importWizard';
import { type ImportLanding, errorText, useImportLanding } from './useImportLanding';

export interface ImportFlow extends ImportLanding {
  step: number;
  report: ImportInspection | null;
  draft: ImportDraft;
  scanning: boolean;
  /** 提交这一口气：按钮靠它挡住连点，作业开始跑之后就不算「提交中」了。 */
  submitting: boolean;
  /** 拦住第 ③ 步的理由；undefined = 放行。第 ②③ 步的按钮与说明共用它。 */
  block: string | undefined;
  setDraft: (draft: ImportDraft) => void;
  goTo: (step: number) => void;
  choose: () => void;
  land: () => void;
}

export function useImportFlow(onChanged: () => void): ImportFlow {
  const [step, setStep] = useState(0);
  const [report, setReport] = useState<ImportInspection | null>(null);
  const [draft, setDraft] = useState<ImportDraft>(emptyDraft);
  const [scanning, setScanning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const landing = useImportLanding(jobId, report, onChanged);

  const choose = useCallback(async (): Promise<void> => {
    const picked = await pickFolder();
    if (picked === null) return;
    setError('');
    setScanning(true);
    try {
      setReport(await modelsApi.inspectImport(picked));
      setDraft(emptyDraft());
      setStep(1);
    } catch (reason) {
      setError(errorText(reason, '读取失败'));
    } finally {
      setScanning(false);
    }
  }, []);

  const land = useCallback(async (): Promise<void> => {
    if (report === null) return;
    setError('');
    setSubmitting(true);
    try {
      const job = await modelsApi.commitImport(commitPayload(draft, report));
      setJobId(job.job_id);
      setStep(3);
    } catch (reason) {
      setError(errorText(reason, '导入没开始'));
    } finally {
      setSubmitting(false);
    }
  }, [draft, report]);

  return {
    ...landing,
    step,
    report,
    draft,
    scanning,
    submitting,
    // 提交前的失败说提交，作业里的失败由 landing 说；同一时刻只有一处在卡壳。
    error: error === '' ? landing.error : error,
    block: report === null ? undefined : gateBlock(draft, report),
    setDraft,
    goTo: (next: number) => {
      setError('');
      setStep(next);
    },
    choose: () => {
      void choose();
    },
    land: () => {
      void land();
    },
  };
}
