/** 关于独立页面：内容分区齐全、版本取数、「打开」入口渲染。 */
import { cleanup, render, screen } from '@testing-library/react';
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

describe('AboutPage', () => {
  it('五个分区齐全：项目信息/版本/本地数据/开源许可/授权声明', () => {
    render(<AboutPage />);
    for (const text of [
      '项目信息', '版本', '本地数据', '开源许可', '授权与合规声明',
      'DramaClip', '成品目录', '日志（含 LLM 留痕）',
    ]) {
      expect(screen.getByText(text), `缺 ${text}`).toBeTruthy();
    }
  });

  it('本地数据四行各带「打开」入口', () => {
    render(<AboutPage />);
    expect(screen.getAllByText('打开')).toHaveLength(4);
  });

  it('版权行在页尾', () => {
    render(<AboutPage />);
    expect(screen.getByText(/© 2026 DramaClip/)).toBeTruthy();
  });
});
