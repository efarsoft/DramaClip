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

/** 日期（完成/录入）：绝对 YYYY/MM/DD，只到日；缺失如实报「—」。与 formatWhen（M/D HH:mm）语义不同，不复用。 */
export function formatDate(ms: number | undefined): string {
  if (ms === undefined) return '—';
  const d = new Date(ms);
  return `${String(d.getFullYear())}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
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
export type WorksFilterKey = 'all' | 'passed' | 'failed' | 'partial' | 'unchecked';

export const WORKS_FILTERS: readonly { key: WorksFilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'passed', label: '自检通过' },
  { key: 'failed', label: '有红' },
  // partial = 「有灰无红」（自检部分量到、部分量不到）：此前筛不出也看不见（规格 §1.4）
  { key: 'partial', label: '有灰' },
  { key: 'unchecked', label: '未检' },
];

/** 徽章三态（意见08）：✓ 实底绿 / ✕ 红带度量原文 / — 灰描边空心。「—」与绿勾是两种视觉。 */
export interface SelfCheckBadge {
  readonly key: string;
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

/** 四项徽章之外的读数行（成片详情）。这些项不进汇总态，**有数才出行**——早期成绩单
 *  没有这些键就不编造行。它们早在服务端落库（开场质检 / 收尾出点 / 音画同步 /
 *  响度读数 / 画面落位 / 残字影子），此前协议类型里没有、界面一行都没显示过
 *  （2026-11-24 审查实锤）。 */
export interface SelfCheckReading {
  readonly key: 'opening' | 'ending' | 'avsync' | 'caption_placement' | 'loudness' | 'caption_residue';
  readonly tone: SelfCheckBadge['tone'];
  readonly text: string;
  readonly detail: string;
}

export function selfCheckReadings(sc: SelfCheck | null | undefined): SelfCheckReading[] {
  if (sc === null || sc === undefined) {
    return [];
  }
  const rows: SelfCheckReading[] = [];
  const opening = sc.opening;
  if (opening !== undefined && opening !== null) {
    rows.push({
      key: 'opening',
      tone: tone(opening.pass),
      text: opening.pass === true ? '✓ 开场有可闻声' : opening.pass === false ? '✕ 开场静默' : '— 开场未检',
      detail:
        opening.reason ??
        (opening.window_s !== undefined && opening.mean_volume_db !== undefined
          ? `前 ${opening.window_s.toFixed(0)}s 均值 ${opening.mean_volume_db.toFixed(1)} dB`
          : '量不到'),
    });
  }
  const ending = sc.ending;
  if (ending !== undefined) {
    const cut = ending.end_s !== undefined ? `最后一刀在 ${ending.end_s.toFixed(1)}s` : '最后一刀';
    rows.push({
      key: 'ending',
      tone: tone(ending.pass),
      text: ending.pass === true ? '✓ 收尾切在句末' : ending.pass === false ? '✕ 收尾把话切断' : '— 收尾未检',
      detail:
        ending.reason === 'mid_line'
          ? `${cut}，落在台词「${ending.line ?? ''}」中间——话被拦腰`
          : ending.reason === 'mid_sentence'
            ? `${cut}，上一句还不是句末、下一句紧接着就来——答案没录进来`
            : ending.pass === true
              ? '出点落在句末'
              : '没有台词时间轴，量不到',
    });
  }
  const avsync = sc.avsync;
  if (avsync !== undefined) {
    const measured = avsync.median_ms !== undefined && avsync.dispersion_ms !== undefined;
    rows.push({
      key: 'avsync',
      tone: tone(avsync.pass),
      text: avsync.pass === true ? '✓ 音画同步' : avsync.pass === false ? '✕ 音画偏移' : '— 音画同步未检',
      detail: measured
        ? `各采样点偏移中位 ${avsync.median_ms.toFixed(1)} ms · 离散 ${avsync.dispersion_ms.toFixed(
            1,
          )} ms · ${String(avsync.samples ?? '?')} 点 · 判据均 ≤ 40 ms`
        : '有效采样点不足两点，量不到',
    });
  }
  const placement = sc.caption_placement;
  if (placement !== undefined) {
    const measured =
      placement.measured_top !== undefined &&
      placement.measured_bottom !== undefined &&
      placement.expected_top !== undefined &&
      placement.expected_bottom !== undefined;
    rows.push({
      key: 'caption_placement',
      tone: tone(placement.pass),
      text:
        placement.pass === true
          ? '✓ 字幕盖住台词带'
          : placement.pass === false
            ? '✕ 字幕偏离台词带'
            : '— 字幕落位未检',
      detail: measured
        ? `字幕实测 ${placement.measured_top.toFixed(2)}–${placement.measured_bottom.toFixed(2)} · 台词带 ${placement.expected_top.toFixed(2)}–${placement.expected_bottom.toFixed(2)}（画面高占比）· 中心偏 ${placement.center_offset?.toFixed(2) ?? '?'}`
        : (placement.reason ?? '量不到'),
    });
  }
  const loudness = sc.loudness;
  if (loudness !== undefined && loudness !== null) {
    // 读数不设徽章：导出链的复核门禁已经硬失败守门，这里只是归一后的复核实测（历史账）
    rows.push({
      key: 'loudness',
      tone: 'none',
      text: '响度读数',
      detail: `综合响度 ${loudness.measured_i.toFixed(1)} LUFS（目标 ${loudness.target_i.toFixed(
            1,
          )}，偏 ${loudness.deviation_lu.toFixed(1)} LU）· 真峰值 ${loudness.measured_tp.toFixed(
            1,
          )} dBTP（上限 ${loudness.target_tp.toFixed(1)}）· 响度范围 ${loudness.lra.toFixed(1)} LU`,
    });
  }
  const residue = sc.caption_residue;
  if (residue !== undefined && (residue.band_frames ?? 0) > 0) {
    // 影子项：只攒数据不改徽章
    rows.push({
      key: 'caption_residue',
      tone: 'none',
      text: '残字候选',
      detail: `字幕带内多出一簇文字的帧 ${String(residue.residue_frames ?? 0)}/${String(
            residue.band_frames ?? 0,
          )}（攒数据用，不作判定）`,
    });
  }
  return rows;
}

/** 已选成片的合计字节（量化确认的数据源）。 */
export function selectedBytes(works: readonly WorkItem[]): number {
  return works.reduce((sum, work) => sum + (work.size_bytes ?? 0), 0);
}
