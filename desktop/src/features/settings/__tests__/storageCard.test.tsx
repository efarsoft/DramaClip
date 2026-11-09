// @vitest-environment jsdom
/** 存储卡片：画像如实上屏（目录/占用/剩余/紧张标记）；dev 态不出迁移按钮、给说明行。 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { App as AntdApp } from 'antd';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { StorageCard } from '../StorageCard';
import type { StorageInfo } from '@dramaclip/protocol';

const api = vi.hoisted(() => ({ info: vi.fn() }));

vi.mock('../../../services/client', () => ({
  storageInfo: (): Promise<StorageInfo> => api.info() as Promise<StorageInfo>,
  migrateDataDir: vi.fn(),
  relaunchApp: vi.fn(),
  dismissStorageHint: vi.fn(),
  pickFolder: vi.fn(),
}));

const INFO: StorageInfo = {
  dataDir: 'C:\\Users\\u\\AppData\\Roaming\\DramaClip\\data',
  defaultDataDir: 'C:\\Users\\u\\AppData\\Roaming\\DramaClip\\data',
  customized: false,
  migrationAvailable: true,
  usage: [
    { name: 'models', bytes: 3 * 1024 ** 3 },
    { name: 'outputs', bytes: 500 * 1024 ** 2 },
  ],
  freeBytes: 10 * 1024 ** 3,
  lowDiskHint: true,
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
    observe(): void { /* jsdom 占位 */ }
    unobserve(): void { /* jsdom 占位 */ }
    disconnect(): void { /* jsdom 占位 */ }
  }
  globalThis.ResizeObserver = NoResizeObserver;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('StorageCard', () => {
  it('画像上屏：目录、GB 级占用、剩余与紧张标记、迁移按钮可用', async () => {
    api.info.mockResolvedValue(INFO);
    render(
      <AntdApp>
        <StorageCard />
      </AntdApp>,
    );
    await waitFor(() => {
      expect(screen.getByText(INFO.dataDir)).toBeTruthy();
    });
    expect(screen.getByText('3.0 GB')).toBeTruthy();
    expect(screen.getByText('500 MB')).toBeTruthy();
    expect(screen.getByText(/空间紧张/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /更改数据目录/ })).toBeTruthy();
  });

  it('dev 态（migrationAvailable=false）：不出迁移按钮，给环境变量说明行', async () => {
    api.info.mockResolvedValue({ ...INFO, migrationAvailable: false });
    render(
      <AntdApp>
        <StorageCard />
      </AntdApp>,
    );
    await waitFor(() => {
      expect(screen.getByText(INFO.dataDir)).toBeTruthy();
    });
    expect(screen.queryByRole('button', { name: /更改数据目录/ })).toBeNull();
    expect(screen.getByText(/DRAMACLIP_DATA_DIR/)).toBeTruthy();
  });

  it('画像取不到：显示不可用行，不装死', async () => {
    api.info.mockRejectedValue(new Error('ipc down'));
    render(
      <AntdApp>
        <StorageCard />
      </AntdApp>,
    );
    await waitFor(() => {
      expect(screen.getByText('存储信息不可用')).toBeTruthy();
    });
  });
});
