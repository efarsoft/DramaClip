/** 三统计芯片（规格 §4.1）：剧数 / 在跑条数+ETA / 成品数+周增。
 *
 * 取代旧的四芯片（项目/剧集/已分析/已导出）——那四个是数据库计数，
 * 回答不了"今天该干什么"。
 * ETA 与周增的措辞按 stats.ts 的口径：一个是量级提示（「预计还需」），
 * 一个在样本被截断时如实显示 '—'。
 */
import type { ReactElement, ReactNode } from 'react';
import { FileDoneOutlined, LoadingOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { tokens } from '../../styles/theme';
import type { WorkbenchStats } from './stats';

interface Chip {
  readonly key: string;
  readonly icon: ReactNode;
  readonly value: string;
  readonly label: string;
  readonly note: string;
}

export function StatChips({ stats }: { stats: WorkbenchStats }): ReactElement {
  const chips: Chip[] = [
    { key: 'dramas', icon: <FileDoneOutlined />, value: String(stats.dramaCount), label: '部剧', note: '' },
    {
      key: 'running',
      icon: <LoadingOutlined />, value: stats.runningValue,
      label: stats.jobsAvailable ? '条在跑' : '条在跑 · 状态取不到',
      note: stats.runningEtaLabel,
    },
    {
      key: 'works',
      icon: <PlayCircleOutlined />, value: stats.workCountOverflow ? `${String(stats.workCount)}+` : String(stats.workCount),
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
        flexDirection: 'row',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `${String(tokens.spaceMd)} ${String(tokens.spaceLg)}`,
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        boxShadow: tokens.shadowCard,
      }}
    >
      <span style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
        <span
          style={{
            width: 38, height: 38, borderRadius: tokens.radiusControl,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: tokens.accentSoft, color: tokens.colorPrimary, fontSize: 17,
          }}
        >
          {chip.icon}
        </span>
        <span style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <span
            style={{
              fontSize: '26px',
              fontWeight: 700,
              lineHeight: '28px',
              color: tokens.textPrimary,
              fontFamily: tokens.fontFamilyMono,
            }}
          >
            {chip.value}
          </span>
          <span style={{ fontSize: tokens.fontMicro, color: tokens.textSecondary }}>{chip.label}</span>
        </span>
      </span>
      {chip.note !== '' && (
        <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{chip.note}</span>
      )}
    </div>
  );
}
