/** 成品库数据加载与页面级动作（独立成文件：页面组件保持函数行数纪律）。 */
import { useCallback, useEffect, useState } from 'react';
import { App as AntdApp } from 'antd';
import type { WorkItem } from '@dramaclip/protocol';
import { exportApi, listWorks, projectApi, revealInFolder } from '../../services/client';
import { useJobsStore } from '../../stores/jobs';
import { useUiStore } from '../../stores/ui';
import type { WorksFilterKey } from './worksView';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export interface WorksLoad {
  works: WorkItem[] | null;
  error: string;
  covers: Map<string, string>;
  load: () => Promise<void>;
}

/** 列表 + 各剧封面：失败如实记账（意见01「取不到 ≠ 一直在取」），旧数据不丢。 */
export function useWorksLoad(filter: WorksFilterKey): WorksLoad {
  const serviceState = useUiStore((state) => state.serviceState);
  const [works, setWorks] = useState<WorkItem[] | null>(null);
  const [error, setError] = useState('');
  const [covers, setCovers] = useState<Map<string, string>>(new Map());
  const load = useCallback(async () => {
    try {
      const [items, projects] = await Promise.all([
        listWorks(60, filter === 'all' ? undefined : filter),
        projectApi.list().catch(() => []),
      ]);
      setWorks(items);
      setCovers(new Map(projects.map((p) => [p.id, p.cover_path ?? ''])));
      setError('');
    } catch (error_: unknown) {
      setError(errorMessage(error_));
    }
  }, [filter]);
  // 服务就绪前 RPC 会失败；ready 后（重）加载。筛选切换由 load 身份变化自动触发。
  useEffect(() => {
    if (serviceState !== 'ready') return;
    void load();
  }, [load, serviceState]);
  return { works, error, covers, load };
}

/** 页面级动作：补测自检（排入即开抽屉，队列为空如实说）与打开文件夹（失败原文上屏）。 */
export function useWorksPageActions(): {
  onSelfcheck: () => void;
  onFolder: (work: WorkItem) => void;
} {
  const { message } = AntdApp.useApp();
  const setDrawerOpen = useJobsStore((state) => state.setDrawerOpen);
  const onSelfcheck = useCallback((): void => {
    void exportApi
      .selfcheck()
      .then((result) => {
        if (result.queued === 0) {
          message.info('没有待补测的成片');
          return;
        }
        setDrawerOpen(true);
        message.success(`已排入自检补测：${String(result.queued)} 条`);
      })
      .catch((error_: unknown) => {
        message.error(errorMessage(error_));
      });
  }, [message, setDrawerOpen]);
  const onFolder = useCallback(
    (work: WorkItem): void => {
      void revealInFolder(work.output_path)
        .then((result) => {
          if (!result.ok) message.error(result.reason ?? '打开文件夹失败');
        })
        .catch((error_: unknown) => {
          message.error(errorMessage(error_));
        });
    },
    [message],
  );
  return { onSelfcheck, onFolder };
}
