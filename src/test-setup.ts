import '@testing-library/jest-dom';
import { vi } from 'vitest';

// 模拟 Electron API
Object.defineProperty(window, 'electronAPI', {
  value: {
    backend: {
      call: vi.fn(),
      onProgress: vi.fn().mockReturnValue(vi.fn()),
      onLog: vi.fn().mockReturnValue(vi.fn()),
    },
    app: {
      platform: 'win32',
      getVersion: vi.fn(),
      getPath: vi.fn(),
      onEvent: vi.fn().mockReturnValue(vi.fn()),
    },
  },
  writable: true,
  configurable: true,
});
