// @vitest-environment jsdom
/**
 * 成片详情页（09-10 §4.5）：追溯链（角度金标签 + 取材集区间 + 去方案区）、
 * 自检分区（未检可补测）、完整路径上屏；方案已删如实说断链；
 * 成片旁挂时间轴（output.srt）逐句可点定位——没有≠失败，读不到≠没有。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { useUiStore } from '../../../stores/ui';
import { WorksDetailPage } from '../WorksDetailPage';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  selfcheck: vi.fn(),
  projectGet: vi.fn(),
  rpc: vi.fn(),
  generate: vi.fn(),
  update: vi.fn(),
  save: vi.fn(),
}));

vi.mock('../../../services/client', () => ({
  exportApi: { get: api.get, selfcheck: api.selfcheck },
  projectApi: { get: api.projectGet },
  rpc: api.rpc,
  titlesApi: { generate: api.generate, update: api.update },
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
  revealInFolder: vi.fn().mockResolvedValue({ ok: true }),
  pickFolder: vi.fn().mockResolvedValue(null),
  copyFiles: vi.fn(),
  saveTextFile: api.save,
}));

const JOB = {
  id: 'w1',
  project_id: 'p1',
  status: 'completed',
  progress: 100,
  created_at: 0,
  output_path: 'D:/data/outputs/p1/film_a1b2c3.mp4',
  narration_plan_id: 'plan1',
  narration_mode: 'full_narration',
  duration_s: 134,
  size_bytes: 268435456,
  completed_at: 1758600000000,
  selfcheck: null,
  selfcheck_state: null,
};

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

function page(): void {
  render(
    <MemoryRouter initialEntries={['/works/w1']}>
      <AntdApp>
        <Routes>
          <Route path="/works/:exportId" element={<WorksDetailPage />} />
        </Routes>
      </AntdApp>
    </MemoryRouter>,
  );
}

/** 旁挂时间轴的真实形状（后端 subtitle/srt.py 的 format_srt）：序号 + 成片内起止时间码 + 一行字幕。 */
const FILM_SRT =
  '1\n00:00:02,000 --> 00:00:04,000\n她替嫁三年\n\n2\n00:00:12,000 --> 00:00:13,500\n一纸休书当场念出\n';

/** media 协议的三种读盘结果都能观测（preview-protocol.ts：404=不在、403/500=读不了），所以「没有」与「失败」必须分开。 */
function stubSrtFetch(read: { ok: boolean; status: number; body?: string }): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: read.ok,
      status: read.status,
      text: (): Promise<string> => Promise.resolve(read.body ?? ''),
    }),
  );
}

beforeEach(() => {
  useUiStore.getState().setServiceState('ready');
  api.get.mockResolvedValue(JOB);
  api.projectGet.mockResolvedValue({
    project: { id: 'p1', name: '替嫁新娘' },
    episodes: [
      { id: 'e1', episode_number: 4 },
      { id: 'e2', episode_number: 11 },
    ],
  });
  api.rpc.mockResolvedValue({
    plan: {
      titles: [],
      angle: '替身真相',
      episode_ids: ['e1', 'e2'],
      plan_data: { narration_texts: [] },
    },
  });
  api.selfcheck.mockResolvedValue({ ok: true, job_id: 'j1', queued: 1 });
  // 旁挂时间轴默认「文件不在」：详情页其余用例不该被一次真实的读盘失败刷屏
  stubSrtFetch({ ok: false, status: 404 });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('追溯链', () => {
  it('角度金标签 + 取材集区间 + 完整路径', async () => {
    page();
    expect(await screen.findByText('替身真相')).toBeTruthy();
    expect(await screen.findByText('取材 EP04–EP11')).toBeTruthy();
    expect(screen.getByText('D:/data/outputs/p1/film_a1b2c3.mp4')).toBeTruthy();
    expect(screen.getByRole('button', { name: /去方案区/ }).hasAttribute('disabled')).toBe(false);
    expect(screen.queryByText(/本页只读/)).toBeNull();
  });

  it('方案已删：如实说断链，去方案区禁用且禁用理由可见（规格 §2.5）', async () => {
    api.get.mockResolvedValue({ ...JOB, narration_plan_id: undefined });
    page();
    expect(await screen.findByText('方案已删除，追溯链断')).toBeTruthy();
    expect(screen.getByRole('button', { name: /去方案区/ }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('方案已删除：本页只读，回跳方案区不可用')).toBeTruthy();
  });
});

describe('候选标题选用', () => {
  /** 星标互斥的三条候选——服务端 `narration.update_titles` 收的是整表。 */
  const threeTitles = [
    { text: '替嫁三年换来一纸休书', selected: false },
    { text: '皇后变卖首饰', selected: false },
    { text: '她替哥哥入宫', selected: false },
  ];

  function withTitles(titles: unknown[]): void {
    api.rpc.mockResolvedValue({
      plan: {
        titles,
        angle: '替身真相',
        episode_ids: [],
        plan_data: { narration_texts: [] },
      },
    });
  }

  it('点星标：整表提交 narration.update_titles（星标不再是假动作）', async () => {
    withTitles(threeTitles);
    api.update.mockResolvedValue({ titles: [threeTitles[0], { ...threeTitles[1], selected: true }, threeTitles[2]] });
    page();
    fireEvent.click(await screen.findByText('皇后变卖首饰'));
    await vi.waitFor(() => {
      expect(api.update).toHaveBeenCalledWith('plan1', [
        threeTitles[0],
        { text: '皇后变卖首饰', selected: true },
        threeTitles[2],
      ]);
    });
    // 选用回声取服务端返回值，且互斥：只有被点的那条亮星
    expect(await screen.findByText('皇后变卖首饰')).toBeTruthy();
    expect(document.querySelectorAll('.anticon-star')).toHaveLength(1);
  });

  it('落库失败：原因常驻可见，星标不亮（服务端才是选用态的真相源）', async () => {
    withTitles(threeTitles);
    api.update.mockRejectedValue(new Error('服务未就绪'));
    page();
    fireEvent.click(await screen.findByText('皇后变卖首饰'));
    expect(await screen.findByText('标题选用未保存：服务未就绪')).toBeTruthy();
    expect(document.querySelectorAll('.anticon-star')).toHaveLength(0);
  });

  it('刷新后星标仍在：选用态读回自 plan.titles，不靠本地 state', async () => {
    withTitles([threeTitles[0], { ...threeTitles[1], selected: true }, threeTitles[2]]);
    page();
    expect(await screen.findByText('皇后变卖首饰')).toBeTruthy();
    expect(document.querySelectorAll('.anticon-star')).toHaveLength(1);
  });

  it('重新生成失败：常驻原因（toast 会自己消失，账不能跟着消失）', async () => {
    withTitles(threeTitles);
    api.generate.mockRejectedValue(new Error('文案模型超时'));
    page();
    // 有候选时按钮出「重新生成」，无候选才出「生成候选标题」
    fireEvent.click(await screen.findByRole('button', { name: /重新生成/ }));
    expect(await screen.findByText('生成候选标题失败：文案模型超时')).toBeTruthy();
  });

  it('方案已删：空态不再指向一个不在场的「生成候选标题」按钮（规格 §2.4）', async () => {
    api.get.mockResolvedValue({ ...JOB, narration_plan_id: undefined });
    page();
    expect(await screen.findByText('方案已删除，追溯链断')).toBeTruthy();
    expect(screen.queryByText(/点击「生成候选标题」/)).toBeNull();
    expect(screen.getByText('方案已删除，候选标题与发布文案无从生成')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /生成候选标题/ })).toBeNull();
  });
});

describe('自检分区', () => {
  it('从未自检：说明文案 + 补测此片真发 RPC', async () => {
    page();
    // 四项徽章的度量原文都如实写「从未自检」，页脚另有一句操作指引
    expect(await screen.findAllByText('从未自检')).toHaveLength(4);
    expect(screen.getByText(/从未自检——「补测此片」/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /补测此片/ }));
    await vi.waitFor(() => {
      expect(api.selfcheck).toHaveBeenCalledWith(['w1']);
    });
  });
});

describe('发布物料', () => {
  it('方案带发布文案/话题标签：随候选标题区一并上屏', async () => {
    api.rpc.mockResolvedValue({
      plan: {
        titles: [{ text: '替嫁新娘当众揭穿真心', selected: true }],
        publish_meta: { caption: '她替嫁三年，换来一纸休书。结局在全集。', tags: ['短剧推荐', '爽剧'] },
        plan_data: { narration_texts: [] },
      },
    });
    page();
    expect(await screen.findByText('她替嫁三年，换来一纸休书。结局在全集。')).toBeTruthy();
    expect(screen.getByText('#短剧推荐 #爽剧')).toBeTruthy();
  });

  it('旧方案无发布物料：只有标题列表，不渲染空行', async () => {
    page();
    expect(await screen.findByText('替身真相')).toBeTruthy();
    expect(screen.queryByText('发布文案')).toBeNull();
  });
});

describe('成片逐句核对', () => {
  it('旁挂时间轴渲染成可点行，点一行把成片播到那一句', async () => {
    stubSrtFetch({ ok: true, status: 200, body: FILM_SRT });
    page();
    expect(await screen.findByText('一纸休书当场念出')).toBeTruthy();
    expect(screen.getByText('0:12')).toBeTruthy();
    fireEvent.click(screen.getByText('一纸休书当场念出'));
    expect(document.querySelector('video')?.currentTime).toBe(12);
    // §1.4 诚实边界：口径悬浮可见，界面不得写成「精确到语音」
    expect(document.querySelector('[title="时间轴取自烧录字幕的分行时刻，非语音对齐"]')).not.toBeNull();
  });

  it('文件确实不在（404）：说「没有逐句时间轴」，不报成失败', async () => {
    page();
    expect(await screen.findByText('本条没有逐句时间轴（旧成片 / 该模式不烧字幕）')).toBeTruthy();
    expect(screen.queryByText(/加载失败/)).toBeNull();
    expect(screen.queryByRole('button', { name: /保存 SRT/ })).toBeNull();
  });

  it('读得到地址却读失败（500）：常驻报错，不伪装成「没有」', async () => {
    stubSrtFetch({ ok: false, status: 500 });
    page();
    expect(await screen.findByText(/逐句时间轴加载失败/)).toBeTruthy();
    expect(screen.queryByText('本条没有逐句时间轴（旧成片 / 该模式不烧字幕）')).toBeNull();
  });

  it('保存 SRT：读旁挂文件走原生保存框（与工具箱同一个动作同名）', async () => {
    stubSrtFetch({ ok: true, status: 200, body: FILM_SRT });
    api.save.mockResolvedValue('D:/out/film_a1b2c3.srt');
    page();
    fireEvent.click(await screen.findByRole('button', { name: /保存 SRT/ }));
    await waitFor(() => {
      expect(api.save).toHaveBeenCalledWith('film_a1b2c3.srt', FILM_SRT);
    });
  });

  it('没有时间轴时回退到文案列表：内部段 id 不上屏', async () => {    api.rpc.mockResolvedValue({
      plan: {
        titles: [],
        angle: '替身真相',
        episode_ids: [],
        plan_data: { narration_texts: [{ id: 'narr_7c31', text: '皇后变卖首饰' }] },
      },
    });
    page();
    expect(await screen.findByText('皇后变卖首饰')).toBeTruthy();
    expect(screen.queryByText('narr_7c31')).toBeNull();
  });

  it('盘上没有成片文件：不挂空 src 的播放器，如实说文件不在', async () => {
    api.get.mockResolvedValue({ ...JOB, status: 'failed', output_path: undefined, error: '编剧模型超时' });
    page();
    expect(await screen.findByText('替身真相')).toBeTruthy();
    expect(document.querySelector('video')).toBeNull();
    expect(screen.getByText('成片文件还不在盘上（未完成或已删除）')).toBeTruthy();
  });
});
