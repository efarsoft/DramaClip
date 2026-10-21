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
import type { DeviceProfile, HealthResult } from '@dramaclip/protocol';
import { indexttsApi, localRuntimeApi, runtimeApi, systemApi } from '../../../services/client';
import { MachinePanel } from '../MachinePanel';

vi.mock('../../../services/client', () => ({
  engineConfigsApi: {
    list: vi.fn(() => Promise.resolve({ configs: [] })),
    create: vi.fn(() => Promise.resolve({ id: 'cfg1', domain: '', name: '', base_url: '', api_key: '', model: '', enabled: 0, api_key_masked: '' })),
    update: vi.fn(() => Promise.resolve({})),
    remove: vi.fn(() => Promise.resolve({ ok: true })),
    enable: vi.fn(() => Promise.resolve({})),
    enableLocal: vi.fn(() => Promise.resolve({ ok: true })),
    test: vi.fn(() => Promise.resolve({ ok: true, latency_s: 0.1, error: null })),
  },

  systemApi: { health: vi.fn(() => Promise.resolve({})) },
  runtimeApi: {
    status: vi.fn(() => Promise.resolve({ cublas: true, cudnn: true, installed: true })),
    install: vi.fn(() => Promise.resolve({})),
  },
  indexttsApi: {
    status: vi.fn(() => Promise.resolve({ installed: true, dir: 'C:/rt' })),
    install: vi.fn(() => Promise.resolve({ job_id: 'j' })),
  },
  localRuntimeApi: {
    status: vi.fn(() =>
      Promise.resolve({
        installed: true, dir: 'C:/rt', torch_variant: 'cuda',
        groups: { indextts: true, funasr: true, kokoro: true, torch: true },
      }),
    ),
    install: vi.fn(() => Promise.resolve({ job_id: 'j' })),
  },
}));

// 单独成常量：HealthResult.device_profile 是可选字段，spread 它会让覆盖对象的
// 属性全变可选、对不上 DeviceProfile 的必填面（tsc 既有红，2026-10-19 顺手修）。
const NVIDIA_PROFILE: DeviceProfile = {
  tier: 'entry',
  tier_label: '标准（6-11GB 显存）',
  vendor: 'nvidia',
  gpu_name: 'RTX 4060',
  memory_total_mb: 8188,
  max_cuda_version: '12.8',
  cuda_runtime_installed: false,
  caps: {
    faster_whisper_gpu: { ok: true, ready: false, hint: '' },
    vocal_separation_gpu: {
      ok: true,
      ready: false,
      hint: '当前走 CPU（MDX-Net）；安装态不等于运行态，实际以后端回执为准',
    },
  },
  driver_guidance: { needed: false, url: 'https://x', min_driver: '551', reason: '' },
  recommendation: '本地 GPU 引擎可启用（安装 CUDA 运行库后生效）',
};

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
    memory_total_mb: 8188,
    compute_cap: '8.9',
  },
  ram_total_gb: 32,
  ram_free_gb: 16,
  disk_free_gb: 200,
  device_profile: NVIDIA_PROFILE,
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

describe('总览页 · 设备档位行', () => {
  afterEach(cleanup);

  it('health 带 device_profile → 档位标签+推荐文案常驻', async () => {
    renderPanel();
    expect(await screen.findByText(/标准（6-11GB 显存）/)).toBeTruthy();
    expect(await screen.findByText(/本地 GPU 引擎可启用/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /更新驱动/ })).toBeNull();
  });

  it('驱动过老 → 给更新驱动入口', async () => {
    renderPanel({
      ...NVIDIA_HEALTH,
      device_profile: {
        ...NVIDIA_PROFILE,
        tier: 'low',
        tier_label: '入门（<6GB 显存）',
        driver_guidance: {
          needed: true,
          url: 'https://nvidia.cn/drivers',
          min_driver: '551',
          reason: '驱动支持的 CUDA 上限低于 12',
        },
      },
    });
    expect(await screen.findByRole('button', { name: /更新驱动（需 551\+）/ })).toBeTruthy();
  });
});

describe('总览页 · 运行环境状态行', () => {
  afterEach(cleanup);

  it('两个环境都装好 → 两行常驻绿账，不给多余动作', async () => {
    renderPanel();
    expect(await screen.findByText(/CUDA 运行库：已安装/)).toBeTruthy();
    expect(await screen.findByText(/本地智能运行环境：已安装/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '去安装' })).toBeNull();
  });

  it('缺 IndexTTS 环境 → 如实报缺 + 「去安装」落到配音 TTS 页', async () => {
    vi.mocked(indexttsApi.status).mockResolvedValue({ installed: false, dir: '' });
    vi.mocked(localRuntimeApi.status).mockResolvedValue({
      installed: false, dir: '', torch_variant: 'unknown', groups: {},
    });
    renderPanel();
    expect(await screen.findByText(/本地智能运行环境：未装齐/)).toBeTruthy();
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
    vi.mocked(localRuntimeApi.status).mockRejectedValue(new Error('pipe broken'));
    renderPanel();
    expect(await screen.findByText(/CUDA 运行库：状态未知/)).toBeTruthy();
    expect(await screen.findByText(/本地智能运行环境：状态未知/)).toBeTruthy();
    expect(screen.queryByText(/未安装/)).toBeNull();
  });
});
