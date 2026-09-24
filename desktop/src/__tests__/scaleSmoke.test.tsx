// @vitest-environment jsdom
/**
 * 规模冒烟（09-10 规格 §9 验收项 7）：50 部剧 + 500 条成品 + 单剧 100 集下，
 * 剧库矩阵、成品分组网格、素材列表三处必须完整渲染且首屏构建时间可接受。
 *
 * 诚实声明：jsdom 量不出帧率——这里量的是「首屏构建耗时 + 行数完整性」，
 * 是虚拟列表要不要上的回归证据；真实滚动帧率在 dev 实跑用 data-scale 库人工观察
 * （scripts/seed_scale_data.py）。耗时上限放得宽，防的是慢机器上的假红，
 * 不是精确基准；具体毫秒数打在 warn 里供选型判断。
 */
import { cleanup, render, screen } from '@testing-library/react';
import type { RefObject } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as AntdApp } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import type { Episode, Project, WorkItem } from '@dramaclip/protocol';
import { DramaMatrix } from '../features/home/DramaMatrix';
import { WorksPage } from '../features/works/WorksPage';
import { EpisodeListPanel } from '../features/analysis/EpisodeListPanel';
import { useJobsStore } from '../stores/jobs';
import { useUiStore } from '../stores/ui';

const api = vi.hoisted(() => ({
  listWorks: vi.fn(),
  projectList: vi.fn(),
}));

vi.mock('../services/client', () => ({
  mediaUrl: (path: string) => `dramaclip://local/${path}`,
  listWorks: api.listWorks,
  projectApi: { list: api.projectList },
  exportApi: { selfcheck: vi.fn(), delete: vi.fn() },
  revealInFolder: vi.fn(),
  pickFolder: vi.fn(),
  copyFiles: vi.fn(),
  onServiceEvent: () => (): void => undefined,
}));

const BASE = 1758600000000;

// 每条冒烟只有一个毫秒预算：findByText 的等待线、elapsed 断言、vitest 的 runner
// 超时全部从它派生。三处各写一个数字等于三套真相——慢机器上 runner 会先于断言
// 掐死，「超时」被误读成「渲染劣化」，快机器上又看不出余量还剩多少。
const BUDGET_MS = { matrix: 15_000, works: 45_000, episodes: 15_000 };

// runner 只兜死循环：留一倍余量，保证永远是 elapsed 断言先响。
function runnerTimeoutMs(budget: number): number {
  return budget * 2;
}
const MODES = [
  'intro_narration',
  'dialogue_narration',
  'full_narration',
  'inner_monologue',
  'dual_host_chat',
  'cross_narration',
  'ultra_short_hook',
  'subtitle_flow',
  'raw_clip',
] as const;
const STATES: WorkItem['selfcheck_state'][] = ['passed', null, 'failed', 'partial'];

function genProjects(count: number): Project[] {
  const projects: Project[] = [];
  for (let index = 0; index < count; index += 1) {
    projects.push({
      id: `p${String(index + 1)}`,
      name: `规模剧${String(index + 1).padStart(2, '0')}`,
      source_path: `D:/scale/p${String(index + 1)}`,
      status: 'active',
      created_at: BASE - index * 86_400_000,
      episode_count: index === 0 ? 100 : 8,
      settings: {},
    });
  }
  return projects;
}

function genWorks(count: number, projects: readonly Project[]): WorkItem[] {
  const works: WorkItem[] = [];
  for (let index = 0; index < count; index += 1) {
    const project = projects[index % projects.length];
    if (project === undefined) throw new Error('生成器越界：projects 为空');
    works.push({
      id: `w${String(index + 1)}`,
      project_id: project.id,
      project_name: project.name,
      narration_mode: MODES[index % MODES.length] ?? 'full_narration',
      output_path: `D:/scale/outputs/w${String(index + 1)}.mp4`,
      duration_s: 60 + (index % 120),
      size_bytes: 100_000_000 + index * 1_000_000,
      completed_at: BASE - index * 3_600_000,
      narration_plan_id: `plan${String(index + 1)}`,
      angle: `角度${String((index % 6) + 1)}`,
      episode_ids: ['e1', 'e2'],
      selfcheck: null,
      selfcheck_state: STATES[index % STATES.length] ?? null,
    });
  }
  return works;
}

function genEpisodes(count: number): Episode[] {
  const episodes: Episode[] = [];
  for (let index = 0; index < count; index += 1) {
    const status = index % 7 === 6 ? 'failed' : index % 3 === 2 ? 'done' : 'pending';
    episodes.push({
      id: `e${String(index + 1)}`,
      episode_number: index + 1,
      name: `ep${String(index + 1).padStart(3, '0')}`,
      source_path: `D:/scale/big/ep${String(index + 1).padStart(3, '0')}.mp4`,
      duration: 120 + (index % 60),
      status,
      has_audio: index === 3 ? false : true,
    });
  }
  return episodes;
}

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

beforeEach(() => {
  useUiStore.getState().setServiceState('ready');
  useJobsStore.setState({ drawerOpen: false });
  vi.clearAllMocks();
});

afterEach(cleanup);

/** 三个冒烟体拆成模块级函数：describe 回调行数红线（60）不吃嵌套用例。 */
function smokeMatrix(): void {
  const projects = genProjects(50);
  const works = genWorks(500, projects);
  const started = performance.now();
  render(
    <DramaMatrix
      projects={projects}
      works={works}
      jobs={[]}
      serverTimeMs={BASE}
      etaLabel=""
      onNavigate={vi.fn()}
    />,
  );
  const elapsed = performance.now() - started;
  console.warn(`[scaleSmoke] 剧库矩阵 50 剧 + 500 成品聚合首屏: ${String(Math.round(elapsed))}ms`);
  expect(screen.getAllByRole('listitem')).toHaveLength(50);
  expect(elapsed).toBeLessThan(BUDGET_MS.matrix);
}

async function smokeWorksGrid(): Promise<void> {
  const projects = genProjects(50);
  api.listWorks.mockResolvedValue(genWorks(500, projects));
  api.projectList.mockResolvedValue(projects);
  const started = performance.now();
  render(
    <MemoryRouter>
      <AntdApp>
        <WorksPage />
      </AntdApp>
    </MemoryRouter>,
  );
  await screen.findByText('共 500 个', undefined, { timeout: BUDGET_MS.works });
  const elapsed = performance.now() - started;
  console.warn(`[scaleSmoke] 成品网格 500 条首屏: ${String(Math.round(elapsed))}ms`);
  // 上限防的是量级恶化（并行跑全量套件时实测 17s）；选型看的是 warn 里的毫秒数与 dev 实跑帧率
  expect(elapsed).toBeLessThan(BUDGET_MS.works);
}

function smokeEpisodeList(): void {
  const episodes = genEpisodes(100);
  const byId = new Map(episodes.map((episode) => [episode.id, episode]));
  const dragIndex: RefObject<number | null> = { current: null };
  const started = performance.now();
  render(
    <EpisodeListPanel
      orderedIds={episodes.map((episode) => episode.id)}
      byId={byId}
      highlights={{}}
      activeEpisodeId={null}
      selectedIds={[]}
      running={false}
      onActivate={vi.fn()}
      onToggle={vi.fn()}
      dragIndex={dragIndex}
      overIndex={null}
      setOverIndex={vi.fn()}
      onDragStart={vi.fn()}
      onDrop={vi.fn()}
      onMove={vi.fn()}
    />,
  );
  const elapsed = performance.now() - started;
  console.warn(`[scaleSmoke] 素材列表 100 集首屏: ${String(Math.round(elapsed))}ms`);
  expect(screen.getAllByText(/^ep\d{3}$/)).toHaveLength(100);
  expect(screen.getByText(/1 集缺音频轨，无法转写/)).toBeTruthy();
  expect(elapsed).toBeLessThan(BUDGET_MS.episodes);
}

describe('规模冒烟：三处列表在目标数据量下完整渲染', () => {
  it('剧库矩阵：50 部剧 + 500 条成品聚合，50 行全在', smokeMatrix, runnerTimeoutMs(BUDGET_MS.matrix));

  it('成品分组网格：500 条成品上屏，计数照实', smokeWorksGrid, runnerTimeoutMs(BUDGET_MS.works));

  it('素材列表：单剧 100 集全渲染，缺音轨告警同时在场', smokeEpisodeList, runnerTimeoutMs(BUDGET_MS.episodes));
});
