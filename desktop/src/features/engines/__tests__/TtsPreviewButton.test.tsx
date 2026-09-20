// @vitest-environment jsdom
/**
 * 试听按钮的行为判据：听到的是选的那一件，听不到时要说清为什么听不到。
 *
 * 播放走 <audio>，故这里替掉全局 Audio 构造器记录 src 与 play()——真机能否出声由
 * dramaclip:// 的 content-type 与 ffprobe 实测时长保证（服务端用例已钉住 >0）。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TtsPreviewButton } from '../TtsPreviewButton';

interface PreviewResult {
  path: string;
  duration_s?: number;
  engine?: string;
  voice?: string;
  text?: string;
}

const preview = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  ttsApi: {
    preview: (engine: string, voice: string): unknown => preview(engine, voice),
  },
  mediaUrl: (path: string): string => `dramaclip://local/${encodeURIComponent(path)}`,
}));

interface Played {
  src: string;
  plays: number;
  pauses: number;
}

class FakeAudio {
  static played: Played[] = [];
  readonly record: Played = { src: '', plays: 0, pauses: 0 };
  constructor(src: string) {
    this.record.src = src;
    FakeAudio.played.push(this.record);
  }
  play(): void {
    this.record.plays += 1;
  }
  pause(): void {
    this.record.pauses += 1;
  }
}

function last(): Played {
  const entry = FakeAudio.played.at(-1);
  if (entry === undefined) throw new Error('没有创建音频元素');
  return entry;
}

function first(): Played {
  const entry = FakeAudio.played.at(0);
  if (entry === undefined) throw new Error('没有创建音频元素');
  return entry;
}

function button(): HTMLElement {
  return screen.getByRole('button', { name: /试听/ });
}

/** 等按钮空下来再点：合成期间它叫「合成中」且禁用，抢点会被吞掉、断言就成了碰运气。 */
async function clickPreview(): Promise<void> {
  const target = await screen.findByRole('button', { name: /试听/ });
  await waitFor(() => {
    expect(target.hasAttribute('disabled')).toBe(false);
  });
  fireEvent.click(target);
}

function settles(): void {
  cleanup();
  preview.mockReset();
  FakeAudio.played = [];
  vi.unstubAllGlobals();
}

afterEach(settles);

describe('TtsPreviewButton · 出声', () => {
  it('点击后按选定的引擎与音色合成，并把产物交给音频元素播放', async () => {
    vi.stubGlobal('Audio', FakeAudio);
    preview.mockResolvedValue({
      path: 'D:\\data\\cache\\analysis\\tts-preview\\kokoro-abc123.mp3',
      duration_s: 2.4,
      engine: 'kokoro',
      voice: 'zf_009',
      text: '她推开门就愣住了',
    } satisfies PreviewResult);
    render(<TtsPreviewButton engine="kokoro" voice="zf_009" />);

    await clickPreview();

    await waitFor(() => {
      expect(preview).toHaveBeenCalledWith('kokoro', 'zf_009');
    });
    await waitFor(() => {
      expect(last().plays).toBe(1);
    });
    expect(last().src).toContain('tts-preview');
  });

  it('第二次试听会先停掉上一次的声，两段不叠成杂音', async () => {
    vi.stubGlobal('Audio', FakeAudio);
    preview.mockResolvedValue({ path: 'D:\\a.mp3' } satisfies PreviewResult);
    render(<TtsPreviewButton engine="kokoro" voice="zf_001" />);

    await clickPreview();
    await waitFor(() => {
      expect(last().plays).toBe(1);
    });
    await clickPreview();
    await waitFor(() => {
      expect(FakeAudio.played.length).toBe(2);
    });

    expect(first().pauses).toBe(1);
    expect(last().pauses).toBe(0);
  });

  it('合成期间按钮禁用，完成后恢复可点', async () => {
    vi.stubGlobal('Audio', FakeAudio);
    let resolve: (value: PreviewResult) => void = () => undefined;
    preview.mockReturnValue(new Promise((done) => {
      resolve = done;
    }));
    render(<TtsPreviewButton engine="edge" voice="zh-CN-YunxiNeural" />);
    const target = button();

    fireEvent.click(target);
    await waitFor(() => {
      expect(target.hasAttribute('disabled')).toBe(true);
    });

    resolve({ path: 'D:\\a.mp3' });
    await waitFor(() => {
      expect(target.hasAttribute('disabled')).toBe(false);
    });
  });
});

describe('TtsPreviewButton · 不出声的理由', () => {
  it('服务端拒绝时把原因原样摆在按钮旁，不改口说已播放', async () => {
    preview.mockRejectedValue(new Error('Kokoro 没有音色「zf_999」——引擎会静默改用 zf_001'));
    render(<TtsPreviewButton engine="kokoro" voice="zf_999" />);

    fireEvent.click(button());

    expect(await screen.findByText(/zf_999/)).toBeTruthy();
    expect(FakeAudio.played).toEqual([]);
  });

  it('给了不可试听的原因时按钮禁用，点击不发请求', () => {
    render(
      <TtsPreviewButton
        engine="kokoro"
        voice="zf_001"
        blocked="模型未下载，先下载后再试听"
      />,
    );

    expect(button().hasAttribute('disabled')).toBe(true);
    fireEvent.click(button());
    expect(preview).not.toHaveBeenCalled();
    expect(screen.getByText('模型未下载，先下载后再试听')).toBeTruthy();
  });
});
