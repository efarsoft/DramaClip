import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { StatusPage } from './StatusPage';

function stubBridge(): void {
  vi.stubGlobal('dramaclip', {
    rpc: vi.fn().mockResolvedValue({ service_version: '2.0.0', protocol_version: 1 }),
    appVersion: vi.fn().mockResolvedValue('2.0.0-test'),
    restartService: vi.fn().mockResolvedValue(undefined),
    onServiceEvent: vi.fn(() => () => undefined),
  });
}

beforeEach(() => {
  stubBridge();
});

it('渲染服务状态页并显示经 RPC 获取的版本', async () => {
  render(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<StatusPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText(/2\.0\.0（协议 v1）/)).toBeTruthy();
  expect(screen.getByText('Python 往返正常 ✅')).toBeTruthy();
});
