/** 工作台（规格 §4.1）：回答"今天该干什么"。
 *
 * 主区 = 今日待办（首要）+ 3 统计芯片 + 最近成品 6 条 + 继续上次
 * 右栏 = 环境就绪度 + 快速上手
 *
 * 右栏的「工具箱」槽位缺席：今天那个叫工具箱的面板里一个工具都没有，三项全是
 * 导轨已有目的地的重复跳转，已随本任务删除。真工具箱属 P-3.4。缺席而非假控件。
 *
 * 「最近成品」不出缩略图：逐片封面不存在（repos/exports.py 无 cover_path），
 * 拿项目封面冒充逐片封面正是 §4.5 要治的"同剧 9 条片共用一张封面"。缩略图归 P-3.3。
 */
import { FolderAddOutlined } from '@ant-design/icons';
import { App as AntdApp, Button } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { JobInfo } from '@dramaclip/protocol';
import { PageHeader, PageShell } from '../../components/layout/PageKit';
import { exportApi, restartService } from '../../services/client';
import { tokens } from '../../styles/theme';
import { ContinueCard } from './ContinueCard';
import { createDramaFromFolder } from './createDrama';
import { EmptyWorkbench } from './EmptyWorkbench';
import { EnvPanel, TipsPanel } from './EnvPanel';
import { RecentWorks } from './RecentWorks';
import { StatChips } from './StatChips';
import { TodoList } from './TodoList';
import { buildStats, type WorkbenchStats } from './stats';
import { buildDramas, buildTodos, type FailedJob, type TodoItem } from './todos';
import { useWorkbench, type WorkbenchData } from './useWorkbench';

/** 主区最近成品的条数（规格 §4.1：6 条）。 */
const RECENT_WORKS = 6;
/** ref_id 是 project_id 的任务类型——与 todos.ts 的 JOB_ROUTES 同一批。
 *  这里再判一次是因为 ref_id 语义异构（export 的是 export_id、model_download 的是
 *  model_id），把它们的 ref_id 当 project_id 拼路径会跳错剧。 */
const PROJECT_JOB_TYPES = new Set(['prescreen', 'analysis', 'narration']);

/** 建剧与重启服务两个动作：状态 + 回调收拢，让 HomePage 只剩编排。 */
function useHomeActions() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [creating, setCreating] = useState(false);

  const onCreate = useCallback(() => {
    setCreating(true);
    createDramaFromFolder()
      .then((created) => {
        if (created === null) return;
        message.success(`已创建「${created.name}」`);
        void navigate(created.entryPath);
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        setCreating(false);
      });
  }, [message, navigate]);

  const onRestart = useCallback(() => {
    restartService().catch((error: unknown) => {
      message.error(error instanceof Error ? error.message : String(error));
    });
  }, [message]);

  return { creating, onCreate, onRestart };
}

export function HomePage() {
  const { data, ready, reload } = useWorkbench();
  const { creating, onCreate, onRestart } = useHomeActions();

  // 逐片封面补拍（幂等）：历史成片缺封面时后台补，完成刷新一次
  useEffect(() => {
    if (!ready || data.works.length === 0) return;
    let cancelled = false;
    void exportApi
      .ensureCovers()
      .then((result) => {
        if (!cancelled && result.generated > 0) void reload();
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [ready, reload, data.works.length]);

  const dramas = buildDramas(data.projects, data.works);
  const todos = buildTodos({
    serviceDown: !ready,
    models: data.models,
    llmConfigured: data.llmBaseUrl !== '',
    dramas,
    failedJobs: failedJobs(data.jobs),
    jobsAvailable: data.jobsAvailable,
    jobsError: data.jobsError,
    serverTimeMs: data.serverTimeMs,
  });
  const stats = buildStatsFromData(data);
  const hasDramas = data.projects.length > 0;

  return (
    <PageShell>
      <PageHeader
        title="工作台"
        desc={greetingLine()}
        actions={
          // 空态下 primary 归 EmptyWorkbench，这里不给——DSS §3.1「每屏 primary 至多 1 个」
          hasDramas ? (
            <Button type="primary" icon={<FolderAddOutlined />} loading={creating} disabled={creating} onClick={onCreate}>
              新增项目
            </Button>
          ) : undefined
        }
      />
      <HomeBody
        data={data}
        todos={todos}
        stats={stats}
        hasDramas={hasDramas}
        creating={creating}
        onCreate={onCreate}
        onRestart={onRestart}
      />
    </PageShell>
  );
}

/** 双栏主体：左 = 待办 + 芯片/成品/继续上次（或空态引导），右 = 环境 + 上手。 */
function HomeBody({
  data,
  todos,
  stats,
  hasDramas,
  creating,
  onCreate,
  onRestart,
}: {
  data: WorkbenchData;
  todos: TodoItem[];
  stats: WorkbenchStats;
  hasDramas: boolean;
  creating: boolean;
  onCreate: () => void;
  onRestart: () => void;
}): React.ReactElement {
  const navigate = useNavigate();
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0,1fr) 330px',
        gap: tokens.spaceLg,
        alignItems: 'start',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXl, minWidth: 0 }}>
        {hasDramas && <StatChips stats={stats} />}
        <TodoList
          items={todos}
          onNavigate={(path) => {
            void navigate(path);
          }}
          onRestartService={onRestart}
        />
        {hasDramas ? (
          <>
            <RecentWorks works={data.works.slice(0, RECENT_WORKS)} />
            <ContinueCard projects={data.projects} nowMs={data.serverTimeMs} />
          </>
        ) : (
          <EmptyWorkbench creating={creating} onCreate={onCreate} />
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
        <EnvPanel models={data.models} llmBaseUrl={data.llmBaseUrl} ttsEngine={data.ttsEngine} />
        <TipsPanel />
      </div>
    </div>
  );
}

function failedJobs(jobs: readonly JobInfo[]): FailedJob[] {
  return jobs
    .filter((job) => job.status === 'failed' && PROJECT_JOB_TYPES.has(job.type))
    .map((job) => ({
      id: job.id,
      type: job.type,
      refId: job.ref_id ?? null,
      error: job.error ?? '',
    }));
}

function buildStatsFromData(data: WorkbenchData): WorkbenchStats {
  return buildStats({
    dramaCount: data.projects.length,
    running: data.jobs
      .filter((job) => job.status === 'running' || job.status === 'pending')
      .map((job) => ({ id: job.id, progress: job.progress, createdAtMs: job.created_at })),
    serverTimeMs: data.serverTimeMs,
    jobsAvailable: data.jobsAvailable,
    works: data.works,
  });
}

function greetingLine(): string {
  const now = new Date();
  const week = ['日', '一', '二', '三', '四', '五', '六'][now.getDay()] ?? '';
  const hour = now.getHours();
  const greeting =
    hour < 6 ? '夜深了' : hour < 12 ? '上午好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
  return `${greeting} · ${String(now.getMonth() + 1)}月${String(now.getDate())}日 星期${week}`;
}
