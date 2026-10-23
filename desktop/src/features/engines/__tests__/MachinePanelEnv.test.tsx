/** 总览页·运行环境两行的接线与口径（业主需求 2026-09-24：运行环境和 CUDA 状态上总览）。
 *
 * 判据：① 装没装都常驻显示——状态是账本，不是出了事才冒出来的警报；② 缺 IndexTTS
 * 环境给「去安装」落点（跳配音 TTS 页，动作在其家，总览只给结论与落点）；③ 无
 * NVIDIA 显卡时不劝人下没用的 CUDA 运行库；④ 探测失败如实「状态未知」——取不到
 * ≠ 不存在，不冒充「未安装」。
 *
 * H2 §2.3 改了 ②的一处：CUDA 运行库的安装动作从兄弟卡搬进行内——那句话原本让用户
 * 「在本页『转写加速（GPU）』卡下载」，而设备钉在 CPU 时那张卡整行不出现（指路指向
 * 一个不在场的按钮）。现在总览上「未安装」那句旁边就是按钮，且全站只此一处入口。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DeviceProfile, HealthResult, ModelInfo } from '@dramaclip/protocol';
import { localRuntimeApi, runtimeApi, systemApi } from '../../../services/client';
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
    faster_whisper_gpu: { ok: true, ready: false, hint: '', reason: '' },
    vocal_separation_gpu: {
      ok: true,
      ready: false,
      hint: '当前走 CPU（MDX-Net）；安装态不等于运行态，实际以后端回执为准',
      reason: '',
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

const AMD_HEALTH: HealthResult = {
  ...NVIDIA_HEALTH,
  gpu_info: {
    ready: true, vendor: 'amd', name: 'Radeon RX 6600', driver_version: '31.0.21006.1',
    max_cuda_version: '', memory_total_mb: 8188, compute_cap: '',
  },
};

const NONE_HEALTH: HealthResult = {
  ...NVIDIA_HEALTH,
  gpu_info: {
    ready: true, vendor: 'none', name: '', driver_version: '',
    max_cuda_version: '', memory_total_mb: 0, compute_cap: '',
  },
};

/** 判定尾句要有结论可判：给一张 4GB 的本地模型（磁盘/内存都吃得下 → verdict=ok）。 */
const MODEL_4GB: ModelInfo = {
  model_id: 'm1', kind: 'asr', engine: 'faster_whisper', repo_id: 'x/y',
  name: 'Whisper 小模型', required: false, status: 'missing', size_label: '~4GB',
  engine_ready: true,
};

function renderPanel(health: HealthResult = NVIDIA_HEALTH, models: readonly ModelInfo[] = []): void {
  vi.mocked(systemApi.health).mockResolvedValue(health);
  render(
    <MemoryRouter initialEntries={['/engines/overview']}>
      <Routes>
        <Route path="/engines/overview" element={<MachinePanel models={models} />} />
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
    expect(screen.queryByRole('button', { name: /下载运行库/ })).toBeNull();
  });

  it('缺 IndexTTS 环境 → 如实报缺 + 「去安装」落到配音 TTS 页', async () => {
    vi.mocked(localRuntimeApi.status).mockResolvedValue({
      installed: false, dir: '', torch_variant: 'unknown', groups: {},
    });
    renderPanel();
    expect(await screen.findByText(/本地智能运行环境：未装齐/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '去安装' }));
    expect(await screen.findByText('TTS 页已到')).toBeTruthy();
  });

  it('有 N 卡但缺 CUDA 运行库 → 行内就是下载按钮，不再指路兄弟卡（规格 §2.3）', async () => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
    renderPanel();
    expect(await screen.findByText(/CUDA 运行库：未安装 · 转写走 CPU/)).toBeTruthy();
    expect(screen.queryByText(/转写加速（GPU）」卡下载/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /下载运行库/ }));
    await waitFor(() => {
      expect(runtimeApi.install).toHaveBeenCalled();
    });
  });

  it('点下载后装成 → 行内自己重探并转绿，不必刷新页面', async () => {
    vi.mocked(runtimeApi.status)
      .mockResolvedValueOnce({ cublas: false, cudnn: false, installed: false })
      .mockResolvedValue({ cublas: true, cudnn: true, installed: true });
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /下载运行库/ }));
    expect(await screen.findByText(/CUDA 运行库：已安装/)).toBeTruthy();
  });

  it('下载没启起来：原因常驻在这一行，不是一闪而过的 toast（规格 §0.1 配方 3）', async () => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
    vi.mocked(runtimeApi.install).mockRejectedValue(new Error('磁盘空间不足'));
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /下载运行库/ }));
    expect(await screen.findByText(/CUDA 运行库下载失败：磁盘空间不足/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /重试下载运行库/ })).toBeTruthy();
  });

  it('AMD 主机 + 缺 CUDA 运行库 → 说清加速需要 N 卡，当前走 CPU，且不给没用的下载按钮', async () => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
    renderPanel(AMD_HEALTH);
    expect(await screen.findByText(/CUDA 运行库：未安装 · 转写加速需要 NVIDIA CUDA，无需安装，当前走 CPU/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /下载运行库/ })).toBeNull();
  });

  it('无显卡主机（vendor=none）+ 缺运行库 → 说清没卡所以无需安装', async () => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
    renderPanel(NONE_HEALTH);
    expect(await screen.findByText(/CUDA 运行库：未安装 · 未检测到独立显卡，无需安装，转写走 CPU/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /下载运行库/ })).toBeNull();
  });

  it('显卡探测中（gpu_info 缺席）→ 不冒充「未检测到独立显卡」', async () => {
    vi.mocked(runtimeApi.status).mockResolvedValue({ cublas: false, cudnn: false, installed: false });
    renderPanel(NO_GPU_HEALTH);
    expect(await screen.findByText(/CUDA 运行库：未安装 · 显卡状态探测中，暂按 CPU 运行/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /下载运行库/ })).toBeNull();
  });

  it('探测失败 → 「状态未知」，取不到 ≠ 不存在，不冒充未安装', async () => {
    vi.mocked(runtimeApi.status).mockRejectedValue(new Error('pipe broken'));
    vi.mocked(localRuntimeApi.status).mockRejectedValue(new Error('pipe broken'));
    renderPanel();
    expect(await screen.findByText(/CUDA 运行库：状态未知/)).toBeTruthy();
    expect(await screen.findByText(/本地智能运行环境：状态未知/)).toBeTruthy();
    expect(screen.queryByText(/未安装/)).toBeNull();
  });
});

describe('总览页 · 显卡格与判定尾句', () => {
  afterEach(cleanup);

  it('AMD 主机：显卡格报型号与驱动，不再写「未检测到 NVIDIA」', async () => {
    renderPanel(AMD_HEALTH);
    expect(await screen.findByText('Radeon RX 6600 · 驱动 31.0.21006.1')).toBeTruthy();
  });

  it('无显卡主机（vendor=none）：如实说没检测到独立显卡', async () => {
    renderPanel(NONE_HEALTH);
    expect(await screen.findByText('未检测到独立显卡 · 走 CPU')).toBeTruthy();
  });

  it('显卡探测中：不冒充「未检测到」', async () => {
    renderPanel(NO_GPU_HEALTH);
    expect(await screen.findByText('显卡待检测…')).toBeTruthy();
  });

  it('判定尾句：硬编由导出时真试编决定，三厂商都点名', async () => {
    renderPanel(AMD_HEALTH, [MODEL_4GB]);
    expect(await screen.findByText(/视频导出会真试编选择硬件编码器（NVENC \/ AMF \/ QSV）/)).toBeTruthy();
  });
});

describe('总览页 · 设备档位行的 GPU 加速灯', () => {
  afterEach(cleanup);

  /** 灯只许读后端 ready：运行环境装没装是另一笔账，不许在这里覆盖算力结论。 */
  const profileWith = (cap: { ok: boolean; ready: boolean; reason: string }): HealthResult => ({
    ...NVIDIA_HEALTH,
    device_profile: { ...NVIDIA_PROFILE, caps: { indextts2_gpu: { hint: '', ...cap } } },
  });

  it('运行环境已装但后端说 ready=false（torch 是 CPU 轮）→ 灯不亮', async () => {
    vi.mocked(localRuntimeApi.status).mockResolvedValue({
      installed: true, dir: 'C:/rt', torch_variant: 'cpu', groups: { indextts: true },
    });
    renderPanel(profileWith({ ok: true, ready: false, reason: '本地运行环境的 torch 是 CPU 轮' }));
    expect(await screen.findByText(/硬件满足但待运行时：音色克隆/)).toBeTruthy();
    expect(screen.queryByText(/GPU 加速已生效/)).toBeNull();
  });

  it('后端说 ready=true → 灯亮，即使本机运行环境探测显示未装', async () => {
    vi.mocked(localRuntimeApi.status).mockResolvedValue({
      installed: false, dir: '', torch_variant: 'unknown', groups: {},
    });
    renderPanel(profileWith({ ok: true, ready: true, reason: '' }));
    expect(await screen.findByText(/GPU 加速已生效：音色克隆/)).toBeTruthy();
  });
});

/**
 * 规格 H3 §3.3：`…` 只准出现在还活着的过程里。health 取不到是终局无数，
 * 三格必须换 `—` 并把原因写进可见文本（行内或故障行），同时给重试——
 * 挂着一屏「…」让用户以为马上就有答案，是拿占位符冒充进度。
 */
describe('总览页 · 本机信息取不到', () => {
  afterEach(() => {
    cleanup();
    vi.mocked(systemApi.health).mockReset();
  });

  function renderWithFailingHealth(): void {
    vi.mocked(systemApi.health).mockRejectedValue(new Error('sidecar 无响应'));
    render(
      <MemoryRouter initialEntries={['/engines/overview']}>
        <Routes>
          <Route path="/engines/overview" element={<MachinePanel models={[]} />} />
          <Route path="/engines/tts" element={<div>TTS 页已到</div>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it('health 取不到：三格显 —，原因常驻可见文本并给重试', async () => {
    renderWithFailingHealth();
    expect(await screen.findByText(/本机信息取不到：sidecar 无响应/)).toBeTruthy();
    expect(screen.getAllByText('—')).toHaveLength(3);
    expect(screen.queryByText(/待检测…/)).toBeNull();
  });

  it('重试取回了：故障行消失、三格回到真数', async () => {
    renderWithFailingHealth();
    await screen.findByText(/本机信息取不到：/);
    vi.mocked(systemApi.health).mockResolvedValue(NVIDIA_HEALTH);
    fireEvent.click(screen.getByRole('button', { name: /^重\s?试$/ }));
    expect(await screen.findByText(/16 \/ 32 GB 可用/)).toBeTruthy();
    expect(screen.queryByText(/本机信息取不到：/)).toBeNull();
  });

  it('health 取到但缺字段：显 — · 服务端未给出，不挂「…」（规格 §3.3）', async () => {
    renderPanel({ ...NVIDIA_HEALTH, ram_total_gb: undefined, disk_free_gb: undefined });
    expect((await screen.findAllByText('— · 服务端未给出')).length).toBe(2);
  });
});
