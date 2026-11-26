/**
 * CUDA 运行库的下载动作（总览页「运行环境」行内，规格 §2.3：指路不指按钮）。
 *
 * 原先这句让用户去兄弟栅格位的 GPU 卡点下载，而设备钉在 CPU 时那张卡连下载行都不渲染，
 * 指路于是指向一个不在场的按钮。装成后自己重探（不逼用户刷页面）；装不起来把原因常驻
 * 在这一行，不交给会自己消失的 toast。
 *
 * 盯的是安装作业而不是状态：原先「装着就每 2 秒重探、探到已安装才停」——装失败时状态
 * 永远到不了已安装，重探永不停，这一行也一直挂在「安装中」。现在按作业终态收尾。
 */
import { useCallback, useEffect, useState } from 'react';
import { jobsApi, runtimeApi } from '../../services/client';
import { errorText } from './errorText';

export interface CudaInstall {
  readonly installing: boolean;
  readonly problem: string;
  readonly start: () => void;
}

export function useCudaInstall(reload: () => void): CudaInstall {
  const [installing, setInstalling] = useState(false);
  const [jobId, setJobId] = useState('');
  const [problem, setProblem] = useState('');

  useEffect(() => {
    if (jobId === '') return undefined;
    // 先查一次再按间隔轮询：作业若瞬间收尾，不必干等一轮间隔
    const poll = (): void => {
      jobsApi
        .get(jobId)
        .then(({ job }) => {
          if (job.status === 'completed') {
            setJobId('');
            setInstalling(false);
            reload();
          } else if (job.status === 'failed' || job.status === 'cancelled') {
            setJobId('');
            setInstalling(false);
            setProblem(
              job.status === 'cancelled'
                ? 'CUDA 运行库安装已取消'
                : `CUDA 运行库下载失败：${job.error ?? '服务端未给出原因'}`,
            );
          }
        })
        .catch(() => undefined);
    };
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      clearInterval(timer);
    };
  }, [jobId, reload]);

  const start = useCallback((): void => {
    setProblem('');
    setInstalling(true);
    void runtimeApi
      .install()
      .then(({ job_id }) => {
        setJobId(job_id);
      })
      .catch((error: unknown) => {
        setInstalling(false);
        setProblem(`CUDA 运行库下载失败：${errorText(error, '服务端未给出原因')}`);
      });
  }, []); // 不读 reload：起作业只认作业号，重探由作业收尾那一支做

  return { installing, problem, start };
}
