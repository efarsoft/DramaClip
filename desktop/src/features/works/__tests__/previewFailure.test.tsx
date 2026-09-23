// @vitest-environment jsdom
/** 播放弹层解码失败态（DSS §4「播放弹层」/ 09-10 §8⑦）：不留黑盒，现象+路径原文+两种可能。 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { WorkItem } from '@dramaclip/protocol';
import { PreviewModal } from '../PreviewModal';

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

afterEach(cleanup);

function work(): WorkItem {
  return {
    id: 'w1',
    project_id: 'p1',
    project_name: '替嫁新娘',
    narration_mode: 'full_narration',
    output_path: 'D:/data/outputs/p1/missing.mp4',
    duration_s: 134,
    size_bytes: 268435456,
    completed_at: 1758600000000,
    narration_plan_id: 'plan1',
    angle: '角度一 · 替身真相',
    episode_ids: ['e1'],
    selfcheck: null,
    selfcheck_state: null,
  };
}

describe('PreviewModal', () => {
  it('正常挂载播放面：原生 video + autoPlay + controls', () => {
    // Modal 走 portal 挂在 body 下，查询打 baseElement 而不是 render 容器
    const { baseElement } = render(<PreviewModal work={work()} onClose={vi.fn()} />);
    const video = baseElement.querySelector('video');
    expect(video).not.toBeNull();
    expect(video?.hasAttribute('controls')).toBe(true);
  });

  it('解码失败：黑盒换成诚实文案——现象 + output_path 原文 + 两种可能', () => {
    const { baseElement } = render(<PreviewModal work={work()} onClose={vi.fn()} />);
    const video = baseElement.querySelector('video');
    if (video === null) throw new Error('播放面没挂上');
    fireEvent.error(video);
    expect(baseElement.querySelector('video')).toBeNull();
    expect(screen.getByText(/播放失败：内置播放器解不出这个文件/)).toBeTruthy();
    expect(screen.getByText('D:/data/outputs/p1/missing.mp4')).toBeTruthy();
    expect(screen.getByText(/文件已被移动或删除/)).toBeTruthy();
  });

  it('work 为 null：弹层不开', () => {
    const { baseElement } = render(<PreviewModal work={null} onClose={vi.fn()} />);
    expect(baseElement.querySelector('video')).toBeNull();
  });
});
