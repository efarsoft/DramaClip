// @vitest-environment jsdom
/** 工具箱页（Tabs 三工具 + 结果区改写面板）：提取/转写产出 → 改写加工 → 送配音闭环。 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { ToolsPage } from '../ToolsPage';

beforeAll(() => {
  // jsdom 无 ResizeObserver：antd 布局组件需要（真浏览器观察，替身空转即可）
  class NoResizeObserver {
    observe(): void {
      // 浮层尺寸由真浏览器观察
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

const api = vi.hoisted(() => ({
  extractStart: vi.fn(),
  getResult: vi.fn(),
  asrStart: vi.fn(),
  rewrite: vi.fn(),
  tts: vi.fn(),
  pickVideoFile: vi.fn(),
  pickAudioFile: vi.fn(),
  revealInFolder: vi.fn(),
  saveTextFile: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  toolsApi: {
    extractStart: api.extractStart,
    getResult: api.getResult,
    asrStart: api.asrStart,
    rewrite: api.rewrite,
    tts: api.tts,
  },
  pickVideoFile: api.pickVideoFile,
  pickAudioFile: api.pickAudioFile,
  revealInFolder: api.revealInFolder,
  saveTextFile: api.saveTextFile,
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
}));

const RESULT = {
  video_path: 'D:/in/ep1.mp4',
  txt_path: 'D:/data/tools/j1/copy.txt',
  srt_path: 'D:/data/tools/j1/copy.srt',
  text: '皇后变卖首饰，才凑出五千两',
  chars: 12,
  duration_s: 138.2,
  lines: 2,
};

function page(): void {
  render(
    <AntdApp>
      <ToolsPage />
    </AntdApp>,
  );
}

function switchTab(label: string | RegExp): void {
  fireEvent.click(screen.getByRole('tab', { name: label }));
}

async function pickVideoAndStartExtract(): Promise<void> {
  fireEvent.click(screen.getByRole('button', { name: /选择视频/ }));
  await waitFor(() => {
    expect(screen.getByDisplayValue('D:/in/ep1.mp4')).toBeTruthy();
  });
  fireEvent.click(screen.getByRole('button', { name: /开始提取/ }));
  await waitFor(() => {
    expect(api.extractStart).toHaveBeenCalledWith('D:/in/ep1.mp4');
  });
}

beforeEach(() => {
  vi.mocked(api.pickVideoFile).mockResolvedValue('D:/in/ep1.mp4');
  vi.mocked(api.pickAudioFile).mockResolvedValue('D:/in/voice.mp3');
  vi.mocked(api.revealInFolder).mockResolvedValue({ ok: true });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('工具箱页（Tabs）', () => {
  it('三个工具选项卡上屏，默认挂载文案提取，其余懒渲染', () => {
    page();
    expect(screen.getByRole('tab', { name: /视频文案提取/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /语音转文字/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /^文字转语音/ })).toBeTruthy();
    expect(screen.queryByRole('tab', { name: /文案改写/ })).toBeNull();
    expect(screen.getByPlaceholderText(/选择一个视频文件/)).toBeTruthy();
    expect(screen.queryByPlaceholderText(/选择一个音频文件/)).toBeNull();
  });

  it('提取作业轮询到 completed：全文与元信息上屏', { timeout: 20000 }, async () => {
    api.extractStart.mockResolvedValue({ job_id: 'j1' });
    api.getResult
      .mockResolvedValueOnce({ status: 'running', error: null, result: null })
      .mockResolvedValue({ status: 'completed', error: null, result: RESULT });
    page();
    await pickVideoAndStartExtract();
    expect(
      await screen.findByText('皇后变卖首饰，才凑出五千两', {}, { timeout: 10000 }),
    ).toBeTruthy();
    expect(await screen.findByText(/提取 12 字 · 2 行/)).toBeTruthy();
    expect(api.getResult).toHaveBeenCalledWith('j1');
  });

  it('保存 SRT：原生保存框以「视频名.srt」为默认名落盘', { timeout: 20000 }, async () => {
    api.extractStart.mockResolvedValue({ job_id: 'j1' });
    api.getResult.mockResolvedValue({ status: 'completed', error: null, result: RESULT });
    api.saveTextFile.mockResolvedValue('D:/out/ep1.srt');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ text: (): Promise<string> => Promise.resolve('1\n00:00:01,000 --> 00:00:03,000\n皇后\n') }),
    );
    page();
    await pickVideoAndStartExtract();
    fireEvent.click(await screen.findByRole('button', { name: /保存 SRT/ }, { timeout: 10000 }));
    await waitFor(() => {
      expect(api.saveTextFile).toHaveBeenCalledWith('ep1.srt', '1\n00:00:01,000 --> 00:00:03,000\n皇后\n');
    });
    vi.unstubAllGlobals();
  });

  it('作业查询连续失败：常驻失败原因上屏而非静默轮询', { timeout: 20000 }, async () => {
    api.extractStart.mockResolvedValue({ job_id: 'jx' });
    api.getResult.mockRejectedValue(new Error('rpc down'));
    page();
    await pickVideoAndStartExtract();
    expect(await screen.findByText(/失败：.*服务无响应/, {}, { timeout: 15000 })).toBeTruthy();
  });

  it('结果区改写：按文风卡改写产出上屏并带审查标注', async () => {
    api.extractStart.mockResolvedValue({ job_id: 'j1' });
    api.getResult.mockResolvedValue({ status: 'completed', error: null, result: RESULT });
    api.rewrite.mockResolvedValue({
      text: '按文风卡重写的稿子',
      style: 'card',
      notes: ['含「关注/点赞/收藏/二维码」，导看片转化走挂链接，建议删除'],
    });
    page();
    await pickVideoAndStartExtract();
    await screen.findByDisplayValue('皇后变卖首饰，才凑出五千两', {}, { timeout: 10000 });
    // 选风格 + 点改写
    fireEvent.mouseDown(screen.getByRole('combobox'));
    fireEvent.click(await screen.findByText(/按文风卡重写/));
    // antd 对两字按钮自动插空格：「改写」渲染成「改 写」
    fireEvent.click(screen.getByRole('button', { name: /改\s*写/ }));
    expect(
      await screen.findByDisplayValue('按文风卡重写的稿子', {}, { timeout: 10000 }),
    ).toBeTruthy();
    expect(await screen.findByText(/审查标注/)).toBeTruthy();
    expect(api.rewrite).toHaveBeenCalledWith('皇后变卖首饰，才凑出五千两', 'card');
  });

  it('送文字转语音：自动切到 TTS 选项卡并填入草稿', { timeout: 20000 }, async () => {
    api.extractStart.mockResolvedValue({ job_id: 'j1' });
    api.getResult.mockResolvedValue({ status: 'completed', error: null, result: RESULT });
    page();
    await pickVideoAndStartExtract();
    const send = await screen.findByRole('button', { name: /送文字转语音/ }, { timeout: 10000 });
    fireEvent.click(send);
    expect(screen.getByRole('tab', { name: /文字转语音/, selected: true })).toBeTruthy();
    await waitFor(() => {
      // 提取结果区与 TTS 草稿框各有一份同文案：≥2 份即草稿已收到
      expect(screen.getAllByDisplayValue('皇后变卖首饰，才凑出五千两').length).toBeGreaterThanOrEqual(2);
    });
  });

  it('语音转文字 tab：纯 ASR 转写结果上屏', { timeout: 20000 }, async () => {
    api.asrStart.mockResolvedValue({ job_id: 'ja' });
    api.getResult.mockResolvedValue({
      status: 'completed',
      error: null,
      result: { ...RESULT, text: '录音里的一句话', chars: 8 },
    });
    page();
    switchTab(/语音转文字/);
    fireEvent.click(screen.getByRole('button', { name: /选择音频/ }));
    await waitFor(() => {
      expect(screen.getByDisplayValue('D:/in/voice.mp3')).toBeTruthy();
    });
    fireEvent.click(screen.getByRole('button', { name: /开始转写/ }));
    expect(await screen.findByText('录音里的一句话', {}, { timeout: 10000 })).toBeTruthy();
    expect(api.asrStart).toHaveBeenCalledWith('D:/in/voice.mp3');
  });

  it('合成失败弹错误，不上音频动作', async () => {
    api.tts.mockRejectedValue(new Error('LLM 未配置'));
    page();
    switchTab(/文字转语音/);
    fireEvent.change(screen.getByPlaceholderText(/粘贴文案全文/), {
      target: { value: '测试文案' },
    });
    fireEvent.click(screen.getByRole('button', { name: /合成语音/ }));
    await waitFor(() => {
      expect(api.tts).toHaveBeenCalledWith('测试文案');
    });
    expect(screen.queryByRole('button', { name: /播放/ })).toBeNull();
  });
});
