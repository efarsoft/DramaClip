/** 总览页·运行环境两行的接线与口径（业主需求 2026-09-24：运行环境和 CUDA 状态上总览）。
 *
 * 判据：① 装没装都常驻显示——状态是账本，不是出了事才冒出来的警报；② 缺 IndexTTS
 * 环境给「去安装」落点（跳配音 TTS 页，动作在其家，总览只给结论与落点）；③ 无
 * NVIDIA 显卡时不劝人下没用的 CUDA 运行库；④ 探测失败如实「状态未知」——取不到
 * ≠ 不存在，不冒充「未安装」。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { HealthResult } from '@dramaclip/protocol';
import { indexttsApi, runtimeApi, systemApi } from '../../../services/client';
import { MachinePanel } from '../MachinePanel';

vi.mock('../../../services/client', () => ({
  systemApi: { health: vi.fn(() => Promise.resolve({})) },
  runtimeApi: {
    status: vi.fn(() => Promise.resolve({ cublas: true, cudnn: true, installed: true })),
    install: vi.fn(() => Promise.resolve({})),
  },
  indexttsApi: {
    status: vi.fn(() => Promise.resolve({ installed: true, dir: 'C:/rt' })),
    install: vi.fn(() => Promise.resolve({ job_id: 'j' })),
  },
}));

const NVIDIA_HEALTH: HealthResult = {
  status: 'ok',
  uptime_s: 1,
  ffmpeg_version: '7.1',
  gpu_info: {
    ready: true,
    vendor: 'nvidia',
    name: 'RTX 4060',
    driver_version: '572.10',
    max_cuda_version: '12.8',
  },
  ram_total_gb: 32,
  ram_free_gb: 16,
  disk_free_gb: 200,
};

const NO_GPU_HEALTH: HealthResult = { ...NVIDIA_HEALTH, gpu_info: undefined };

function renderPanel(health: HealthResult = NVIDIA_HEALTH): void {
  vi.mocked(systemApi.health).mockResolvedValue(health);
  render(
    <MemoryRouter initialEntries={['/engines/overview']}>
      <Routes>
        <Route path="/engines/overview" element={<MachinePanel models={[]} />} />
        <Route path="/engines/tts" element={<div>TTS 页已到</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('总览页 · 运行环境状态行', () => {
  afterEach(cleanup);

  it('两个环境都装好 → 两行常驻绿账，不给多余动作', async () => {
    renderPanel();
    expect(await screen.findByText(/CUDA 运行库：已安装/)).toBeTruthy();
    expect(await screen.findByText(/IndexTTS 运行环境：已安装/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '去安装' })).toBeNull();
  });

  it('缺 IndexTTS 环境 → 如实报缺 + 「去安装」落到配音 TTS 页', async () => {
    vi.mocked(indexttsApi.status).mockResolvedValue({ installed: false, dir: '' });
    renderPanel();
    expect(await screen.findByText(/IndexTTS 运行环境：未安装/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '去安装' }));
    expect(await screen.findByText('TTS 页已到')).toBeTruthy();
  });

  it('有 N 卡但缺 CUDA 运行库 → 指向本页 GPU 卡的下载入口', async () => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
    renderPanel();
    expect(await screen.findByText(/CUDA 运行库：未安装 · 转写走 CPU，可在本页「转写加速（GPU）」卡下载/)).toBeTruthy();
  });

  it('无 N 卡 → 不劝人下没用的运行库（如实说无需安装）', async () => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
    renderPanel(NO_GPU_HEALTH);
    expect(await screen.findByText(/CUDA 运行库：未安装 · 本机无 NVIDIA 显卡，无需安装/)).toBeTruthy();
  });

  it('探测失败 → 「状态未知」，取不到 ≠ 不存在，不冒充未安装', async () => {
    vi.mocked(runtimeApi.status).mockRejectedValue(new Error('pipe broken'));
    vi.mocked(indexttsApi.status).mockRejectedValue(new Error('pipe broken'));
    renderPanel();
    expect(await screen.findByText(/CUDA 运行库：状态未知/)).toBeTruthy();
    expect(await screen.findByText(/IndexTTS 运行环境：状态未知/)).toBeTruthy();
    expect(screen.queryByText(/未安装/)).toBeNull();
  });
});
