// @vitest-environment jsdom
/**
 * 成品库页（09-10 §4.5 / 卷三图5 / §3.4）：失败态不永久转圈、自检筛选、
 * 徽章三态上屏、批量条量化确认与删除入回收、补测自检开抽屉。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import type { SelfCheck, WorkItem } from '@dramaclip/protocol';
import { useJobsStore } from '../../../stores/jobs';
import { useUiStore } from '../../../stores/ui';
import { WorksPage } from '../WorksPage';

const api = vi.hoisted(() => ({
  listWorks: vi.fn(),
  projectList: vi.fn(),
  selfcheck: vi.fn(),
  deleteWork: vi.fn(),
  revealInFolder: vi.fn(),
  pickFolder: vi.fn(),
  copyFiles: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  listWorks: api.listWorks,
  projectApi: { list: api.projectList },
  exportApi: { selfcheck: api.selfcheck, delete: api.deleteWork },
  revealInFolder: api.revealInFolder,
  pickFolder: api.pickFolder,
  copyFiles: api.copyFiles,
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
}));

function work(over: Partial<WorkItem> = {}): WorkItem {
  return {
    id: 'w1',
    project_id: 'p1',
    project_name: '替嫁新娘',
    narration_mode: 'full_narration',
    output_path: 'D:/data/outputs/p1/a.mp4',
    duration_s: 134,
    size_bytes: 268435456, // 0.25 GB
    completed_at: 1758600000000,
    narration_plan_id: 'plan1',
    angle: '角度一 · 替身真相',
    episode_ids: ['e1', 'e2'],
    selfcheck: null,
    selfcheck_state: null,
    ...over,
  };
}

const FULL_CHECK: SelfCheck = {
  checked_at: 1758600000000,
  duration: { pass: true, measured_s: 134, budget_s: 134, tolerance_s: 10.7 },
  narration: { pass: true, has_audio: true, expected: 'many', planned_segments: 8 },
  silence: { pass: null },
  freeze: { pass: false, max_freeze_s: 3.2 },
};

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
      // 浮层尺寸由真浏览器观察
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

function page(): void {
  render(
    <MemoryRouter>
      <AntdApp>
        <WorksPage />
      </AntdApp>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useUiStore.getState().setServiceState('ready');
  useJobsStore.setState({ drawerOpen: false });
  api.listWorks.mockResolvedValue([]);
  api.projectList.mockResolvedValue([]);
  api.revealInFolder.mockResolvedValue({ ok: true });
  api.deleteWork.mockResolvedValue({ ok: true, trashed: ['D:/data/.trash/x/a.mp4'], missing: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('失败态（意见01：取不到 ≠ 一直在取）', () => {
  it('加载失败原文上屏 + 真重试，不永久转圈', async () => {
    api.listWorks.mockRejectedValue(new Error('管道断开'));
    page();
    expect(await screen.findByText(/成品列表加载失败：管道断开/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeTruthy();
    expect(document.querySelector('.ant-card-loading')).toBeNull();
  });

  it('点重试真重拉：成功后横幅消失、剧分组出现', async () => {
    api.listWorks.mockRejectedValueOnce(new Error('管道断开'));
    page();
    await screen.findByText(/成品列表加载失败/);
    api.listWorks.mockResolvedValue([work()]);
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }));
    expect(await screen.findByText('替嫁新娘')).toBeTruthy();
    expect(screen.queryByText(/成品列表加载失败/)).toBeNull();
  });
});

describe('成品卡（图5）', () => {
  it('角度名（金）、绝对时间、四项徽章三态同屏', async () => {
    api.listWorks.mockResolvedValue([
      work({ id: 'w1', selfcheck: FULL_CHECK, selfcheck_state: 'partial' }),
      work({ id: 'w2', output_path: 'D:/data/outputs/p1/b.mp4', selfcheck: null }),
    ]);
    page();
    expect((await screen.findAllByText('角度一 · 替身真相')).length).toBe(2);
    // 徽章：绿勾、红叉、灰「—」三种视觉各自在场
    expect(screen.getAllByText('✓ 时长达标')).toHaveLength(1);
    expect(screen.getByText('✕ 有长冻结帧')).toBeTruthy();
    // 静音「—」两处：已检卡里量不到的项 + 未检卡的四项全灰
    expect(screen.getAllByText('— 静音段未检')).toHaveLength(2);
    // 未自检的卡四项全灰（时长未检只可能来自 w2）
    expect(screen.getByText('— 时长未检')).toBeTruthy();
    // 完成时间是绝对钟点，不是「昨天」
    expect(screen.getAllByText(/9\/2[0-9] \d{2}:\d{2}/).length).toBeGreaterThan(0);
  });

  it('方案已删的卡：方案卡按钮禁用（缺席而非假控件）', async () => {
    api.listWorks.mockResolvedValue([work({ narration_plan_id: null, angle: null })]);
    page();
    await screen.findByText('替嫁新娘');
    const jump = screen.getByRole('button', { name: /方案卡/ });
    expect((jump as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('自检筛选（#30）', () => {
  it('点「自检通过」按状态重拉', async () => {
    api.listWorks.mockResolvedValue([]);
    page();
    await screen.findByText('还没有完成的成片——去项目里生成并导出第一个作品吧');
    fireEvent.click(screen.getByRole('button', { name: '自检通过' }));
    expect(api.listWorks).toHaveBeenLastCalledWith(60, 'passed');
    fireEvent.click(screen.getByRole('button', { name: '全部' }));
    expect(api.listWorks).toHaveBeenLastCalledWith(60, undefined);
  });
});

describe('批量条与删除（§3.4 危险操作四规矩）', () => {
  it('勾选两条：量化「已选 2 条 · 共 0.50 GB」，删除走量化确认并逐条 RPC', async () => {
    api.listWorks.mockResolvedValue([
      work({ id: 'w1' }),
      work({ id: 'w2', output_path: 'D:/data/outputs/p1/b.mp4' }),
    ]);
    page();
    await screen.findByText('替嫁新娘');
    // 两条成片 → 两个勾选框，全部勾上
    for (const box of screen.getAllByRole('checkbox')) {
      fireEvent.click(box);
    }
    expect(await screen.findByText(/已选/)).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
    expect(screen.getByText('0.50 GB')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /删\s*除/ }));
    // 确认框量化 + 回收站去向说明（可恢复性必须写清）；confirm 的标题与正文各自成节点
    expect((await screen.findAllByText(/删除 2 条成片/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/共 0\.50 GB/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/回收站/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: /移入回收/ }));
    await vi.waitFor(() => {
      expect(api.deleteWork).toHaveBeenCalledTimes(2);
    });
    expect(api.deleteWork).toHaveBeenCalledWith('w1');
  });

  it('复制到：先选目录再复制，取消则不动', async () => {
    api.listWorks.mockResolvedValue([work()]);
    api.pickFolder.mockResolvedValue(null);
    page();
    await screen.findByText('替嫁新娘');
    for (const box of screen.getAllByRole('checkbox')) {
      fireEvent.click(box);
    }
    fireEvent.click(await screen.findByRole('button', { name: /复制到/ }));
    await vi.waitFor(() => {
      expect(api.pickFolder).toHaveBeenCalled();
    });
    expect(api.copyFiles).not.toHaveBeenCalled();
  });
});

describe('补测自检', () => {
  it('排入作业即开任务抽屉；无待补测如实说', async () => {
    api.selfcheck.mockResolvedValue({ ok: true, job_id: 'j1', queued: 3 });
    page();
    fireEvent.click(await screen.findByRole('button', { name: /补测自检/ }));
    await vi.waitFor(() => {
      expect(useJobsStore.getState().drawerOpen).toBe(true);
    });

    useJobsStore.setState({ drawerOpen: false });
    api.selfcheck.mockResolvedValue({ ok: true, job_id: null, queued: 0 });
    fireEvent.click(screen.getByRole('button', { name: /补测自检/ }));
    await vi.waitFor(() => {
      expect(api.selfcheck).toHaveBeenCalledTimes(2);
    });
    expect(useJobsStore.getState().drawerOpen).toBe(false);
  });
});
