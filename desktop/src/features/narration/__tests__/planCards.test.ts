/**
 * 方案卡的四要素判据（规格 §4.3：角度名 · 取材集区间 · 钩子首句 · 自选理由 + 重叠率）。
 *
 * 卡片是只读的，但它把「K 条到底是不是 K 个不同卖点」这句话翻译成了界面上的字。
 * 这里钉的是翻译过程中最容易静默变形的三处：空值、零值、以及缺失字段。
 */
import { describe, expect, it } from 'vitest';
import type { NarrationPlan } from '@dramaclip/protocol';
import { HOOK_MAX, planCardView } from '../planCards';

function plan(over: Partial<NarrationPlan>): NarrationPlan {
  return {
    id: 'p1',
    project_id: 'proj',
    narration_mode: 'cross_narration',
    episode_ids: [],
    plan_data: { mode: 'cross_narration', timeline: [], narration_texts: [] },
    status: 'planned',
    created_at: 0,
    ...over,
  };
}

function withTexts(...texts: string[]): NarrationPlan {
  return plan({
    plan_data: {
      mode: 'cross_narration',
      timeline: [],
      narration_texts: texts.map((text, i) => ({ id: `n${String(i)}`, text })),
    },
  });
}

describe('钩子首句', () => {
  it('取第一条解说文案，到句末标点为止', () => {
    const card = planCardView(withTexts('总裁不知道，她怀了他的孩子。第二句没人想看'));
    expect(card.hook).toBe('总裁不知道，她怀了他的孩子。');
  });

  it('没有句末标点时截断，不让整段独白挤爆卡片', () => {
    const card = planCardView(withTexts(`无标点${'长'.repeat(60)}`));
    expect(card.hook).toBe(`无标点${'长'.repeat(37)}…`);
  });

  it('句末标点在 40 字之后同样截断——长句不等于有边界', () => {
    const card = planCardView(withTexts(`${'句'.repeat(50)}。后面不看了`));
    expect(card.hook).toBe(`${'句'.repeat(HOOK_MAX)}…`);
  });

  it('原声模式没有解说文案 → 空串，界面据此不渲染这一行', () => {
    expect(planCardView(plan({})).hook).toBe('');
    expect(planCardView(withTexts('   ')).hook).toBe('');
  });
});

describe('取材集区间', () => {
  it('报集数而不是 id 列表', () => {
    expect(planCardView(plan({ episode_ids: ['e1', 'e2', 'e3'] })).episodes).toBe('取材 3 集');
    expect(planCardView(plan({ episode_ids: ['e1'] })).episodes).toBe('取材 1 集');
  });
});

describe('重叠率', () => {
  it('null = 组内首条，没有兄弟可比，说清楚而不是显示空白', () => {
    expect(planCardView(plan({ overlap_max: null })).overlap).toBe('组内首条');
  });

  it('0 是「一点没重」，不能被当成缺失', () => {
    expect(planCardView(plan({ overlap_max: 0 })).overlap).toBe('取材重叠 0%');
  });

  it('比率按百分比读，60% 是服务端拒绝的上界', () => {
    expect(planCardView(plan({ overlap_max: 0.6 })).overlap).toBe('取材重叠 60%');
    expect(planCardView(plan({ overlap_max: 0.234 })).overlap).toBe('取材重叠 23%');
  });

  it('字段整个缺失（未带角度的旧模式方案）→ 与首条同一口径，不显示 NaN', () => {
    expect(planCardView(plan({})).overlap).toBe('组内首条');
  });
});

describe('角度名与理由', () => {
  it('透传模型给的角度名和自选理由', () => {
    const card = planCardView(
      plan({ angle: '误会式强拆', angle_reason: '全剧冲突最密的一段' }),
    );
    expect(card.angle).toBe('误会式强拆');
    expect(card.reason).toBe('全剧冲突最密的一段');
  });

  it('缺失时落到空串，不出现 undefined 字样', () => {
    const card = planCardView(plan({}));
    expect(card.angle).toBe('');
    expect(card.reason).toBe('');
  });
});

describe('剧本清洗丢弃段数', () => {
  function withDropped(count: number | undefined): NarrationPlan {
    return plan({
      plan_data: { mode: 'dialogue_narration', timeline: [], narration_texts: [], dropped_segments: count },
    });
  }

  it('丢掉几段是句要说的话——实测真机吃掉 22-23% 而界面上毫无痕迹', () => {
    expect(planCardView(withDropped(3)).dropped).toBe('剧本丢弃 3 段');
  });

  it('0 段不占卡片位置，缺失字段（非剧本模式）同样不占', () => {
    expect(planCardView(withDropped(0)).dropped).toBe('');
    expect(planCardView(withDropped(undefined)).dropped).toBe('');
    expect(planCardView(plan({})).dropped).toBe('');
  });
});

describe('转化门禁', () => {
  it('ready 可出片', () => {
    const card = planCardView(plan({ status: 'ready' }));
    expect(card.pickable).toBe(true);
    expect(card.gate).toBe('');
  });

  it('draft 不能勾选，原因优先用 block_reason', () => {
    const card = planCardView(plan({ status: 'draft', block_reason: '收尾没有指向看全集' }));
    expect(card.pickable).toBe(false);
    expect(card.gate).toBe('收尾没有指向看全集');
  });
});
