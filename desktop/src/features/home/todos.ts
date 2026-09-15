/** 工作台待办派生：纯函数，不发 RPC。 */
import type { ModelInfo } from '@dramaclip/protocol';

export interface TodoAction {
  readonly kind: 'navigate' | 'restart-service';
  readonly label: string;
  readonly path?: string;
}

export interface TodoItem {
  readonly key: string;
  readonly text: string;
  readonly detail?: string;
  readonly severity: 'error' | 'warning' | 'info';
  readonly action?: TodoAction;
}

export interface DramaState {
  readonly id: string;
  readonly name: string;
  readonly episodeCount: number;
  readonly workCount: number;
  readonly createdAtMs: number;
}

export interface FailedJob {
  readonly id: string;
  readonly type: string;
  readonly refId: string | null;
  readonly error: string | null;
}

export interface TodoInput {
  readonly serviceDown: boolean;
  readonly models: readonly ModelInfo[] | null;
  readonly llmConfigured: boolean;
  readonly dramas: readonly DramaState[];
  readonly failedJobs: readonly FailedJob[];
  /** jobs.list 是否取到。取不到 = 在跑条数与失败待办双双不可用，必须说出来。 */
  readonly jobsAvailable: boolean;
  /** 取不到时的原因原文，进 detail 不截断。 */
  readonly jobsError: string | null;
  readonly serverTimeMs: number;
}

const DAY = 86_400_000;
const STALLED_DAYS = 14;
const MAX_STALLED = 5;

/** 仅收 ref_id=project_id 的任务类型；export→export_id、semantic→episode_id 无法路由。 */
const JOB_ROUTES: Readonly<Record<string, string>> = {
  analysis: 'analysis',
  prescreen: 'analysis',
  narration: 'produce',
};

const SEVERITY_RANK: Readonly<Record<string, number>> = { error: 0, warning: 1, info: 2 };

export function buildTodos(input: TodoInput): TodoItem[] {
  const items: TodoItem[] = [];

  if (input.serviceDown) {
    items.push({
      key: 'svc', text: 'Python 服务不可用，功能暂不可用', severity: 'error',
      action: { kind: 'restart-service', label: '重启服务' },
    });
  }

  // 服务在跑但 jobs.list 取不到：在跑条数与失败待办都成了盲区。
  // 不报的话界面会显示"0 条在跑、没有失败"，那是把"不知道"说成"没有"（规格 §3.3）。
  // serviceDown 时不重复报——那一条已经给了同一个动作。
  if (!input.serviceDown && !input.jobsAvailable) {
    items.push({
      key: 'jobs-unavailable',
      text: '任务状态取不到：在跑条数与失败待办不可用',
      detail: input.jobsError ?? '',
      severity: 'error',
      action: { kind: 'restart-service', label: '重启服务' },
    });
  }

  if (input.models !== null) {
    const missing = input.models.filter((m) => m.required && m.status !== 'installed');
    if (missing.length > 0) {
      items.push({
        key: 'models', text: `推荐模型未安装：${missing.map((m) => m.name).join('、')}`,
        severity: 'warning',
        action: { kind: 'navigate', label: '去下载', path: '/engines/asr' },
      });
    }
  }

  if (!input.llmConfigured) {
    items.push({
      key: 'llm',
      text: 'LLM 未配置：七个解说模式不会产出方案',
      detail: '仅「纯原片剪辑」「字幕金句流」不依赖编剧模型；分析层改用关键词打分',
      severity: 'error',
      action: { kind: 'navigate', label: '去配置', path: '/engines/llm' },
    });
  }

  for (const job of input.failedJobs) {
    const sub = JOB_ROUTES[job.type];
    if (sub === undefined || !job.refId) continue;
    items.push({
      key: `job-${job.id}`,
      text: `任务失败: ${job.error ?? '未知原因'}`,
      severity: 'error',
      action: { kind: 'navigate', label: '去处理', path: `/projects/${job.refId}/${sub}` },
    });
  }

  for (const drama of input.dramas) {
    if (drama.episodeCount === 0 || drama.workCount > 0) continue;
    const age = (input.serverTimeMs - drama.createdAtMs) / DAY;
    if (age < STALLED_DAYS) continue;
    items.push({
      key: `stalled-${drama.id}`,
      text: `${drama.name}：${String(drama.episodeCount)} 集已就位 ${String(Math.floor(age))} 天，还没有成品`,
      severity: 'info',
      action: { kind: 'navigate', label: '去出片', path: `/projects/${drama.id}/produce` },
    });
  }

  return capStalled(items).sort(
    (a, b) => (SEVERITY_RANK[a.severity] ?? 2) - (SEVERITY_RANK[b.severity] ?? 2) || (a.key < b.key ? -1 : 1),
  );
}

function capStalled(items: TodoItem[]): TodoItem[] {
  const stalled = items.filter((item) => item.key.startsWith('stalled-'));
  if (stalled.length <= MAX_STALLED) return items;
  const overflow = stalled.length - MAX_STALLED;
  const kept = stalled.slice(0, MAX_STALLED);
  const rest = items.filter((item) => !stalled.includes(item));
  const last = kept[kept.length - 1];
  if (last !== undefined) {
    rest.push({ ...last, text: `${last.text}（另有 ${String(overflow)} 部同样停滞）` });
  }
  return rest;
}

export function buildDramas(
  projects: readonly { id: string; name: string; episode_count: number; created_at: number }[],
  works: readonly { id: string; project_id: string }[],
): DramaState[] {
  const counts = new Map<string, number>();
  for (const w of works) counts.set(w.project_id, (counts.get(w.project_id) ?? 0) + 1);
  return projects.map((p) => ({
    id: p.id,
    name: p.name,
    episodeCount: p.episode_count,
    workCount: counts.get(p.id) ?? 0,
    createdAtMs: p.created_at,
  }));
}
