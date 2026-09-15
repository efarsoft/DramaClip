/** 关于覆盖层（规格 §4.8）：内容四块 + Esc/遮罩关闭 + 不自动弹出。 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/client', () => ({
  appVersion: vi.fn().mockResolvedValue('2.0.0'),
  appPaths: vi.fn().mockResolvedValue({
    root: 'D:/data', outputs: 'D:/data/outputs', models: 'D:/data/models', logs: 'D:/data/logs',
  }),
  revealInFolder: vi.fn().mockResolvedValue(undefined),
  systemApi: { ping: vi.fn().mockResolvedValue({ service_version: '2.0.0', protocol_version: 1 }) },
}));

import { AboutPage } from '../AboutPage';

afterEach(cleanup);

function LocationProbe(): React.ReactElement {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
}

function renderAbout() {
  render(
    <MemoryRouter initialEntries={['/about']}>
      <Routes>
        <Route path="/about" element={<AboutPage />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AboutPage', () => {
  it('四块信息齐全：版本/本地数据/开源许可/授权声明', () => {
    renderAbout();
    for (const text of ['版本', '本地数据', '开源许可', '授权与合规声明', '成品目录']) {
      expect(screen.getByText(text), `缺 ${text}`).toBeTruthy();
    }
    expect(screen.getAllByText('打开')).toHaveLength(4);
  });

  it('点遮罩关闭并回到首页（深链 /about 的关闭落点）', async () => {
    renderAbout();
    screen.getByRole('presentation').click();
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/');
    });
  });

  it('内容卡片点击不冒泡关闭（点「打开」等控件不得误关）', () => {
    renderAbout();
    screen.getByText('DramaClip').click();
    expect(screen.getByRole('presentation')).toBeTruthy();
  });
});
