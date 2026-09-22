// @vitest-environment jsdom
/**
 * 方案卡勾选 → 出片提交的是这批的 id；换批之后旧勾选必须作废。
 *
 * 规划一次、出片一次之间隔着一次「再生成」，方案 id 是按批次新建的。
 * 上一批的勾选如果留着，`export.submit` 就会收到本批根本不存在的 id。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { NarrationPlan } from '@dramaclip/protocol';
import { PlanPickList } from '../PlanPickList';

afterEach(() => {
  cleanup();
});

function plan(id: string): NarrationPlan {
  return {
    id,
    project_id: 'proj',
    narration_mode: 'cross_narration',
    episode_ids: ['e1'],
    plan_data: {
      mode: 'cross_narration',
      timeline: [],
      narration_texts: [{ id: 'n0', text: `第 ${id} 条的钩子。` }],
    },
    status: 'ready',
    created_at: 0,
    angle: `角度 ${id}`,
  };
}

const idleQueue = {
  running: false,
  percent: 0,
  stageText: '',
  rejected: [],
  error: '',
  run: vi.fn(),
  cancel: vi.fn(),
};

const idleBatch = {
  planning: false,
  percent: 0,
  stageText: '',
  error: '',
  run: vi.fn(),
  cancel: vi.fn(),
};

it('勾选后出片，提交的是勾了的方案 id', () => {
  const run = vi.fn();
  render(
    <PlanPickList
      batch={{ ...idleBatch, plans: [plan('a'), plan('b')] }}
      queue={{ ...idleQueue, run }}
    />,
  );
  fireEvent.click(screen.getByText('角度 a'));
  fireEvent.click(screen.getByRole('button', { name: /出片所选/ }));
  expect(run).toHaveBeenCalledWith(['a']);
});

it('换了批次，上一批的勾选自动作废', () => {
  const { rerender } = render(
    <PlanPickList
      batch={{ ...idleBatch, plans: [plan('a')] }}
      queue={idleQueue}
    />,
  );
  fireEvent.click(screen.getByText('角度 a'));
  expect(screen.getByText('已选 1 / 1 条方案')).not.toBeNull();

  rerender(
    <PlanPickList
      batch={{ ...idleBatch, plans: [plan('c'), plan('d')] }}
      queue={idleQueue}
    />,
  );
  expect(screen.getByText('已选 0 / 2 条方案')).not.toBeNull();
  expect(screen.getByRole('button', { name: /出片所选/ }).hasAttribute('disabled')).toBe(true);
});

it('剧本清洗丢了几段就写在卡上：不说出口，方案看起来像天生只有这么长', () => {
  const dropped: NarrationPlan = {
    ...plan('a'),
    plan_data: { ...plan('a').plan_data, dropped_segments: 3 },
  };
  render(
    <PlanPickList
      batch={{ ...idleBatch, plans: [dropped, plan('b')] }}
      queue={idleQueue}
    />,
  );
  expect(screen.getByText('剧本丢弃 3 段')).not.toBeNull();
  expect(screen.getAllByText(/剧本丢弃/)).toHaveLength(1);
});

it('过不了转化门禁的方案不能勾选出片', () => {
  const run = vi.fn();
  const blocked: NarrationPlan = {
    ...plan('a'),
    status: 'draft',
    block_reason: '收尾没有指向看全集',
  };
  render(
    <PlanPickList
      batch={{ ...idleBatch, plans: [blocked, plan('b')] }}
      queue={{ ...idleQueue, run }}
    />,
  );
  fireEvent.click(screen.getByText('角度 a'));
  fireEvent.click(screen.getByText('角度 b'));
  fireEvent.click(screen.getByRole('button', { name: /出片所选/ }));
  expect(run).toHaveBeenCalledWith(['b']);
  expect(screen.getByText('收尾没有指向看全集')).not.toBeNull();
});
