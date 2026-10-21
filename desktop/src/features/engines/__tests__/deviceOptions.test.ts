/** 设备选项：CUDA 是承诺，界面只给会被后端 resolve 接受的值。 */
import { describe, expect, it } from 'vitest';
import type { DeviceCaps, GpuInfo } from '@dramaclip/protocol';
import { deviceOptions } from '../deviceOptions';

const NVIDIA_READY: GpuInfo = {
  ready: true, vendor: 'nvidia', name: 'RTX 4060', driver_version: '572.10',
  max_cuda_version: '12.8', memory_total_mb: 8188, compute_cap: '8.9',
};
const AMD_READY: GpuInfo = {
  ready: true, vendor: 'amd', name: 'Radeon RX 6600', driver_version: '31.0.21006.1',
  max_cuda_version: '', memory_total_mb: 8192, compute_cap: '',
};

type DeviceCap_ = DeviceCaps[string];

function capsOf(entry: Partial<DeviceCap_>): DeviceCaps {
  return { indextts2_gpu: { ok: true, ready: false, hint: '', reason: '', ...entry } };
}

describe('deviceOptions', () => {
  it('cap ready → 给可用的 CUDA', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'auto', gpu: NVIDIA_READY,
      caps: capsOf({ ready: true }),
    });
    expect(options.map((o) => o.value)).toEqual(['auto', 'cpu', 'cuda']);
    expect(options.find((o) => o.value === 'cuda')?.disabled).toBeFalsy();
  });

  it('cap 不 ready → 不给 CUDA（读 cap 不读厂商：AMD 与老 N 卡同走这支）', () => {
    for (const gpu of [AMD_READY, NVIDIA_READY]) {
      const options = deviceOptions({
        engine: 'indextts2', saved: 'auto', gpu, caps: capsOf({ ready: false, ok: false }),
      });
      expect(options.map((o) => o.value)).toEqual(['auto', 'cpu']);
    }
  });

  it('已保存 cuda 但本机不 ready → 该项仍在，disabled 且带原因', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'cuda', gpu: AMD_READY,
      caps: capsOf({ ready: false, ok: false, reason: '转写加速仅支持 NVIDIA CUDA' }),
    });
    const cuda = options.find((o) => o.value === 'cuda');
    expect(cuda?.disabled).toBe(true);
    expect(cuda?.label).toBe('CUDA（转写加速仅支持 NVIDIA CUDA）');
  });

  it('原因缺失时不渲染空括号', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'cuda', gpu: AMD_READY, caps: capsOf({ ready: false }),
    });
    expect(options.find((o) => o.value === 'cuda')?.label).toBe('CUDA（本机不可用）');
  });

  it('显卡待探测 → 保留 CUDA：探测中不等于不可用', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'auto', gpu: { ...NVIDIA_READY, ready: false },
      caps: capsOf({ ready: false }),
    });
    expect(options.some((o) => o.value === 'cuda')).toBe(true);
  });

  it('caps 缺失（旧服务）→ 保留 CUDA，不做假阴性', () => {
    const options = deviceOptions({ engine: 'indextts2', saved: 'auto', gpu: NVIDIA_READY });
    expect(options.some((o) => o.value === 'cuda')).toBe(true);
  });

  it('引擎没有 cap（kokoro / edge）→ 不替它宣布可用性，原样给三档', () => {
    const options = deviceOptions({
      engine: 'kokoro', saved: 'auto', gpu: AMD_READY, caps: capsOf({ ready: false }),
    });
    expect(options.map((o) => o.value)).toEqual(['auto', 'cpu', 'cuda']);
  });

  it('ASR 两个引擎读各自的 cap：funasr 与 whisper 下限不同', () => {
    const caps: DeviceCaps = {
      faster_whisper_gpu: { ok: false, ready: false, hint: '', reason: '算力低于 ctranslate2 下限' },
      indextts2_gpu: { ok: true, ready: true, hint: '', reason: '' },
    };
    expect(
      deviceOptions({ engine: 'faster_whisper', saved: 'auto', gpu: NVIDIA_READY, caps })
        .map((o) => o.value),
    ).toEqual(['auto', 'cpu']);
    expect(
      deviceOptions({ engine: 'sensevoice', saved: 'auto', gpu: NVIDIA_READY, caps })
        .some((o) => o.value === 'cuda'),
    ).toBe(true);
  });
});
