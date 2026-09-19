// @vitest-environment jsdom
/**
 * 资产库怎么接待「本地导入」的两种货：清单内的行只多一个来源标记，清单外的目录另起一组。
 *
 * 判据全部出自后端的两个接口：models.list 的 imported 字段、models.import_records 的登记本。
 * 外部资产那一组压根没有「选为生效」——认不出身份（model_id 为 null）是登记本说的，
 * 引擎没接进工厂这件事不由前端猜；登记本读坏了也一样要明说，不能当成库里没货。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ImportRecord, ModelInfo } from '@dramaclip/protocol';
import { AssetLibrary } from '../AssetLibrary';
import { specsFromHealth } from '../machineFit';
import { externalRecord, importRecord, model, report, reportsOf } from './fixtures';

const remove = vi.hoisted(() => vi.fn((modelId: string) => Promise.resolve({ removed: modelId })));

vi.mock('../../../services/client', () => ({
  modelsApi: {
    remove: (modelId: string): Promise<{ removed: string }> => remove(modelId),
    download: vi.fn(() => Promise.resolve({ job_id: 'j' })),
  },
  revealInFolder: vi.fn(() => Promise.resolve({})),
}));

const noop = (): void => {
  // 只验呈现与交回的参数，写回由页面负责
};

/**
 * jsdom 缺两件真浏览器都有的东西：matchMedia（antd 断点用）与 ResizeObserver（浮层定位用）。
 * 都是环境假象，不是被测判据——不补就一律炸在挂载上，看不见组件说了什么。
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
      // 尺寸变化由真浏览器管，这里什么都不必做
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

interface Props {
  models?: ModelInfo[];
  externals?: ImportRecord[];
  importError?: string;
  onImport?: () => void;
  onForget?: (path: string) => void;
}

/** 横幅在不在：文本查不出「空标题的 Alert」，而「读通了就不吱声」正是要钉的那一条。 */
function alerts(): NodeListOf<Element> {
  return document.querySelectorAll('.ant-alert');
}

function library(over: Props = {}): void {
  render(
    <AssetLibrary
      models={over.models ?? []}
      reports={reportsOf(report())}
      specs={specsFromHealth(null)}
      activeModelId={undefined}
      externals={over.externals ?? []}
      importError={over.importError ?? ''}
      onActivate={noop}
      onChanged={noop}
      onVerify={noop}
      onForget={over.onForget ?? noop}
      onImport={over.onImport ?? noop}
    />,
  );
}

afterEach(() => {
  cleanup();
  remove.mockClear();
});

describe('外部资产自成一组', () => {
  it('登记本里认不出身份的那几条进「外部资产 · 引擎未接入」，路径原样摆出来', () => {
    library({ externals: [externalRecord()] });

    expect(screen.getByText(/外部资产 · 引擎未接入（1）/)).toBeTruthy();
    expect(screen.getByText('同事给的模型')).toBeTruthy();
    expect(screen.getByText(externalRecord().path)).toBeTruthy();
    expect(alerts()).toHaveLength(0);
  });

  /** 库内一件模型都没有时，这一组也必须出现——业主刚导入的那份就是它。 */
  it('这一行只有「撤销登记」，没有「选为生效」——不假装能用来骗过导出', () => {
    library({ externals: [externalRecord()] });

    expect(screen.getByRole('button', { name: /撤销登记/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '选为生效' })).toBeNull();
  });

  it('撤销登记交回的是那条登记自己的路径', async () => {
    const onForget = vi.fn();
    library({ externals: [externalRecord({ path: 'E:\\下载\\另一个盘\\模型' })], onForget });
    fireEvent.click(screen.getByRole('button', { name: /撤销登记/ }));

    fireEvent.click(await screen.findByRole('button', { name: '确认撤销' }));

    expect(onForget).toHaveBeenCalledWith('E:\\下载\\另一个盘\\模型');
  });

  it('登记本读坏了：把原话贴出来，不当成库里没货', () => {
    library({ importError: 'imported.json 读不出来：JSON 在第 12 行断了' });

    expect(screen.getByText(/imported\.json 读不出来/)).toBeTruthy();
    expect(alerts()).toHaveLength(1);
  });

  /** 这一行没说谎的地方只有两处：文件没搬过（仅登记），体检没过（按现状）。 */
  it('按现状登记的坏资产：说不搬文件，也说出体检没过', () => {
    library({ externals: [externalRecord({ incomplete: true })] });

    expect(screen.getByText('仅登记路径，不搬文件')).toBeTruthy();
    expect(screen.getByText(/按现状登记，当时体检未通过/)).toBeTruthy();
  });

  /** 对照组钉在同一个用例里：不打字时这一组在，打了字才轮到「不在」说话。 */
  it('搜索关键字同样过一遍外部资产，不留下对不上号的行', () => {
    library({ externals: [externalRecord()] });
    expect(screen.getByText(/外部资产 · 引擎未接入（1）/)).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText(/搜索模型/), {
      target: { value: '不存在的名字' },
    });

    expect(screen.queryByText(/外部资产 · 引擎未接入/)).toBeNull();
  });
});

describe('内置行的「本地导入」来源标记', () => {
  it('带登记的行多一枚来源标记，删除提示说清会动到哪一份', async () => {
    library({ models: [model({ imported: importRecord() })] });

    expect(screen.getByText('本地导入')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '删除这一份' }));

    expect(await screen.findByText(/库里这一份/)).toBeTruthy();
  });

  it('没导入过的行照旧说「随时重新下载」', async () => {
    library({ models: [model()] });

    expect(screen.queryByText('本地导入')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '删除这一份' }));

    expect(await screen.findByText(/随时重新下载/)).toBeTruthy();
  });
});

describe('导入入口', () => {
  it('工具栏那颗按钮把向导叫起来', () => {
    const onImport = vi.fn();
    library({ onImport });

    fireEvent.click(screen.getByRole('button', { name: /导入本地模型/ }));

    expect(onImport).toHaveBeenCalledTimes(1);
  });
});
