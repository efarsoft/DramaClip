/** 工作台（规格 §4.1 + 卷三意见 04）：回答"今天该干什么"。
 *
 * 主区 = 今日待办（首要）+ 我的剧矩阵（吸收原三统计芯片/最近成品/继续上次）
 * 右栏 = 环境就绪度 + 快速上手
 *
 * 原六块变四块的理由：芯片/成品/继续卡片各自只有一行信息量，摊开是三块地皮；
 * 矩阵一行一部剧，把同一部剧的阶段、卡点、成品数、继续入口收进一眼（卷三图 1）。
 * 「继续上次」不再是独立卡片——最近打开的剧在矩阵置顶 + 铺底 + 芯片点名。
 *
 * 右栏的「工具箱」槽位缺席：真工具箱属 P-3.4。缺席而非假控件。
 */
import { FolderAddOutlined } from '@ant-design/icons';
import { App as AntdApp, Button } from 'antd';
import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { JobInfo } from '@dramaclip/protocol';
import { PageHeader, PageShell } from '../../components/layout/PageKit';
import { restartService } from '../../services/client';
import { tokens } from '../../styles/theme';
import { createDramaFromFolder } from './createDrama';
import { DramaMatrix } from './DramaMatrix';
import { EmptyWorkbench } from './EmptyWorkbench';
import { EnvPanel, TipsPanel } from './EnvPanel';
import { TodoList } from './TodoList';
import { buildStats, type WorkbenchStats } from './stats';
import { buildDramas, buildTodos, type FailedJob, type TodoItem } from './todos';
import { useWorkbench, type WorkbenchData } from './useWorkbench';

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
  const { data, ready } = useWorkbench();
  const { creating, onCreate, onRestart } = useHomeActions();

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

/** 双栏主体：左 = 待办 + 我的剧矩阵（或空态引导），右 = 环境 + 上手。 */
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
        <TodoList
          items={todos}
          onNavigate={(path) => {
            void navigate(path);
          }}
          onRestartService={onRestart}
        />
        {hasDramas ? (
          <DramaMatrix
            projects={data.projects}
            works={data.works}
            jobs={data.jobs}
            serverTimeMs={data.serverTimeMs}
            etaLabel={stats.runningEtaLabel}
            onNavigate={(route) => {
              void navigate(route);
            }}
          />
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
