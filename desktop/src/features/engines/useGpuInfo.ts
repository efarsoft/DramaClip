/** GPU 探测状态（system.health.gpu_info；未就绪时短轮询补拉，就绪即停）。 */
import { useEffect, useState } from 'react';
import type { GpuInfo } from '@dramaclip/protocol';
import { systemApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';

export function useGpuInfo(): GpuInfo | null {
  const serviceState = useUiStore((state) => state.serviceState);
  const [gpu, setGpu] = useState<GpuInfo | null>(null);
  useEffect(() => {
    if (serviceState !== 'ready') return undefined;
    let alive = true;
    let timer: number | undefined;
    const load = (): void => {
      void systemApi
        .health()
        .then((health) => {
          if (!alive) return;
          const info = health.gpu_info ?? null;
          setGpu(info);
          if (info?.ready === true && timer !== undefined) {
            clearInterval(timer);
            timer = undefined;
          }
        })
        .catch(() => undefined);
    };
    load();
    timer = window.setInterval(load, 5000);
    return () => {
      alive = false;
      if (timer !== undefined) clearInterval(timer);
    };
  }, [serviceState]);
  return gpu;
}

/** 一行式 GPU 描述（引擎卡/参数区共用）。 */
export function gpuSummary(info: GpuInfo | null): string {
  if (!info?.ready) return '检测中…';
  if (info.vendor !== 'nvidia') return '未检测到 NVIDIA 显卡，转写将以 CPU 运行';
  const short = info.name.replace(/^NVIDIA\s+/i, '');
  const parts = [short !== '' ? short : 'NVIDIA'];
  if (info.driver_version !== '') parts.push(`驱动 ${info.driver_version}`);
  if (info.max_cuda_version !== '') parts.push(`CUDA 上限 ${info.max_cuda_version}`);
  return parts.join(' · ');
}
