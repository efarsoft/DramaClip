/** C2 回归：素材行必须三态可辨——失败集绝不能再渲染成「● 待分析」。 */
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Episode } from '@dramaclip/protocol';
import { EpisodeListRow } from './EpisodeListRow';

// vitest 未开 globals，RTL 的自动 cleanup 不会注册；查询默认打在 document.body 上必须逐条清台。
afterEach(cleanup);

function episode(status: Episode['status']): Episode {
  return {
    id: 'e1',
    episode_number: 3,
    name: 'ep03.mp4',
    source_path: 'D:/x/ep03.mp4',
    duration: 120,
    status,
  };
}

function renderRow(target: Episode): ReturnType<typeof render> {
  return render(
    <EpisodeListRow
      episode={target}
      highlightCount={0}
      active={false}
      checked={false}
      dropTarget={false}
      onActivate={vi.fn()}
      onToggle={vi.fn()}
      onDragStart={vi.fn()}
      onDragOver={vi.fn()}
      onDrop={vi.fn()}
      onMove={vi.fn()}
    />,
  );
}

describe('EpisodeListRow 状态可辨性', () => {
  it('failed 不得显示为「待分析」', () => {
    const { getByText, queryByText } = renderRow(episode('failed'));
    expect(getByText(/分析失败/)).toBeTruthy();
    expect(queryByText(/待分析/)).toBeNull();
  });

  it('done 显示已转写', () => {
    const { getByText } = renderRow(episode('done'));
    expect(getByText(/已转写/)).toBeTruthy();
  });

  it('pending 显示待分析', () => {
    const { getByText } = renderRow(episode('pending'));
    expect(getByText(/待分析/)).toBeTruthy();
  });
});

describe('缺音轨标记（取不到 ≠ 没有）', () => {
  it('探测过且没有音频轨：行内挂「无音轨」', () => {
    const { getByText } = renderRow({ ...episode('pending'), has_audio: false });
    expect(getByText('无音轨')).toBeTruthy();
  });

  it('探测过且有音轨：不挂', () => {
    const { queryByText } = renderRow({ ...episode('pending'), has_audio: true });
    expect(queryByText('无音轨')).toBeNull();
  });

  it('未重扫的旧集（null/缺省）：不挂——未知不告警', () => {
    const { queryByText } = renderRow({ ...episode('pending'), has_audio: null });
    expect(queryByText('无音轨')).toBeNull();
    const legacy = renderRow(episode('pending'));
    expect(legacy.queryByText('无音轨')).toBeNull();
  });
});

describe('封面 NULL 防线（库内 NULL 原样过线）', () => {
  it('cover_path 为 null：走占位，不渲染 img（绝不请求 mediaUrl(null)）', () => {
    const { container } = renderRow({ ...episode('pending'), cover_path: null });
    expect(container.querySelector('img')).toBeNull();
  });

  it('cover_path 有值：正常渲染 img', () => {
    const { container } = renderRow({ ...episode('pending'), cover_path: 'D:/covers/e1.jpg' });
    expect(container.querySelector('img')).not.toBeNull();
  });
});
