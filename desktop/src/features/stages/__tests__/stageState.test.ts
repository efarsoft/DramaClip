/** stageState 真值表：四阶段灯 + 卡点优先级的每条分支都有用例钉死（卷二 §4.1 / 卷三意见 02-03）。 */
import { describe, expect, it } from 'vitest';
import type { JobInfo } from '@dramaclip/protocol';
import {
  allStagesDone,
  continueRoute,
  degradedFacts,
  deriveBlockNote,
  deriveStages,
  jobFactsFor,
  NO_JOB_FACTS,
  type BlockContext,
  type StageFacts,
} from '../stageState';

const DAY = 86_400_000;
const NOW = 1_000 * DAY;

const CTX: BlockContext = { dramaId: 'p1', createdAtMs: NOW - 2 * DAY, serverTimeMs: NOW };

function facts(partial: Partial<StageFacts> = {}): StageFacts {
  return {
    episodeCount: 6,
    workCount: 0,
    activeTypes: new Set(),
    activeLabel: null,
    activeProgress: null,
    failed: null,
    analyzedCount: null,
    planCount: null,
    staleHint: null,
    analysisEverCompleted: false,
    jobsPresent: true,
    ...partial,
  };
}

function job(partial: Partial<JobInfo> = {}): JobInfo {
  return {
    id: 'j1',
    type: 'analysis',
    ref_id: 'p1',
    status: 'running',
    progress: 40,
    label: null,
    error: null,
    created_at: NOW - DAY,
    updated_at: NOW,
    ...partial,
  };
}

describe('deriveStages 四阶段灯', () => {
  it('① 进素材：有集数即完成，零集数未开始', () => {
    expect(deriveStages(facts({ episodeCount: 6 })).intake).toBe('done');
    expect(deriveStages(facts({ episodeCount: 0 })).intake).toBe('idle');
  });

  it('② 分析：聚合计数缺席时只亮灰，即便有成品也不倒推绿（宁灰勿假绿）', () => {
    expect(deriveStages(facts({ analyzedCount: null, workCount: 3 })).analysis).toBe('unknown');
    expect(deriveStages(facts({ analyzedCount: null, analysisEverCompleted: true })).analysis).toBe('unknown');
  });

  it('② 分析：有在跑任务时 active 优先于一切计数', () => {
    expect(deriveStages(facts({ activeTypes: new Set(['prescreen']), analyzedCount: 6 })).analysis).toBe('active');
  });

  it('② 分析：聚合计数在场时按 全集=done / 部分=active / 零=idle', () => {
    expect(deriveStages(facts({ analyzedCount: 6, episodeCount: 6 })).analysis).toBe('done');
    expect(deriveStages(facts({ analyzedCount: 2, episodeCount: 6 })).analysis).toBe('active');
    expect(deriveStages(facts({ analyzedCount: 0, episodeCount: 6 })).analysis).toBe('idle');
  });

  it('③ 规划：narration 在跑=active；staleHint=true 压过完成态', () => {
    expect(deriveStages(facts({ activeTypes: new Set(['narration']) })).planning).toBe('active');
    expect(deriveStages(facts({ staleHint: true, planCount: 4 })).planning).toBe('stale');
  });

  it('③ 规划：方案账缺席时成品是硬证据，无成品亮灰', () => {
    expect(deriveStages(facts({ planCount: null, workCount: 2 })).planning).toBe('done');
    expect(deriveStages(facts({ planCount: null, workCount: 0 })).planning).toBe('unknown');
  });

  it('③ 规划：方案账在场时按条数点亮', () => {
    expect(deriveStages(facts({ planCount: 4, workCount: 0 })).planning).toBe('done');
    expect(deriveStages(facts({ planCount: 0, workCount: 0 })).planning).toBe('idle');
  });

  it('④ 出片：成品数即真值，无成品未开始', () => {
    expect(deriveStages(facts({ workCount: 1 })).export).toBe('done');
    expect(deriveStages(facts({ workCount: 0 })).export).toBe('idle');
    expect(deriveStages(facts({ workCount: 0, activeTypes: new Set(['export']) })).export).toBe('active');
  });
});

describe('账本粒度降级（缺哪本账灰哪几盏灯，不连坐）', () => {
  it('成品账缺（workCount=null）：③④ 灰，① 照硬数据走', () => {
    const stages = deriveStages(facts({ workCount: null }));
    expect(stages.intake).toBe('done');
    expect(stages.planning).toBe('unknown');
    expect(stages.export).toBe('unknown');
    expect(deriveStages(facts({ workCount: null, activeTypes: new Set(['export']) })).export).toBe('active');
  });

  it('任务账缺（jobsPresent=false）：② 灰，「还没开跑」类卡点句沉默', () => {
    const f = facts({ jobsPresent: false });
    expect(deriveStages(f).analysis).toBe('unknown');
    expect(deriveBlockNote(f, deriveStages(f), CTX)).toBeNull();
  });

  it('成品账缺：停滞催办也不说——「还没有成品」断不了', () => {
    const stalled = { ...CTX, createdAtMs: NOW - 20 * DAY };
    const f = facts({ workCount: null });
    expect(deriveBlockNote(f, deriveStages(f), stalled)).toBeNull();
  });

  it('任务账缺但成品账在且停滞超 14 天：催办照说（只依赖成品与建库时间）', () => {
    const stalled = { ...CTX, createdAtMs: NOW - 20 * DAY };
    const f = facts({ jobsPresent: false });
    expect(deriveBlockNote(f, deriveStages(f), stalled)).toMatchObject({
      stage: 'export',
      text: '6 集已就位 20 天，还没有成品',
    });
  });
});

describe('deriveBlockNote 卡点优先级', () => {
  it('失败最重：阶段词 + error 原文全量进句，路由按阶段', () => {
    const note = deriveBlockNote(
      facts({ failed: { type: 'analysis', error: 'Whisper 缺模型：转写无法开始' }, episodeCount: 0 }),
      deriveStages(facts()),
      CTX,
    );
    expect(note).toMatchObject({
      stage: 'analysis',
      tone: 'error',
      text: '卡在分析：Whisper 缺模型：转写无法开始',
      actionLabel: '去处理',
      route: '/projects/p1/analysis',
    });
  });

  it('narration 失败卡③，路由进出片页；error 缺失说未知原因', () => {
    const note = deriveBlockNote(facts({ failed: { type: 'narration', error: '' } }), deriveStages(facts()), CTX);
    expect(note).toMatchObject({ stage: 'planning', tone: 'error', text: '卡在规划：未知原因', route: '/projects/p1/produce' });
  });

  it('过期方案压过一切非失败卡点', () => {
    const note = deriveBlockNote(
      facts({ staleHint: true, activeTypes: new Set(['narration']), activeLabel: '写方案中' }),
      deriveStages(facts({ staleHint: true })),
      CTX,
    );
    expect(note).toMatchObject({ stage: 'planning', tone: 'warning', actionLabel: '重新规划' });
  });

  it('没喂料：建了库零集数，给去喂料动作', () => {
    const f = facts({ episodeCount: 0 });
    const note = deriveBlockNote(f, deriveStages(f), CTX);
    expect(note).toMatchObject({ stage: 'intake', tone: 'action', text: '建了库还没喂料：目录里没有识别到剧集文件' });
  });

  it('正在跑：用 job.label 人读文本，不刷「分析中」空话', () => {
    const f = facts({ activeTypes: new Set(['analysis']), activeLabel: '第 3 集转写中' });
    const note = deriveBlockNote(f, deriveStages(f), CTX);
    expect(note).toMatchObject({ stage: 'analysis', tone: 'action', text: '第 3 集转写中', actionLabel: '去看' });
  });

  it('停滞催办：就位超 14 天无成品才催，天数用服务端时钟', () => {
    const stale = { ...CTX, createdAtMs: NOW - 20 * DAY };
    const note = deriveBlockNote(facts(), deriveStages(facts()), stale);
    expect(note).toMatchObject({ stage: 'export', tone: 'warning', text: '6 集已就位 20 天，还没有成品', actionLabel: '去出片' });
    expect(deriveBlockNote(facts(), deriveStages(facts()), CTX)).not.toMatchObject({ tone: 'warning' });
  });

  it('没开跑与跑过账缺是两句话，不混说', () => {
    const fresh = deriveBlockNote(facts(), deriveStages(facts()), CTX);
    expect(fresh).toMatchObject({ stage: 'analysis', tone: 'action', text: '素材已就位，分析还没开跑', actionLabel: '去分析' });
    const ever = deriveBlockNote(facts({ analysisEverCompleted: true }), deriveStages(facts({ analysisEverCompleted: true })), CTX);
    expect(ever).toMatchObject({ text: '分析有过完成记录，方案还没见着' });
  });

  it('有成品无卡点=null；全完成=null', () => {
    const shipped = facts({ workCount: 2, analyzedCount: 6, planCount: 4 });
    expect(deriveBlockNote(shipped, deriveStages(shipped), CTX)).toBeNull();
    expect(allStagesDone(deriveStages(shipped))).toBe(true);
  });
});

describe('continueRoute 继续按钮', () => {
  it('③④ 在跑去出片页；全完成去成品库；否则回分析页', () => {
    expect(continueRoute('p1', deriveStages(facts({ activeTypes: new Set(['narration']) })))).toEqual({
      route: '/projects/p1/produce',
      label: '继续出片',
    });
    expect(continueRoute('p1', deriveStages(facts({ workCount: 2, analyzedCount: 6, planCount: 4 })))).toEqual({
      route: '/works',
      label: '看成品',
    });
    expect(continueRoute('p1', deriveStages(facts({ workCount: 2 })))).toEqual({
      route: '/projects/p1/produce',
      label: '继续出片',
    });
    expect(continueRoute('p1', deriveStages(facts()))).toEqual({
      route: '/projects/p1/analysis',
      label: '继续分析',
    });
  });
});

describe('jobFactsFor 从任务账提取', () => {
  it('只认 ref_id=剧 且 project 系任务；export/semantic 挂不上剧', () => {
    const f = jobFactsFor('p1', [
      job({ id: 'other', ref_id: 'p2' }),
      job({ id: 'exp', type: 'export', ref_id: 'e1' }),
      job({ id: 'sem', type: 'semantic', ref_id: 'ep1' }),
    ]);
    expect(f.activeTypes.size).toBe(0);
    expect(f.failed).toBeNull();
    expect(f.analysisEverCompleted).toBe(false);
  });

  it('在跑类型入集合，label 取最近一条（jobs.list 倒序前提）', () => {
    const f = jobFactsFor('p1', [
      job({ id: 'a', type: 'prescreen', status: 'running', label: '预筛 2/6' }),
      job({ id: 'b', type: 'analysis', status: 'pending', label: null }),
    ]);
    expect(f.activeTypes).toEqual(new Set(['prescreen', 'analysis']));
    expect(f.activeLabel).toBe('预筛 2/6');
  });

  it('失败取最近一条，error 原文保留；完成过的分析记账', () => {
    const f = jobFactsFor('p1', [
      job({ id: 'new', status: 'failed', error: 'CUDA 显存不足', updated_at: NOW }),
      job({ id: 'old', status: 'failed', error: '旧错', updated_at: NOW - DAY }),
      job({ id: 'done', status: 'completed', updated_at: NOW - 2 * DAY }),
    ]);
    expect(f.failed).toEqual({ type: 'analysis', error: 'CUDA 显存不足' });
    expect(f.analysisEverCompleted).toBe(true);
  });

  it('degradedFacts 三个聚合字段恒 null：宁灰勿假绿的入口', () => {
    const f = degradedFacts(6, 2, jobFactsFor('p1', []));
    expect(f).toMatchObject({ episodeCount: 6, workCount: 2, analyzedCount: null, planCount: null, staleHint: null });
    expect(deriveStages(f).analysis).toBe('unknown');
    expect(degradedFacts(6, null, NO_JOB_FACTS).workCount).toBeNull();
  });

  it('activeProgress 取最近在跑任务的进度；NO_JOB_FACTS 全沉默', () => {
    const f = jobFactsFor('p1', [job({ progress: 40 }), job({ id: 'b', progress: 90, updated_at: NOW - DAY })]);
    expect(f.activeProgress).toBe(40);
    expect(f.jobsPresent).toBe(true);
    expect(NO_JOB_FACTS).toMatchObject({ activeProgress: null, jobsPresent: false, analysisEverCompleted: false });
    expect(NO_JOB_FACTS.activeTypes.size).toBe(0);
  });
});
