// @vitest-environment jsdom
/**
 * 接口地址这个框只该出现在真消费它的域：asr_cloud/tts_cloud 由服务商 SDK 固定端点发起，
 * 后端对这两个域拒收地址值。界面留着框就是「填了不生效」的死控件，
 * 留着旧行里的地址原样回送就是保存必失败——口径与后端 _DOMAIN_FIELDS 同一份。
 */
import { App as AntdApp } from 'antd';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { CloudConfigsPane } from '../CloudDomainUI';
import type { FormState } from '../CloudConfigModal';
import type { EngineConfigActions } from '../useEngineConfigs';

vi.mock('../../../services/client', () => ({
  engineConfigsApi: {
    list: vi.fn(() => Promise.resolve({ configs: [] })),
    create: vi.fn(() => Promise.resolve({})),
    update: vi.fn(() => Promise.resolve({})),
    remove: vi.fn(() => Promise.resolve({ ok: true })),
    enable: vi.fn(() => Promise.resolve({})),
    enableLocal: vi.fn(() => Promise.resolve({ ok: true })),
    test: vi.fn(() => Promise.resolve({ ok: true, latency_s: 0.1, error: null })),
  },
}));

/**
 * jsdom 缺 matchMedia 与 ResizeObserver（antd 断点与浮层定位要用），
 * 都是环境假象，不是被测判据。
 */
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
      // 尺寸变化由真浏览器管
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

const noop = (): void => {
  // 只验弹窗交回什么，落库由 actions 负责
};

function actions(over: Partial<EngineConfigActions> = {}): EngineConfigActions {
  return {
    configs: [],
    saving: false,
    saveError: null,
    editing: null,
    adding: true,
    openAdd: noop,
    openEdit: noop,
    close: noop,
    save: noop,
    enable: noop,
    enableLocal: () => Promise.resolve(),
    remove: noop,
    ...over,
  };
}

function wrapper({ children }: { children: ReactNode }): ReactNode {
  return <AntdApp>{children}</AntdApp>;
}

function pane(domain: string, over: Partial<EngineConfigActions> = {}): void {
  render(<CloudConfigsPane domain={domain} actions={actions(over)} note="说明" />, { wrapper });
}

describe('云端配置弹窗的接口地址字段', () => {
  afterEach(cleanup);

  it('SDK 固定端点的域不给接口地址框，按钮文案里也不提它', () => {
    pane('asr_cloud');
    expect(screen.queryByLabelText('API 地址')).toBeNull();
    expect(screen.queryByRole('button', { name: /接口地址/ })).toBeNull();
    expect(screen.getByLabelText('模型名')).toBeTruthy();
  });

  it('OpenAI 兼容端点的域照旧给（image 真消费这个值）', () => {
    pane('image');
    expect(screen.getByLabelText('API 地址')).toBeTruthy();
  });

  it('旧行里存着的地址不再原样送回：保存交回的 base_url 必须是空', () => {
    const save = vi.fn();
    const legacy: FormState = {
      name: '旧配置',
      base_url: 'https://dashscope.aliyuncs.com',
      api_key: '',
      model: 'qwen-audio-3.1-asr-flash',
    };
    pane('asr_cloud', { adding: false, editing: { id: 'cfg-1', form: legacy }, save });
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));
    expect(save).toHaveBeenCalledWith({ ...legacy, base_url: '' });
  });
});
