// @vitest-environment jsdom
/** H2 §2.5/§2.6：禁用要有可见前置条件；死组件不留「以后可能用」。
 *
 * 死 Modal 的判据只能落在源码上：`open={false}` 的 antd Modal 一个节点都不渲染，
 * 界面观测不到它存在——而它每次渲染方案卡都在挂载、解析 8 段文案。
 */
import { readFileSync } from 'node:fs';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { NarrationPlan } from '@dramaclip/protocol';
import { ModePicker } from '../ModePicker';
import { PlanPickList } from '../PlanPickList';
import type { PlanBatch } from '../usePlanBatch';
import type { ExportQueue } from '../useExportQueue';

/** 签名要 Promise<void>，但用例不真的 await 空实现——写成 async 会被 require-await 判红。 */
const resolved = (): Promise<void> => Promise.resolve();

const idleBatch: PlanBatch = {
  planning: false,
  percent: 0,
  stageText: '',
  plans: [],
  error: '',
  failDetail: '',
  batchId: null,
  spec: null,
  run: vi.fn(resolved),
  rerollOne: vi.fn(resolved),
  cancel: vi.fn(resolved),
};

const idleQueue: ExportQueue = {
  submitting: false,
  rejected: [],
  error: '',
  run: vi.fn(resolved),
};

describe('PlanCard 死 Modal 实例', () => {
  it('只留 PlanCopyButton 那一处 Modal：`copyOpen` 与它的常驻实例一并删除', () => {
    const source = readFileSync('src/features/narration/PlanCard.tsx', 'utf-8');
    expect(source).not.toMatch(/copyOpen/);
    const instances = source.match(/<PlanCopyModal\b/g) ?? [];
    expect(instances).toHaveLength(1);
  });
});

describe('禁用按钮的可见前置条件', () => {
  afterEach(cleanup);

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

  it('ModePicker：一个模式都没勾 → 生成方案禁用并说明缺什么', () => {
    render(
      <ModePicker
        batch={idleBatch}
        modes={[]}
        k={3}
        onGenerate={() => undefined}
        onToggleMode={() => undefined}
        onSelectAll={() => undefined}
        onKChange={() => undefined}
      />,
    );
    expect(screen.getByRole('button', { name: /生成方案/ }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('先勾选至少一个模式')).toBeTruthy();
  });

  it('ModePicker：勾了模式 → 前置条件提示退场，按钮可用', () => {
    render(
      <ModePicker
        batch={idleBatch}
        modes={['full_narration']}
        k={3}
        onGenerate={() => undefined}
        onToggleMode={() => undefined}
        onSelectAll={() => undefined}
        onKChange={() => undefined}
      />,
    );
    expect(screen.queryByText('先勾选至少一个模式')).toBeNull();
    expect(screen.getByRole('button', { name: /生成方案/ }).hasAttribute('disabled')).toBe(false);
  });

  it('PlanPickList：把默认推荐全部取消 → 开始出片禁用并说明缺什么', async () => {
    render(
      <PlanPickList
        batch={{ ...idleBatch, plans: [plan('p1'), plan('p2')] }}
        queue={idleQueue}
        episodeCount={2}
        avgBytes={null}
      />,
    );
    // 默认每模式勾 2 条（不用盲选），所以要把这两条点掉才落到「已选 0」
    fireEvent.click(await screen.findByText('第 p1 条的钩子。'));
    fireEvent.click(await screen.findByText('第 p2 条的钩子。'));
    expect(await screen.findByText('已选 0 / 2 条方案')).toBeTruthy();
    expect(screen.getByRole('button', { name: /开始出片/ }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('先勾选至少一条方案')).toBeTruthy();
  });
});
