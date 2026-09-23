// @vitest-environment jsdom
/**
 * 内联失败横幅（卷二 P-A）：端点配置弹窗与提示词编辑器的失败原文常驻上屏，
 * 不再只闪一次 toast——弹窗还开着、草稿还在，失败却没了踪影，就是静默降级。
 */
import { App as AntdApp } from 'antd';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { CloudConfigSection } from '../CloudConfigSection';
import { PromptEditor } from '../PromptEditor';
import { usePrompts } from '../usePrompts';

const api = vi.hoisted(() => ({
  configList: vi.fn(),
  create: vi.fn(),
  test: vi.fn(),
  promptList: vi.fn(),
  promptSave: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  engineConfigsApi: {
    list: api.configList,
    create: api.create,
    update: vi.fn(),
    test: api.test,
    remove: vi.fn(),
    enable: vi.fn(),
  },
  promptsApi: { list: api.promptList, save: api.promptSave, reset: vi.fn() },
}));

const PROMPT = {
  key: 'prompt.scriptwriter_system',
  title: '剧情解说·结构指令',
  description: '每次编剧调用都会带上这段',
  default: '代码里的默认',
  current: '当前生效值',
  overridden: false,
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
  api.configList.mockResolvedValue({ configs: [] });
  api.promptList.mockResolvedValue({ prompts: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function wrapper({ children }: { children: ReactNode }): ReactNode {
  return <AntdApp>{children}</AntdApp>;
}

describe('端点配置弹窗', () => {
  async function openAddModal(): Promise<void> {
    render(<CloudConfigSection domain="llm" />, { wrapper });
    fireEvent.click(await screen.findByRole('button', { name: /添加配置/ }));
    await screen.findByText('端点配置（OpenAI 兼容）');
  }

  it('保存失败：原因原文进弹窗横幅，弹窗不关、草稿不丢', async () => {
    api.create.mockRejectedValue(new Error('SQLite 被锁'));
    await openAddModal();

    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '我的端点' } });
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));

    expect(await screen.findByText(/保存失败：SQLite 被锁/)).toBeTruthy();
    expect(screen.getByText(/草稿仍在表单里/)).toBeTruthy();
    // 弹窗没被失败关掉：标题还在
    expect(screen.getByText('端点配置（OpenAI 兼容）')).toBeTruthy();
  });

  it('名称为空：校验原因也进横幅，不闪 toast 就算完', async () => {
    await openAddModal();
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));
    expect(await screen.findByText(/请填写配置名称/)).toBeTruthy();
  });

  it('连接测试未通过：原因常驻，且说清「仍可保存」的后果边界', async () => {
    api.test.mockResolvedValue({ ok: false, error: '401 无效的 key' });
    await openAddModal();

    fireEvent.change(screen.getByLabelText('API 地址'), { target: { value: 'https://api.example.com/v1' } });
    fireEvent.change(screen.getByLabelText('模型名'), { target: { value: 'qwen-plus' } });
    fireEvent.click(screen.getByRole('button', { name: /测试连接/ }));

    expect(await screen.findByText(/连接测试未通过：401 无效的 key/)).toBeTruthy();
    expect(screen.getByText(/仍可保存/)).toBeTruthy();
  });
});

describe('提示词编辑器', () => {
  it('保存失败进 saveError 状态，弹窗保持可重试', async () => {
    api.promptSave.mockRejectedValue(new Error('设置写入失败：磁盘满'));
    const { result } = renderHook(() => usePrompts(), { wrapper });
    await waitFor(() => {
      expect(result.current.prompts).toEqual([]);
    });

    act(() => {
      result.current.openEdit(PROMPT);
    });
    await act(async () => {
      await result.current.save();
    });

    expect(result.current.saveError).toBe('设置写入失败：磁盘满');
    expect(result.current.editing).not.toBeNull();
  });

  it('saveError 渲染成弹窗内横幅：原文 + 草稿还在的后果说明', async () => {
    render(
      <PromptEditor
        editing={PROMPT}
        draft="改了一半的稿"
        saving={false}
        saveError="设置写入失败：磁盘满"
        onDraft={() => undefined}
        onSave={() => undefined}
        onClose={() => undefined}
      />,
      { wrapper },
    );
    expect(await screen.findByText(/保存失败：设置写入失败：磁盘满/)).toBeTruthy();
    expect(screen.getByText(/草稿仍在编辑框里/)).toBeTruthy();
  });
});
