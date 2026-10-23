/** GPU 卡文案按宿主厂商分支：AMD/Intel 主机不该再被告知「未检测到 NVIDIA 显卡」。
 *
 * 「未检测到独立显卡」与「有卡但不支持 CUDA」是两件事，压成一句话会让用户
 * 以为自己的卡不存在（真机口径：RX 5500 XT 主机上看到过这句）。
 *
 * 另钉 H2 §2.2：这张卡与兄弟栅格的「本机运行条件」卡同屏，两张卡说同一件事不能相反。
 * 原先 GPU 卡只读 `gpu_info`（卡型可得性）就写「首次转写时将自动启用 GPU 加速」，而运行
 * 库探测（`models.runtime_status`）未装时兄弟卡写「转写走 CPU」——同一屏两个结论。
 * 现在 GPU 卡的出词读同一个运行库探测：装了什么才敢说什么。
 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GpuInfo } from '@dramaclip/protocol';
import { runtimeApi } from '../../../services/client';
import { GpuCard } from '../GpuCard';

vi.mock('../../../services/client', () => ({
  runtimeApi: {
    status: vi.fn(() => Promise.resolve({ cublas: true, cudnn: true, installed: true })),
    install: vi.fn(() => Promise.resolve({})),
  },
}));

function card(vendor: GpuInfo['vendor'], name: string, device = 'auto'): void {
  render(
    <GpuCard
      info={{
        ready: true, vendor, name, driver_version: '31.0.1',
        max_cuda_version: '', memory_total_mb: 8192, compute_cap: '',
      }}
      device={device}
      onRefresh={() => undefined}
    />,
  );
}

describe('GpuCard 厂商分支', () => {
  afterEach(cleanup);

  it('amd → 说清转写走 CPU，但 AMF 硬件编码可用', async () => {
    card('amd', 'Radeon RX 6600');
    expect(await screen.findByText(/未检测到 NVIDIA 显卡 · 转写将以 CPU 运行/)).toBeTruthy();
    expect(
      screen.getByText(/Radeon RX 6600 · 驱动 31.0.1 · 视频导出可用 AMD 硬件编码（AMF，导出时真试编）/),
    ).toBeTruthy();
  });

  it('intel → 文案给 QSV', async () => {
    card('intel', 'UHD Graphics 630');
    expect(await screen.findByText(/视频导出可用 Intel 硬件编码（QSV，导出时真试编）/)).toBeTruthy();
  });

  it('other → 不点名厂商，只说真试编', async () => {
    card('other', 'Microsoft Basic Display Adapter');
    expect(await screen.findByText(/视频导出将真试编可用的硬件编码器/)).toBeTruthy();
  });

  it('none → 没有卡：型号行不编造名字', async () => {
    card('none', '');
    expect(await screen.findByText(/未检测到独立显卡 · 转写将以 CPU 运行/)).toBeTruthy();
    expect(
      screen.getByText(/ASR\/TTS 加速需要 NVIDIA CUDA；视频导出将真试编，全不可用回退 libx264/),
    ).toBeTruthy();
  });
});

describe('GpuCard 按运行库实际状态出词', () => {
  afterEach(cleanup);

  // 模块 mock 的实现是跨用例残留的：本组每条用例从「已装」起步，只改自己关心的那一态
  beforeEach(() => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: true, cudnn: true, installed: true });
  });

  it('运行库已装 + 设备自动：说 GPU 加速可用，不再承诺「首次转写时自动启用」', async () => {
    card('nvidia', 'RTX 4060');
    expect(await screen.findByText(/CUDA 运行库已装 · 转写可用 GPU 加速/)).toBeTruthy();
    expect(screen.queryByText(/自动启用 GPU 加速/)).toBeNull();
  });

  it('运行库未装：不得出「已就绪/将自动启用」——与本机运行条件卡同一个口径', async () => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
    card('nvidia', 'RTX 4060');
    expect(await screen.findByText(/CUDA 运行库未安装 · 转写当前走 CPU/)).toBeTruthy();
    expect(screen.queryByText(/已就绪/)).toBeNull();
    expect(screen.queryByText(/自动启用 GPU 加速/)).toBeNull();
  });

  it('运行库探测失败：如实说未知，不把「取不到」说成「已就绪」', async () => {
    vi.mocked(runtimeApi.status).mockRejectedValue(new Error('管道断了'));
    card('nvidia', 'RTX 4060');
    expect(await screen.findByText(/CUDA 运行库状态未知 · 暂按 CPU 运行/)).toBeTruthy();
    expect(screen.queryByText(/已就绪/)).toBeNull();
  });

  it('设备钉在 CPU：说的是切换设备这一条真话，不吹加速', async () => {
    card('nvidia', 'RTX 4060', 'cpu');
    expect(await screen.findByText(/当前运行设备为 CPU，将运行设备切换为「自动」即可启用 GPU 加速/)).toBeTruthy();
  });
});

