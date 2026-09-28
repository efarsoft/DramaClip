// @vitest-environment jsdom
/**
 * 方案卡勾选 → 出片提交的是这批的 id；换批之后旧勾选必须作废。
 * 规划一次、出片一次之间隔着一次「再生成」，方案 id 是按批次新建的。
 * 上一批的勾选如果留着，`export.submit` 就会收到本批根本不存在的 id。
 * 另钉（卷三图4 / 意见08 / 静默清单第2条）：覆盖度行常驻、成本预估一期口径。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { NarrationPlan } from '@dramaclip/protocol';
import { PlanPickList } from '../PlanPickList';

afterEach(() => {
  cleanup();
});

function plan(id: string, episodeIds: string[] = ['e1']): NarrationPlan {
  return {
    id,
    project_id: 'proj',
    narration_mode: 'cross_narration',
    episode_ids: episodeIds,
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
  submitting: false,
  rejected: [],
  error: '',
  run: vi.fn(),
};

const idleBatch = {
  planning: false,
  percent: 0,
  stageText: '',
  error: '',
  run: vi.fn(),
  cancel: vi.fn(),
};

function pickList(plans: NarrationPlan[], queue = idleQueue, episodeCount = 2, avgBytes: number | null = null) {
  return render(
    <PlanPickList batch={{ ...idleBatch, plans }} queue={queue} episodeCount={episodeCount} avgBytes={avgBytes} />,
  );
}

it('默认每模式预选 1 条推荐，直接出片不用盲选', () => {
  const run = vi.fn();
  pickList([plan('a'), plan('b')], { ...idleQueue, run });
  fireEvent.click(screen.getByRole('button', { name: /开始出片/ }));
  expect(run).toHaveBeenCalledWith(['a']);
  expect(screen.getByText('推荐')).toBeTruthy();
});

it('推荐可取消：同模式备选不自动顶上，清空后按钮禁用', () => {
  const run = vi.fn();
  pickList([plan('a'), plan('b')], { ...idleQueue, run });
  fireEvent.click(screen.getByText('角度 a')); // 取消默认预选
  expect(screen.getByText('已选 0 / 2 条方案')).not.toBeNull();
  expect(screen.getByRole('button', { name: /开始出片/ }).hasAttribute('disabled')).toBe(true);
  expect(run).not.toHaveBeenCalled();
});

it('换了批次，勾选按新批次的默认推荐重置', () => {
  const { rerender } = render(
    <PlanPickList batch={{ ...idleBatch, plans: [plan('a')] }} queue={idleQueue} episodeCount={2} avgBytes={null} />,
  );
  expect(screen.getByText('已选 1 / 1 条方案')).not.toBeNull();

  rerender(
    <PlanPickList batch={{ ...idleBatch, plans: [plan('c'), plan('d')] }} queue={idleQueue} episodeCount={2} avgBytes={null} />,
  );
  expect(screen.getByText('已选 1 / 2 条方案')).not.toBeNull();
  expect(screen.getByRole('button', { name: /开始出片/ }).hasAttribute('disabled')).toBe(false);
});

it('剧本清洗丢了几段就写在卡上：不说出口，方案看起来像天生只有这么长', () => {
  const dropped: NarrationPlan = {
    ...plan('a'),
    plan_data: { ...plan('a').plan_data, dropped_segments: 3 },
  };
  pickList([dropped, plan('b')]);
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
  pickList([blocked, plan('b')], { ...idleQueue, run });
  fireEvent.click(screen.getByRole('button', { name: /开始出片/ }));
  expect(run).toHaveBeenCalledWith(['b']);
  expect(screen.getByText('收尾没有指向看全集')).not.toBeNull();
});

it('覆盖度行常驻卡头：取材集去重 n / 全剧 m', () => {
  pickList([plan('a', ['e1', 'e2']), plan('b', ['e2'])], idleQueue, 3);
  expect(screen.getByText(/本次规划覆盖/)).toBeTruthy();
  expect(screen.getByText('2/3')).toBeTruthy();
});

it('集数拿不到时覆盖度行缺席，不拿 0/0 充数', () => {
  pickList([plan('a')], idleQueue, 0);
  expect(screen.queryByText(/本次规划覆盖/)).toBeNull();
});

it('成本预估一期口径：条数照实、磁盘带「估」字、耗时与 LLM 就是「—」', () => {
  pickList([plan('a'), plan('b')], idleQueue, 2, 1073741824);
  expect(screen.getByText('成本预估')).toBeTruthy();
  expect(screen.getByText('1 条')).toBeTruthy(); // 默认预选每模式 1 条
  expect(screen.getByText('约 1.0 GB（估）')).toBeTruthy();
  fireEvent.click(screen.getByText('角度 a'));
  expect(screen.getByText('0 条')).toBeTruthy(); // 手动清空：条数照实是 0
  // 清空后磁盘也失去口径：三个「—」芯片（磁盘/耗时/LLM）
  expect(screen.getAllByText('—')).toHaveLength(3);
});

it('没有已完成成片：磁盘项显示「—」而不是编一个系数', () => {
  pickList([plan('a')], idleQueue, 2, null);
  expect(screen.getByText('1 条')).toBeTruthy();
  expect(screen.queryByText(/GB（估）/)).toBeNull();
});
