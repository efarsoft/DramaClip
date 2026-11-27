/** 任务喂数：全局唯一轮询点，快照写 stores/jobs；顺带挂载任务抽屉。
 *  页面隐藏（最小化/切走）时 tick 直接空转不发包，回前台 visibilitychange 立即补一发——
 *  看不见的页面不该持续打扰服务；完成通知等回前台一并到，不丢账。 */
import { useEffect, type ReactElement } from 'react';
import { jobsApi } from '../../services/client';
import { useJobsStore } from '../../stores/jobs';
import { useUiStore } from '../../stores/ui';
import { JobDrawer } from './JobDrawer';
import { ExportToast } from './ExportToast';

/** 抽屉开着看进度走 2s；关着只养状态栏角标，10s 足够（卷三意见 09：事件驱动是 backlog）。 */
const OPEN_INTERVAL_MS = 2_000;
const CLOSED_INTERVAL_MS = 10_000;
/** 服务端对 limit 的上限就是 200；超出部分抽屉里如实写「仅显示最近 200 条」。 */
const LIST_LIMIT = 200;

export function JobsFeed(): ReactElement {
  const serviceState = useUiStore((state) => state.serviceState);
  const drawerOpen = useJobsStore((state) => state.drawerOpen);
  const fast = useJobsStore((state) => state.fast);

  useEffect(() => {
    if (serviceState !== 'ready') return;
    let stopped = false;
    const tick = (): void => {
      if (document.hidden) return;
      jobsApi
        .list(LIST_LIMIT)
        .then((result) => {
          if (!stopped) useJobsStore.getState().setSnapshot(result.jobs, result.server_time_ms);
        })
        .catch((error: unknown) => {
          if (stopped) return;
          const reason = error instanceof Error && error.message !== '' ? error.message : String(error);
          useJobsStore.getState().setUnavailable(reason);
        });
    };
    tick();
    const timer = setInterval(tick, drawerOpen || fast > 0 ? OPEN_INTERVAL_MS : CLOSED_INTERVAL_MS);
    const onVisibility = (): void => {
      if (!document.hidden) tick();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stopped = true;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [serviceState, drawerOpen, fast]);

  return (
    <>
      <JobDrawer />
      <ExportToast />
    </>
  );
}
