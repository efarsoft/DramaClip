/** 导出完成/失败 toast（🟡批③）：出片好了不用自己翻成品页。
 *
 * 挂在 JobsFeed 内（全局唯一轮询点），对 jobs 快照做 diff——
 * 上一轮 running/pending → 本轮 completed/failed = 终态迁移，触发 toast。
 * Antd App.useApp().notification 保证样式与全局主题一致。
 */
import { App as AntdApp } from 'antd';
import { useEffect, useRef, type ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import { useJobsStore } from '../../stores/jobs';
import type { JobInfo } from '@dramaclip/protocol';

export function ExportToast(): ReactElement {
  const { notification } = AntdApp.useApp();
  const navigate = useNavigate();
  const jobs = useJobsStore((state) => state.jobs);
  const prevRef = useRef<readonly JobInfo[]>([]);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = jobs;
    if (prev.length === 0) return; // 首帧（或重连）不判迁移——全是「新出现的」

    const prevById = new Map(prev.map((job) => [job.id, job]));
    for (const job of jobs) {
      const before = prevById.get(job.id);
      if (before === undefined) continue; // 本轮新出现的任务
      if (before.status === 'running' || before.status === 'pending') {
        if (job.status === 'completed' && job.type.includes('export')) {
          notification.success({
            message: '导出完成',
            description: job.label ?? '成片已就绪',
            placement: 'bottomRight',
            duration: 6,
            onClick: () => {
              void navigate('/works');
            },
          });
        } else if (job.status === 'failed' && job.type.includes('export')) {
          notification.error({
            message: '导出失败',
            description: job.error ?? '未知原因',
            placement: 'bottomRight',
            duration: 8,
          });
        }
      }
    }
  }, [jobs, notification, navigate]);

  return <></>;
}
