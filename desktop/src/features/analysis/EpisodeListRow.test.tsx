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
