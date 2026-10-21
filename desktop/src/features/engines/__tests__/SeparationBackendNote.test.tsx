// @vitest-environment jsdom
/**
 * 人声分离后端提示的「重跑安装」只对可能有 CUDA 的宿主有意义（批次四 Task 9）。
 * 钉的是判据来源：读宿主显卡事实，不读后端文案字符串——后端改一个字就悄悄换路是 §1 的老根因。
 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GpuInfo } from '@dramaclip/protocol';
import type { LocalRuntimeState, OrtGpuState } from '../useLocalRuntime';
import type { MachineSpecs } from '../machineFit';
import { SeparationBackendNote } from '../TtsTab';

const runtime = vi.hoisted(() => ({ state: vi.fn() }));
vi.mock('../useLocalRuntime', () => ({ useLocalRuntime: runtime.state }));

function state(over: Partial<LocalRuntimeState>): LocalRuntimeState {
  return {
    installed: true, groups: {}, ortGpu: null, jobId: '', progress: 0,
    stage: '', busy: false, install: vi.fn(), ...over,
  };
}

const cpuBackend = (reason: string): OrtGpuState => ({
  variant: 'cpu', gpu: false, providers: ['CPUExecutionProvider'], version: '1.19.2', reason,
});

function host(vendor: GpuInfo['vendor'], name: string): GpuInfo {
  return {
    ready: true, vendor, name, driver_version: '31.0.1',
    max_cuda_version: '', memory_total_mb: 8192, compute_cap: '',
  };
}

function note(gpu: GpuInfo | undefined, ortGpu: OrtGpuState | null): void {
  runtime.state.mockReturnValue(state({ ortGpu }));
  const machine: MachineSpecs = { gpu };
  render(<SeparationBackendNote machine={machine} />);
}

describe('人声分离提示 · 重跑安装入口', () => {
  afterEach(cleanup);

  it('AMD 主机 + CPU 后端：装了也不会启用 CUDA EP，不劝人重跑', async () => {
    note(host('amd', 'Radeon RX 6600'), cpuBackend('本机无 CUDA 运行库'));
    expect(await screen.findByText(/CPU · 本机无 CUDA 运行库/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '重跑安装' })).toBeNull();
  });

  it('NVIDIA 主机 + CPU 后端：给重跑入口', async () => {
    note(host('nvidia', 'RTX 4060'), cpuBackend('CUDA EP 初始化失败'));
    expect(await screen.findByRole('button', { name: '重跑安装' })).toBeTruthy();
  });

  it('显卡探测中：不拦重跑', async () => {
    note(undefined, cpuBackend('探测中'));
    expect(await screen.findByRole('button', { name: '重跑安装' })).toBeTruthy();
  });

  it('ORT 后端还没探到 → 一律给重跑入口', async () => {
    note(host('amd', 'Radeon RX 6600'), null);
    expect(await screen.findByRole('button', { name: '重跑安装' })).toBeTruthy();
  });

  it('GPU 后端在跑：只报后端，不摆动作', async () => {
    runtime.state.mockReturnValue(
      state({ ortGpu: { variant: 'cuda', gpu: true, providers: ['CUDAExecutionProvider'], version: '1.19.2', reason: '' } }),
    );
    render(<SeparationBackendNote machine={{ gpu: host('nvidia', 'RTX 4060') }} />);
    expect(await screen.findByText(/GPU（CUDAExecutionProvider，ORT 1\.19\.2）/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '重跑安装' })).toBeNull();
  });
});
