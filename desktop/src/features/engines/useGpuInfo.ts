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
    const load = (): void => {
      void systemApi
        .health()
        .then((health) => {
          if (alive) setInfo(health.gpu_info ?? null);
        })
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 5000);
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
