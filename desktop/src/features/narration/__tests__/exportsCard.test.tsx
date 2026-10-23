// @vitest-environment jsdom
/**
 * 出片记录行的去向（规格 §1.6）：整行点击不分状态一律进详情页，
 * 而失败/进行中的行 `output_path` 是空的——点进去是一间黑房子。成功的才进得去。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import type { ExportJob } from '@dramaclip/protocol';
import { ExportsCard } from '../ExportsCard';

const navigated = vi.hoisted(() => vi.fn());
const api = vi.hoisted(() => ({ retry: vi.fn() }));

vi.mock('react-router-dom', () => ({ useNavigate: () => navigated }));

vi.mock('../../../services/client', () => ({ exportApi: { retry: api.retry } }));

function job(status: ExportJob['status'], over: Partial<ExportJob> = {}): ExportJob {
  return {
    id: status === 'completed' ? 'ok1' : 'bad1',
    project_id: 'p1',
    status,
    progress: status === 'completed' ? 100 : 40,
    created_at: 0,
    narration_mode: 'full_narration',
    ...(status === 'completed' ? { output_path: 'D:/data/outputs/p1/film_a1b2c3.mp4' } : {}),
    ...(status === 'failed' ? { error: '编剧模型超时' } : {}),
    ...over,
  };
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

beforeEach(() => {
  navigated.mockClear();
  api.retry.mockReset();
});

afterEach(() => {
  cleanup();
});

function row(statusText: string): HTMLElement {
  // 状态徽章在整行容器里：点它＝点这一行（不靠 cursor 样式选元素，那正是要改的东西）
  const cell = screen.getByText(statusText).closest('div');
  expect(cell).not.toBeNull();
  return cell as HTMLElement;
}

function card(exports: ExportJob[]): void {
  render(
    <AntdApp>
      <ExportsCard exports={exports} onRefresh={vi.fn()} />
    </AntdApp>,
  );
}

describe('出片记录行的去向', () => {
  it('成功的成片：点整行进详情页', () => {
    card([job('completed')]);
    fireEvent.click(row('完成'));
    expect(navigated).toHaveBeenCalledWith('/works/ok1');
  });

  it('失败的成片：点整行不进详情页（就地给原因与重试，不把人送进黑房子）', () => {
    card([job('failed')]);
    fireEvent.click(row('失败'));
    expect(navigated).not.toHaveBeenCalled();
  });

  it('进行中的成片：点整行同样不进详情页', () => {
    card([job('running')]);
    fireEvent.click(row('进行中'));
    expect(navigated).not.toHaveBeenCalled();
  });

  it('成功但没有落盘路径（数据异常）：也不进详情页', () => {
    card([job('completed', { output_path: undefined })]);
    fireEvent.click(row('完成'));
    expect(navigated).not.toHaveBeenCalled();
  });

  it('重试被拒：失败原因可见，不静默退回原样', async () => {
    api.retry.mockRejectedValue(new Error('sidecar 已断开'));
    card([job('failed')]);
    // antd 给两字按钮的文案中间插了空格（ accessible 名是「重 试」），正则得容一下
    fireEvent.click(screen.getByRole('button', { name: /^重\s?试$/ }));
    expect(await screen.findByText(/sidecar 已断开/)).toBeTruthy();
  });
});

/**
 * 规格 H3 §3.1.4-5：失败行的原话必须在行内可见文本里，重试再失败也不能只靠一枚会过期的 toast。
 * 判据钉在「这一行的文本」上——toast 是另一个传送门，行内永远取不到。
 */
describe('出片失败行的原话常驻', () => {
  it('原因原文进可见文本，不再只留「原因」两个字（§3.1.4）', () => {
    card([job('failed')]);
    expect(row('失败').textContent).toContain('编剧模型超时');
  });

  it('服务端没给原因：如实写「服务端未给出原因」，不整条吞掉（§3.1.4）', () => {
    card([job('failed', { error: undefined })]);
    expect(row('失败').textContent).toContain('服务端未给出原因');
  });

  it('重试再失败：原话常驻行内，转圈停了话还在（§3.1.5）', async () => {
    api.retry.mockRejectedValue(new Error('sidecar 已断开'));
    card([job('failed')]);
    fireEvent.click(screen.getByRole('button', { name: /^重\s?试$/ }));
    await waitFor(() => {
      expect(row('失败').textContent).toContain('重试失败：sidecar 已断开');
    });
  });
});
