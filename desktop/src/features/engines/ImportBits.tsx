/**
 * 导入向导的排版小件：字段行、旁注、标签、带说明的单选组。
 *
 * 只有「怎么摆」，没有「怎么说」（文案表在 importWizard.ts 挨着它服务的枚举），
 * 更没有「能不能走」——那条判据全在 importWizard.ts 一处。
 */
import type { CSSProperties, ReactElement, ReactNode } from 'react';
import { Radio } from 'antd';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

/** 一行「标签 + 内容」：向导里每个实测事实都这样摆，标签固定宽度对齐。 */
export function Field({ label, children }: { label: string; children: ReactNode }): ReactElement {
  return (
    <div style={{ display: 'flex', gap: tokens.spaceMd, alignItems: 'flex-start' }}>
      <span style={{ width: 64, flexShrink: 0, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
        {label}
      </span>
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          gap: tokens.spaceSm,
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        {children}
      </div>
    </div>
  );
}

export function Hint({ children }: { children: ReactNode }): ReactElement {
  return <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>{children}</span>;
}

/** 实测事实的标签摆法：路径长就让它折行，不裁掉业主要看的那串字符。 */
export function Chip({ children, style }: { children: ReactNode; style?: CSSProperties }): ReactElement {
  return <span style={{ ...mixins.chip(), fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, ...style }}>{children}</span>;
}

/** 一组带一句话说明的单选项（冲突裁决与落位方式共用）。 */
export function ChoiceRow<T extends string>({
  value,
  labels,
  hints,
  onPick,
}: {
  value: T | undefined;
  labels: Record<T, string>;
  hints: Record<T, string>;
  onPick: (key: T) => void;
}): ReactElement {
  const keys = Object.keys(labels) as T[];
  return (
    <Radio.Group
      value={value}
      onChange={(event) => {
        onPick(event.target.value as T);
      }}
      style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}
    >
      {keys.map((key) => (
        <Radio key={key} value={key}>
          {`${labels[key]}——${hints[key]}`}
        </Radio>
      ))}
    </Radio.Group>
  );
}
