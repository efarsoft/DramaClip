/** 三统计芯片（规格 §4.1）：剧数 / 在跑条数+ETA / 成品数+周增。
 *
 * 取代旧的四芯片（项目/剧集/已分析/已导出）——那四个是数据库计数，
 * 回答不了"今天该干什么"。
 * ETA 与周增的措辞按 stats.ts 的口径：一个是量级提示（「预计还需」），
 * 一个在样本被截断时如实显示 '—'。
 */
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';
import type { WorkbenchStats } from './stats';

interface Chip {
  readonly key: string;
  readonly value: string;
  readonly label: string;
  readonly note: string;
}

export function StatChips({ stats }: { stats: WorkbenchStats }): ReactElement {
  const chips: Chip[] = [
    { key: 'dramas', value: String(stats.dramaCount), label: '部剧', note: '' },
    {
      key: 'running',
      value: stats.runningValue,
      label: stats.jobsAvailable ? '条在跑' : '条在跑 · 状态取不到',
      note: stats.runningEtaLabel,
    },
    {
      key: 'works',
      value: stats.workCountOverflow ? `${String(stats.workCount)}+` : String(stats.workCount),
      label: '条成品',
      // 周增不可用（成品数触到扫描上限）时显示 '—'：被截断的样本算不出可信周增。
      // 零增则显示 +0，隐藏它会让人以为没算。
      note: `本周 ${stats.workWeekDelta === null ? '—' : `+${String(stats.workWeekDelta)}`}`,
    },
  ];
  return (
    <div style={{ display: 'flex', gap: tokens.spaceMd }}>
      {chips.map((chip) => (
        <ChipView key={chip.key} chip={chip} />
      ))}
    </div>
  );
}

function ChipView({ chip }: { chip: Chip }): ReactElement {
  return (
    <div
      data-testid="stat-chip"
      style={{
        flex: 1,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        padding: `${String(tokens.spaceXs)} ${String(tokens.spaceLg)}`,
      }}
    >
      <span
        style={{
          fontSize: tokens.fontDisplay,
          fontWeight: 700,
          lineHeight: '26px',
          color: tokens.textPrimary,
          fontFamily: tokens.fontFamilyMono,
        }}
      >
        {chip.value}
      </span>
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>{chip.label}</span>
      {chip.note !== '' && (
        <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{chip.note}</span>
      )}
    </div>
  );
}
