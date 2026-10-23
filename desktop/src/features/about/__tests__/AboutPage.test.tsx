/** 关于独立页面：内容分区齐全、版本取数、「打开」入口渲染。 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { systemApi } from '../../../services/client';

vi.mock('../../../services/client', () => ({
  localRuntimeApi: {
    status: vi.fn().mockResolvedValue({
      installed: true, dir: '', torch_variant: 'cuda',
      groups: { indextts: true, funasr: true, kokoro: true, torch: true },
    }),
    install: vi.fn().mockResolvedValue({ job_id: 'j-local' }),
  },
  appVersion: vi.fn().mockResolvedValue('2.0.0'),
  appPaths: vi.fn().mockResolvedValue({
    root: 'D:/data', outputs: 'D:/data/outputs', models: 'D:/data/models', logs: 'D:/data/logs',
    trash: 'D:/data/.trash',
  }),
  revealInFolder: vi.fn().mockResolvedValue({ ok: true }),
  systemApi: { ping: vi.fn().mockResolvedValue({ service_version: '2.0.0', protocol_version: 1 }) },
}));

import { AboutPage } from '../AboutPage';

afterEach(cleanup);

function page(): void {
  render(
    <AntdApp>
      <AboutPage />
    </AntdApp>,
  );
}

describe('AboutPage', () => {
  it('五个分区齐全：项目信息/版本/本地数据/开源许可/授权声明', () => {
    page();
    for (const text of [
      '项目信息', '版本', '本地数据', '开源许可', '授权与合规声明',
      'DramaClip', '成品目录', '日志（含 LLM 留痕）',
    ]) {
      expect(screen.getByText(text), `缺 ${text}`).toBeTruthy();
    }
  });

  it('本地数据五行各带「打开」入口（含回收站，§3.4 可达性）', () => {
    page();
    expect(screen.getAllByText('打开')).toHaveLength(5);
    expect(screen.getByText(/回收站/)).toBeTruthy();
  });

  it('版权行在页尾', () => {
    page();
    expect(screen.getByText(/© 2026 DramaClip/)).toBeTruthy();
  });
});

/**
 * 规格 H3 §3.3：ping 被 catch 吞掉后，版本行永远挂着「…」——用户读到的是「马上就出」，
 * 真相是「这一屏答不上来」。终局无数必须 `—` + 原话 + 重试。
 */
describe('版本行的取数终态', () => {
  afterEach(() => {
    vi.mocked(systemApi.ping).mockReset();
    vi.mocked(systemApi.ping).mockResolvedValue({ service_version: '2.0.0', protocol_version: 1 });
  });

  it('服务版本取不到：— + 原话常驻 + 重试，不再挂「…」', async () => {
    vi.mocked(systemApi.ping).mockRejectedValueOnce(new Error('sidecar 无响应'));
    page();
    expect(await screen.findByText(/取不到：sidecar 无响应/)).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy();
    expect(screen.queryByText('…')).toBeNull();
  });

  it('重试取回了：故障行消失、版本回到 v 号', async () => {
    vi.mocked(systemApi.ping).mockRejectedValueOnce(new Error('sidecar 无响应'));
    page();
    await screen.findByText(/取不到：sidecar 无响应/);
    fireEvent.click(screen.getByRole('button', { name: /^重\s?试$/ }));
    await waitFor(() => {
      expect(screen.queryByText(/取不到：/)).toBeNull();
    });
    expect(screen.getAllByText('v2.0.0')).toHaveLength(2);
  });
});
