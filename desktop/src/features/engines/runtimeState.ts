/** 运行环境探测的共用口径：`GpuCard`（转写加速）与 `MachinePanel`（本机运行条件）在同一屏
 *  的兄弟栅格位，两张卡对「CUDA 运行库在不在」必须出同一个词——判据分两处就会长成两个
 *  相反结论（2026-10-22 规格 §2.2 实测：一边写「将自动启用 GPU 加速」，一边写「转写走 CPU」）。
 */
import { useCallback, useEffect, useState } from 'react';

/** 装好 / 没装 / 还在探 / 取不到：「取不到」既不许说成「已就绪」，也不许说成「未安装」。 */
export type EnvStatus = 'loading' | 'installed' | 'missing' | 'unknown';

/** 一次 `installed` 探测的四态包装；`reload` 给安装动作完成后自己重探用，不逼用户刷页面。 */
export function useEnvStatus(probe: () => Promise<{ installed: boolean }>): {
  status: EnvStatus;
  reload: () => void;
} {
  const [status, setStatus] = useState<EnvStatus>('loading');
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let stopped = false;
    probe()
      .then((result) => {
        if (!stopped) setStatus(result.installed ? 'installed' : 'missing');
      })
      .catch(() => {
        if (!stopped) setStatus('unknown');
      });
    return () => {
      stopped = true;
    };
  }, [probe, tick]);
  const reload = useCallback(() => {
    setTick((prev) => prev + 1);
  }, []);
  return { status, reload };
}
