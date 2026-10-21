// @vitest-environment jsdom
/**
 * 状态栏 GPU 段按宿主厂商说话（批次四 Task 9）。
 * 钉的是口径不是像素：有卡就说卡名，只有 vendor=none 才说「未检测到独立显卡」，
 * 探测中不许冒充任何一种结论。
 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GpuInfo } from '@dramaclip/protocol';
import { useJobsStore } from '../../../stores/jobs';
import { useUiStore } from '../../../stores/ui';
import { StatusBar } from '../StatusBar';

const api = vi.hoisted(() => ({ health: vi.fn() }));

vi.mock('../../../services/client', () => ({
  appVersion: vi.fn(() => Promise.resolve('0.2.0')),
  systemApi: { health: api.health },
}));

function gpu(over: Partial<GpuInfo> = {}): GpuInfo {
  return {
    ready: true, vendor: 'nvidia', name: 'NVIDIA GeForce RTX 4060', driver_version: '572.10',
    max_cuda_version: '12.8', memory_total_mb: 8188, compute_cap: '8.9', ...over,
  };
}

function renderWith(info: GpuInfo | undefined): void {
  api.health.mockResolvedValue({ gpu_info: info });
  render(<StatusBar />);
}

beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }));
  class NoResizeObserver {
    observe(): void {
      // 尺寸观察交给真浏览器
    }

    unobserve(): void {
      // 同上
    }

    disconnect(): void {
      // 同上
    }
  }
  globalThis.ResizeObserver = NoResizeObserver;
});

beforeEach(() => {
  useJobsStore.setState({ jobs: [], available: false, error: null, serverTimeMs: null, drawerOpen: false });
  useUiStore.setState({ serviceState: 'ready' });
});

afterEach(cleanup);

describe('状态栏 · GPU 段', () => {
  it('NVIDIA：去掉前缀只报型号与驱动', async () => {
    renderWith(gpu());
    expect(await screen.findByText(/GPU · GeForce RTX 4060 · 驱动 572\.10/)).toBeTruthy();
  });

  it('AMD：有卡就说卡名，不说「无独立显卡」', async () => {
    renderWith(gpu({ vendor: 'amd', name: 'Radeon RX 6600', driver_version: '31.0.21006.1', max_cuda_version: '', compute_cap: '' }));
    expect(await screen.findByText(/GPU · Radeon RX 6600 · 驱动 31\.0\.21006\.1/)).toBeTruthy();
    expect(screen.queryByText(/无独立显卡/)).toBeNull();
  });

  it('无独立显卡：如实说没有卡', async () => {
    renderWith(gpu({ vendor: 'none', name: '', driver_version: '', max_cuda_version: '', memory_total_mb: 0, compute_cap: '' }));
    expect(await screen.findByText(/GPU · 未检测到独立显卡 · CPU 模式/)).toBeTruthy();
  });

  it('探测中：不给任何厂商结论', async () => {
    renderWith(undefined);
    expect(await screen.findByText(/GPU · 待检测/)).toBeTruthy();
  });
});
