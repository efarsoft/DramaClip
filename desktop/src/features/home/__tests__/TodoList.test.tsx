/** 待办列表：每条必须带一个能点的动作（规格 §4.1「不是通知」）。 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TodoList } from '../TodoList';
import type { TodoItem } from '../todos';

afterEach(cleanup);

function item(over: Partial<TodoItem> = {}): TodoItem {
  return {
    key: 'k1',
    text: '《A》分析任务失败',
    detail: 'ffmpeg 退出码 1',
    severity: 'error',
    action: { kind: 'navigate', label: '去处理', path: '/projects/p1/analysis' },
    ...over,
  };
}

function renderList(items: readonly TodoItem[]) {
  const onNavigate = vi.fn();
  const onRestartService = vi.fn();
  const view = render(
    <MemoryRouter>
      <TodoList items={items} onNavigate={onNavigate} onRestartService={onRestartService} />
    </MemoryRouter>,
  );
  return { ...view, onNavigate, onRestartService };
}

function dotBackground(container: HTMLElement): string {
  const dot = container.querySelector('[data-testid="severity-dot"]');
  expect(dot).not.toBeNull();
  return (dot as HTMLElement).style.background;
}

describe('TodoList', () => {
  it('空数组整块不渲染（缺席而非空壳，也不写"暂无待办"）', () => {
    const { container } = renderList([]);
    expect(container.querySelector('section')).toBeNull();
    expect(screen.queryByText('今日待办')).toBeNull();
  });

  it('每条渲染结论文本与动作按钮，并在 extra 里报条数', () => {
    renderList([
      item(),
      item({ key: 'k2', text: '第二条', action: { kind: 'navigate', label: '去下载', path: '/engines/asr' } }),
    ]);
    expect(screen.getByText('《A》分析任务失败')).toBeTruthy();
    expect(screen.getByText('第二条')).toBeTruthy();
    expect(screen.getByRole('button', { name: '去处理' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '去下载' })).toBeTruthy();
    expect(screen.getByText('2 条')).toBeTruthy();
  });

  it('navigate 动作点下去带着目标路径回调', () => {
    const { onNavigate } = renderList([item()]);
    screen.getByRole('button', { name: '去处理' }).click();
    expect(onNavigate).toHaveBeenCalledWith('/projects/p1/analysis');
  });

  it('restart-service 动作触发重启回调，不试图导航', () => {
    const { onNavigate, onRestartService } = renderList([
      item({ key: 'svc', action: { kind: 'restart-service', label: '重启服务' } }),
    ]);
    screen.getByRole('button', { name: '重启服务' }).click();
    expect(onRestartService).toHaveBeenCalledTimes(1);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it('detail 非空时挂在 title 上，原文不截断', () => {
    const long = 'x'.repeat(300);
    renderList([item({ detail: long })]);
    expect(screen.getByTitle(long)).toBeTruthy();
  });

  it('detail 为空时不挂空 title', () => {
    const { container } = renderList([item({ detail: '' })]);
    expect(container.querySelector('[title=""]')).toBeNull();
  });

  it('error 用 status/error（#F87171），不用钩子红 #FF4D4F', () => {
    const { container } = renderList([item({ severity: 'error' })]);
    expect(dotBackground(container)).toBe('rgb(248, 113, 113)'); // #F87171
  });

  it('warning 用 status/warning、info 用 status/info（规格 §3.2）', () => {
    const warning = renderList([item({ severity: 'warning' })]);
    expect(dotBackground(warning.container)).toBe('rgb(251, 191, 36)'); // #FBBF24
    cleanup();
    const info = renderList([item({ severity: 'info' })]);
    expect(dotBackground(info.container)).toBe('rgb(96, 165, 250)'); // #60A5FA
  });
});
