/** 下载取消的共享路径：ModelDownloadPopover 与工作台一键引导（OnboardingSteps）共用。
 *
 * 作业 id 不在进度事件里（服务端不下发），刷新后 store 里也没有——
 * 所以按「进行中的 model_download 且 ref_id=本模型」现查，页面刷过之后取消照样能用。
 */
import { jobsApi } from '../../services/client';

export type CancelOutcome = { kind: 'cancelled' } | { kind: 'gone' } | { kind: 'blocked'; reason: string };

export async function requestCancel(modelId: string): Promise<CancelOutcome> {
  const { jobs } = await jobsApi.list(50, true);
  const job = jobs.find((item) => item.type === 'model_download' && item.ref_id === modelId);
  if (job === undefined) return { kind: 'gone' };
  const result = await jobsApi.cancel(job.id);
  if (!result.cancelling) return { kind: 'blocked', reason: result.reason ?? '服务端未给出原因' };
  return { kind: 'cancelled' };
}
