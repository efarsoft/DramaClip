/** 成品库纯逻辑（09-10 §4.5 / 卷三图5）：分组、徽章三态文案、绝对时间、体积合计——不发 RPC。 */
import type { Episode, SelfCheck, WorkItem } from '@dramaclip/protocol';
import { MODE_INFO } from '../../components/modeMeta';
import { tokens } from '../../styles/theme';

/** 模式色板（§3.4）：六枚全部从 tokens 派生，九种模式按序循环取用——色值只在 theme.ts 有一份。 */
const MODE_COLORS = [
  tokens.colorPrimary,
  tokens.colorAccent,
  tokens.colorSuccess,
  tokens.colorWarning,
  tokens.colorError,
  tokens.colorInfo,
] as const;

export function modeColor(mode: string | undefined): string {
  if (mode === undefined) return tokens.textTertiary;
  const index = MODE_INFO.findIndex((item) => item.mode === mode);
  return MODE_COLORS[index % MODE_COLORS.length] ?? tokens.colorPrimary;
}

export function durationLabel(s: number | undefined): string {
  if (s === undefined || s <= 0) return '';
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${String(m)}:${String(sec).padStart(2, '0')}`;
}

export function formatSize(bytes: number | undefined): string {
  if (bytes === undefined || bytes <= 0) return '—';
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

/** 批量操作的量化确认（§3.4 规矩①）：合计体积一律 GB 两位小数，由实测字节换算。 */
export function formatTotalGb(bytes: number): string {
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}
/** 完成时间：绝对 M/D HH:mm。不用「昨天/今天」——那是拿本机时钟冒充事实的相对话术。 */
export function formatWhen(ms: number | undefined): string {
  if (ms === undefined) return '';
  const date = new Date(ms);
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${String(date.getMonth() + 1)}/${String(date.getDate())} ${hh}:${mm}`;
}

export interface WorkGroup {
  readonly projectId: string;
  readonly name: string;
  readonly works: WorkItem[];
}

/** 按剧分组；剧内按完成时间倒序，剧间按最新成片时间倒序。 */
export function groupWorks(works: readonly WorkItem[]): WorkGroup[] {
  const map = new Map<string, WorkGroup>();
  for (const work of works) {
    const group = map.get(work.project_id) ?? {
      projectId: work.project_id,
      name: work.project_name,
      works: [],
    };
    group.works.push(work);
    map.set(work.project_id, group);
  }
  const list = [...map.values()];
  for (const group of list) {
    group.works.sort((a, b) => (b.completed_at ?? 0) - (a.completed_at ?? 0));
  }
  return list.sort((a, b) => latestOf(b) - latestOf(a));
}

function latestOf(group: WorkGroup): number {
  return Math.max(...group.works.map((w) => w.completed_at ?? 0));
}

/** 卡面取材行：有集数映射给区间（EP04–EP11），没有就只报条数——拿不到的不编。 */
export function episodeLabel(episodeIds: readonly string[] | null | undefined, episodes?: readonly Episode[]): string {
  if (episodeIds === null || episodeIds === undefined || episodeIds.length === 0) return '';
  if (episodes !== undefined) {
    const numbers = episodeIds
      .map((id) => episodes.find((ep) => ep.id === id)?.episode_number)
      .filter((n): n is number => n !== undefined);
    if (numbers.length === episodeIds.length) {
      const min = Math.min(...numbers);
      const max = Math.max(...numbers);
      const one = `EP${String(min).padStart(2, '0')}`;
      return min === max ? `取材 ${one}` : `取材 ${one}–EP${String(max).padStart(2, '0')}`;
    }
  }
  return `取材 ${String(episodeIds.length)} 集`;
}

/** 自检筛选 chip（#30）：'all' 只活在界面层，不发服务端。 */
export type WorksFilterKey = 'all' | 'passed' | 'failed' | 'unchecked';

export const WORKS_FILTERS: readonly { key: WorksFilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'passed', label: '自检通过' },
  { key: 'failed', label: '有红' },
  { key: 'unchecked', label: '未检' },
];

/** 徽章三态（意见08）：✓ 实底绿 / ✕ 红带度量原文 / — 灰描边空心。「—」与绿勾是两种视觉。 */
export interface SelfCheckBadge {
  readonly key: 'duration' | 'narration' | 'silence' | 'freeze';
  readonly tone: 'ok' | 'fail' | 'none';
  readonly text: string;
  /** 度量原文（tooltip 与详情页「看度量原文」）；未检时说明量不到的原因。 */
  readonly detail: string;
}

export function selfCheckBadges(sc: SelfCheck | null | undefined): SelfCheckBadge[] {
  if (sc === null || sc === undefined) {
    return [
      { key: 'duration', tone: 'none', text: '— 时长未检', detail: '从未自检' },
      { key: 'narration', tone: 'none', text: '— 配音未检', detail: '从未自检' },
      { key: 'silence', tone: 'none', text: '— 静音段未检', detail: '从未自检' },
      { key: 'freeze', tone: 'none', text: '— 冻结帧未检', detail: '从未自检' },
    ];
  }
  return [durationBadge(sc), narrationBadge(sc), silenceBadge(sc), freezeBadge(sc)];
}

function tone(pass: boolean | null): 'ok' | 'fail' | 'none' {
  if (pass === true) return 'ok';
  if (pass === false) return 'fail';
  return 'none';
}

function durationBadge(sc: SelfCheck): SelfCheckBadge {
  const item = sc.duration;
  const detail =
    item.measured_s !== undefined && item.budget_s !== undefined
      ? `实测 ${item.measured_s.toFixed(1)}s · 声明 ${item.budget_s.toFixed(1)}s · 容差 ${item.tolerance_s?.toFixed(1) ?? '?'}s`
      : '声明或实测时长拿不到';
  return {
    key: 'duration',
    tone: tone(item.pass),
    text: item.pass === true ? '✓ 时长达标' : item.pass === false ? '✕ 时长不达标' : '— 时长未检',
    detail,
  };
}

function narrationBadge(sc: SelfCheck): SelfCheckBadge {
  const item = sc.narration;
  const audio = item.has_audio === true ? '有音轨' : '无音轨';
  const detail =
    item.expected === 'none'
      ? item.has_audio === true
        ? '原声模式，有音轨即过'
        : '无音轨'
      : item.planned_segments !== undefined
        ? `方案旁白段 ${String(item.planned_segments)} 条 · ${audio}`
        : '方案缺失，配音判据量不到';
  return {
    key: 'narration',
    tone: tone(item.pass),
    text: item.pass === true ? '✓ 含配音' : item.pass === false ? '✕ 配音不足' : '— 配音未检',
    detail,
  };
}

function silenceBadge(sc: SelfCheck): SelfCheckBadge {
  const item = sc.silence;
  const detail =
    item.reason !== undefined
      ? `${item.reason}（整片皆静音）`
      : item.mean_volume_db !== undefined
        ? `整片均值 ${item.mean_volume_db.toFixed(1)} dB · 下限 -70 dB`
        : '响度量不到';
  return {
    key: 'silence',
    tone: tone(item.pass),
    text: item.pass === true ? '✓ 无静音段' : item.pass === false ? '✕ 有静音段' : '— 静音段未检',
    detail,
  };
}

function freezeBadge(sc: SelfCheck): SelfCheckBadge {
  const item = sc.freeze;
  const detail =
    item.max_freeze_s !== undefined
      ? `最长静止段 ${item.max_freeze_s.toFixed(1)}s · 上限 2.0s`
      : '画面量不到';
  return {
    key: 'freeze',
    tone: tone(item.pass),
    text: item.pass === true ? '✓ 无长冻结帧' : item.pass === false ? '✕ 有长冻结帧' : '— 冻结帧未检',
    detail,
  };
}

/** 已选成片的合计字节（量化确认的数据源）。 */
export function selectedBytes(works: readonly WorkItem[]): number {
  return works.reduce((sum, work) => sum + (work.size_bytes ?? 0), 0);
}
