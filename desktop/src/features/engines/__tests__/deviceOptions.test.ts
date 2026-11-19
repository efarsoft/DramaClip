/** 设备选项：GPU 是承诺，界面只给会被后端 resolve 接受的值（词汇 auto/gpu/cpu）。 */
import { describe, expect, it } from 'vitest';
import type { DeviceCaps, GpuInfo } from '@dramaclip/protocol';
import { deviceOptions, visualCapKey } from '../deviceOptions';

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
  it('cap ready → 给可用的 GPU', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'auto', gpu: NVIDIA_READY,
      caps: capsOf({ ready: true }),
    });
    expect(options.map((o) => o.value)).toEqual(['auto', 'cpu', 'gpu']);
    expect(options.find((o) => o.value === 'gpu')?.disabled).toBeFalsy();
  });

  it('cap 不 ready → 不给 GPU（读 cap 不读厂商：AMD 与老 N 卡同走这支）', () => {
    for (const gpu of [AMD_READY, NVIDIA_READY]) {
      const options = deviceOptions({
        engine: 'indextts2', saved: 'auto', gpu, caps: capsOf({ ready: false, ok: false }),
      });
      expect(options.map((o) => o.value)).toEqual(['auto', 'cpu']);
    }
  });

  it('已保存 gpu 但本机不 ready → 该项仍在，disabled 且带原因', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'gpu', gpu: AMD_READY,
      caps: capsOf({ ready: false, ok: false, reason: '转写加速仅支持 NVIDIA CUDA' }),
    });
    const gpu = options.find((o) => o.value === 'gpu');
    expect(gpu?.disabled).toBe(true);
    expect(gpu?.label).toBe('GPU（转写加速仅支持 NVIDIA CUDA）');
  });

  it('存量设置值 cuda 视同 gpu：陈旧提示同样可见', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'cuda', gpu: AMD_READY,
      caps: capsOf({ ready: false, ok: false, reason: '原因 X' }),
    });
    const gpu = options.find((o) => o.value === 'gpu');
    expect(gpu?.disabled).toBe(true);
    expect(gpu?.label).toBe('GPU（原因 X）');
  });

  it('原因缺失时不渲染空括号', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'gpu', gpu: AMD_READY, caps: capsOf({ ready: false }),
    });
    expect(options.find((o) => o.value === 'gpu')?.label).toBe('GPU（本机不可用）');
  });

  it('显卡待探测 → 保留 GPU：探测中不等于不可用', () => {
    const options = deviceOptions({
      engine: 'indextts2', saved: 'auto', gpu: { ...NVIDIA_READY, ready: false },
      caps: capsOf({ ready: false }),
    });
    expect(options.some((o) => o.value === 'gpu')).toBe(true);
  });

  it('caps 缺失（旧服务）→ 保留 GPU，不做假阴性', () => {
    const options = deviceOptions({ engine: 'indextts2', saved: 'auto', gpu: NVIDIA_READY });
    expect(options.some((o) => o.value === 'gpu')).toBe(true);
  });

  it('引擎没有 cap（kokoro / edge）→ 不替它宣布可用性，原样给三档', () => {
    const options = deviceOptions({
      engine: 'kokoro', saved: 'auto', gpu: AMD_READY, caps: capsOf({ ready: false }),
    });
    expect(options.map((o) => o.value)).toEqual(['auto', 'cpu', 'gpu']);
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
        .some((o) => o.value === 'gpu'),
    ).toBe(true);
  });

  it('视觉轨按模型档位点名 cap：哪档 ready 哪档给 GPU', () => {
    const caps: DeviceCaps = {
      local_visual_2b: { ok: true, ready: true, hint: '', reason: '' },
      local_visual_4b: { ok: true, ready: false, hint: '', reason: '视觉模型 CUDA 构建资产未入库' },
    };
    expect(
      deviceOptions({
        engine: 'qwen3_vl', capKey: visualCapKey('qwen3-vl-2b'), saved: 'auto',
        gpu: NVIDIA_READY, caps,
      }).map((o) => o.value),
    ).toEqual(['auto', 'cpu', 'gpu']);
    expect(
      deviceOptions({
        engine: 'qwen3_vl', capKey: visualCapKey('qwen3-vl-4b'), saved: 'auto',
        gpu: NVIDIA_READY, caps,
      }).map((o) => o.value),
    ).toEqual(['auto', 'cpu']);
  });
});
