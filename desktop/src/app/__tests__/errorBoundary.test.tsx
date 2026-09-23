// @vitest-environment jsdom
/** 错误边界三补（卷二 P-A）：复制错误原文 / 重启服务 / 回工作台——崩溃页也是界面，恢复出口必须全是真的。 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from '../ErrorBoundary';

const client = vi.hoisted(() => ({ restartService: vi.fn() }));

vi.mock('../../services/client', () => ({ restartService: client.restartService }));

const writeText = vi.hoisted(() => vi.fn());

/**
 * 投弹开关。React 并发渲染会整树重试：抛一次就不抛的子组件在重试里「恢复」，
 * 边界根本接不到错误——所以开关不在组件内自翻，由用例在恢复动作前显式翻。
 */
let armed = true;

function Boom(): React.ReactElement | null {
  if (armed) {
    throw new Error('渲染炸了');
  }
  return <div>工作台内容</div>;
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
  armed = true;
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  window.location.hash = '';
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe('ErrorBoundary 崩溃现场', () => {
  it('崩溃不白屏：错误原文 + 四个恢复出口全在场', async () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(await screen.findByText('界面出了点问题')).toBeTruthy();
    expect(screen.getByText('渲染炸了')).toBeTruthy();
    expect(screen.getByRole('button', { name: '重新加载' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '重启服务' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '复制错误' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '回工作台' })).toBeTruthy();
  });
});

describe('ErrorBoundary 恢复出口', () => {
  it('复制错误：写入剪贴板的是 message+stack，成功要回执', async () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    fireEvent.click(await screen.findByRole('button', { name: '复制错误' }));
    expect(await screen.findByRole('button', { name: '已复制' })).toBeTruthy();
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0]?.[0]).toContain('渲染炸了');
  });

  it('复制失败也说出来，不假装已复制', async () => {
    writeText.mockRejectedValue(new Error('剪贴板权限被拒'));
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    fireEvent.click(await screen.findByRole('button', { name: '复制错误' }));
    expect(await screen.findByRole('button', { name: '复制失败，请手动截图' })).toBeTruthy();
  });

  it('回工作台：清崩溃态、跳 #/、内容渲染回来', async () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    const back = await screen.findByRole('button', { name: '回工作台' });
    armed = false;
    fireEvent.click(back);
    expect(await screen.findByText('工作台内容')).toBeTruthy();
    expect(window.location.hash).toBe('#/');
  });

  it('重启服务：走 restartService，成功后清崩溃态回工作台', async () => {
    client.restartService.mockResolvedValue(undefined);
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    const restart = await screen.findByRole('button', { name: '重启服务' });
    armed = false;
    fireEvent.click(restart);
    await waitFor(() => {
      expect(client.restartService).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText('工作台内容')).toBeTruthy();
    expect(window.location.hash).toBe('#/');
  });
});
