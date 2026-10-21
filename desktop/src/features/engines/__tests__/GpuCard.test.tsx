/** GPU 卡文案按宿主厂商分支：AMD/Intel 主机不该再被告知「未检测到 NVIDIA 显卡」。
 *
 * 「未检测到独立显卡」与「有卡但不支持 CUDA」是两件事，压成一句话会让用户
 * 以为自己的卡不存在（真机口径：RX 5500 XT 主机上看到过这句）。
 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GpuInfo } from '@dramaclip/protocol';
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
