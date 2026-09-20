// @vitest-environment jsdom
/**
 * 提示词 tab 的状态行为：编辑框里看到的必须就是当前生效的那份。
 *
 * 草稿若从空白起步，用户点「保存」会把整条 system prompt 存成空串或被清空的文本，
 * 界面上却显示「已保存」——这条用例就是钉住那个入口。
 */
import { App as AntdApp } from 'antd';
import { renderHook, act, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { usePrompts } from '../usePrompts';

const list = vi.hoisted(() => vi.fn());
const save = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  promptsApi: {
    list: (): unknown => list(),
    save: (key: string, text: string): unknown => save(key, text),
    reset: vi.fn(),
  },
}));

const OVERRIDDEN = {
  key: 'prompt.scriptwriter_system',
  title: '剧情解说·结构指令',
  description: '',
  default: '代码里的默认',
  current: '业主改过的现值',
  overridden: true,
};

afterEach(() => {
  list.mockReset();
  save.mockReset();
});

function wrapper({ children }: { children: ReactNode }): ReactNode {
  return <AntdApp>{children}</AntdApp>;
}

it('打开编辑时草稿灌的是当前生效值，不是空白', async () => {
  list.mockResolvedValue({ prompts: [OVERRIDDEN] });
  const { result } = renderHook(() => usePrompts(), { wrapper });
  await waitFor(() => {
    expect(result.current.prompts).toHaveLength(1);
  });

  act(() => {
    result.current.openEdit(OVERRIDDEN);
  });
  expect(result.current.draft).toBe('业主改过的现值');

  await act(async () => {
    await result.current.save();
  });
  expect(save).toHaveBeenCalledWith(OVERRIDDEN.key, '业主改过的现值');
});

it('加载失败时把真因说出口，不只报"加载失败"', async () => {
  list.mockRejectedValue(new Error('方法未注册：prompts.list'));
  const { result } = renderHook(() => usePrompts(), { wrapper });
  await waitFor(() => {
    expect(result.current.prompts).toEqual([]);
  });
  expect(document.body.textContent).toContain('方法未注册：prompts.list');
});
