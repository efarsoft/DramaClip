/** 三统计芯片（规格 §4.1）。溢出与不可用必须如实显示，不得给假精确值。 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { StatChips } from '../StatChips';
import type { WorkbenchStats } from '../stats';

afterEach(cleanup);

function stats(over: Partial<WorkbenchStats> = {}): WorkbenchStats {
  return {
    dramaCount: 12,
    runningCount: 3,
    runningValue: '3',
    runningEtaLabel: '预计还需 8 分',
    jobsAvailable: true,
    workCount: 45,
    workCountOverflow: false,
    workWeekDelta: 6,
    ...over,
  };
}

describe('StatChips', () => {
  it('恰好三个芯片', () => {
    render(<StatChips stats={stats()} />);
    expect(screen.getAllByTestId('stat-chip')).toHaveLength(3);
  });

  it('三块内容各自可读', () => {
    render(<StatChips stats={stats()} />);
    for (const text of ['12', '部剧', '3', '条在跑', '预计还需 8 分', '45', '条成品', '本周 +6']) {
      expect(screen.getByText(text), `缺 ${text}`).toBeTruthy();
    }
  });

  it('无在跑任务时不渲染 ETA 那一行', () => {
    render(<StatChips stats={stats({ runningCount: 0, runningEtaLabel: '' })} />);
    expect(screen.queryByText(/^预计/)).toBeNull();
  });

  it('溢出时总数带 +，周增显示为不可用', () => {
    render(<StatChips stats={stats({ workCount: 1000, workCountOverflow: true, workWeekDelta: null })} />);
    expect(screen.getByText('1000+')).toBeTruthy();
    expect(screen.getByText('本周 —')).toBeTruthy();
  });

  it('本周零增显示 +0，不隐藏（隐藏会让人以为没算）', () => {
    render(<StatChips stats={stats({ workWeekDelta: 0 })} />);
    expect(screen.getByText('本周 +0')).toBeTruthy();
  });

  it('任务状态取不到时在跑显示 —，不显示 0', () => {
    render(<StatChips stats={stats({ jobsAvailable: false, runningCount: 0, runningValue: '—', runningEtaLabel: '' })} />);
    expect(screen.getByText('—')).toBeTruthy();
    expect(screen.queryByText('0')).toBeNull();
  });
});
