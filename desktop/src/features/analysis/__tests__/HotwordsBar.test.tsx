// @vitest-environment jsdom
/** 剧级热词条：改了才存（project.update_settings）、存失败如实报错、外部刷新不覆盖草稿未保存态。 */
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { HotwordsBar, HOTWORDS_KEY } from '../HotwordsBar';

const updateSettings = vi.fn<
  (projectId: string, settings: Record<string, string>) => Promise<unknown>
>();

vi.mock('../../../services/client', () => ({
  projectApi: { updateSettings: (id: string, values: Record<string, string>) => updateSettings(id, values) },
}));

// vitest 未开 globals，RTL 的自动 cleanup 不会注册；查询默认打在 document.body 上必须逐条清台
afterEach(cleanup);

/** 挂载并返回**本次渲染作用域内**的热词输入框（不查全局 DOM，防跨用例串台）。 */
function mount(value: string, onSaved = vi.fn()): HTMLInputElement {
  const { getByPlaceholderText } = render(
    <AntdApp>
      <HotwordsBar projectId="p1" value={value} onSaved={onSaved} />
    </AntdApp>,
  );
  return getByPlaceholderText(
    '这部剧的人名/专名，顿号、逗号或空格分隔——转写时永远排最前',
  ) as HTMLInputElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  updateSettings.mockResolvedValue({});
});

describe('HotwordsBar（剧级热词）', () => {
  it('改动后失焦保存到本项目设置，并回话「下次分析生效」', async () => {
    const onSaved = vi.fn();
    const input = mount('', onSaved);
    fireEvent.change(input, { target: { value: ' 骆养性、崇祯 ' } });
    fireEvent.blur(input);
    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith('p1', { [HOTWORDS_KEY]: '骆养性、崇祯' });
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('没改就不保存（失焦不产生写请求）', () => {
    const input = mount('骆养性、崇祯');
    fireEvent.blur(input);
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it('清空也保存（空串落库，等于「本剧不点名」）', async () => {
    const input = mount('骆养性、崇祯');
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.blur(input);
    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith('p1', { [HOTWORDS_KEY]: '' });
    });
  });

  it('保存失败如实报错，不冒充成功', async () => {
    updateSettings.mockRejectedValue(new Error('RPC 超时'));
    const onSaved = vi.fn();
    const input = mount('', onSaved);
    fireEvent.change(input, { target: { value: '崇祯' } });
    await act(async () => {
      fireEvent.blur(input);
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(document.body.textContent).toContain('没存上');
    });
    expect(onSaved).not.toHaveBeenCalled();
  });
});
