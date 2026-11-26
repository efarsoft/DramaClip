/** GPU 探测状态（system.health.gpu_info；5s 轮询，就绪即停；支持强制重测）。 */
import { useCallback, useEffect, useState } from 'react';
import type { GpuInfo } from '@dramaclip/protocol';
import { systemApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';

export interface GpuView {
  readonly info: GpuInfo | null;
  readonly refresh: () => void;
}

export function useGpuInfo(): GpuView {
  const serviceState = useUiStore((state) => state.serviceState);
  const [info, setInfo] = useState<GpuInfo | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (serviceState !== 'ready') return undefined;
    let alive = true;
    // 「就绪即停」此前只写在文件头：探到了也照旧每 5 秒问一次 system.health
    // （这条在慢的时候要七八秒），引擎页开着就一直在问。探到结果即停，重测走 refresh。
    let timer = 0;
    const load = (): void => {
      void systemApi
        .health()
        .then((health) => {
          if (!alive) return;
          const next = health.gpu_info ?? null;
          setInfo(next);
          if (next?.ready) window.clearInterval(timer);
        })
        .catch(() => undefined);
    };
    load();
    timer = window.setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [serviceState, tick]);

  const refresh = useCallback((): void => {
    setInfo((prev) => (prev === null ? prev : { ...prev, ready: false }));
    void systemApi
      .health(true)
      .then((health) => {
        setInfo(health.gpu_info ?? null);
        setTick((t) => t + 1);
      })
      .catch(() => undefined);
  }, []);

  return { info, refresh };
}
