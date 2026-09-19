/**
 * 第 ④ 步的实测来源：轮询落位作业自己的状态，收尾后再读一次登记本。
 *
 * 完成页要说的路径不是这里猜出来的：作业说完成，就重读 models.import_records，拿本次来源
 * 路径对应的那一条登记；没有它就明说没有，不拿第 ② 步的体检结果顶包。
 * 作业跑在后台，关掉弹窗它照旧跑完——GB 级复制中途停不下来，所以提交时压根没给取消入口。
 */
import { useEffect, useState } from 'react';
import type { ImportInspection, ImportRecord } from '@dramaclip/protocol';
import { jobsApi, modelsApi } from '../../services/client';
import { landedRecord } from './importWizard';

const POLL_MS = 800;

/** idle = 还没提交；running = 作业在跑；done / failed 都算「作业自己说过的话」。 */
export type LandingState = 'idle' | 'running' | 'done' | 'failed';

export interface ImportLanding {
  state: LandingState;
  percent: number;
  placed: ImportRecord | null;
  error: string;
}

/** 作业的结论：一旦落下，placed / error 就是它说过的话。没结论时两者都不该存在。 */
interface Settlement {
  outcome: 'done' | 'failed';
  placed: ImportRecord | null;
  error: string;
}

export function useImportLanding(
  jobId: string,
  report: ImportInspection | null,
  onChanged: () => void,
): ImportLanding {
  const [settled, setSettled] = useState<Settlement | null>(null);
  const [percent, setPercent] = useState(0);

  useEffect(() => {
    if (jobId === '' || report === null) return undefined;
    let stopped = false;
    // 经函数读取：直接判断变量会让「弹窗已卸载」这条分支在类型层面变成死码。
    const stoppedNow = (): boolean => stopped;
    let timer: number | undefined;
    const check = async (): Promise<void> => {
      try {
        const { job } = await jobsApi.get(jobId);
        if (stoppedNow()) return;
        setPercent(job.progress);
        if (job.status === 'completed') {
          const stored = await modelsApi.importRecords();
          if (stoppedNow()) return;
          const placed = landedRecord(stored.records, report.source_path);
          setSettled({ outcome: 'done', placed, error: '' });
          onChanged();
          return;
        }
        if (job.status !== 'pending' && job.status !== 'running') {
          setSettled({ outcome: 'failed', placed: null, error: job.error ?? '落位作业没跑完就停了' });
          return;
        }
        timer = window.setTimeout(() => {
          void check();
        }, POLL_MS);
      } catch (reason) {
        setSettled({ outcome: 'failed', placed: null, error: errorText(reason, '读不到作业状态') });
      }
    };
    void check();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [jobId, report, onChanged]);

  return {
    state: landingState(jobId, settled),
    percent,
    placed: settled?.placed ?? null,
    error: settled?.error ?? '',
  };
}

function landingState(jobId: string, settled: Settlement | null): LandingState {
  if (jobId === '') return 'idle';
  return settled?.outcome ?? 'running';
}

/** 后端的拒绝话术原样贴出，只在它没说话时补一句兜底。 */
export function errorText(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message !== '' ? reason.message : fallback;
}
