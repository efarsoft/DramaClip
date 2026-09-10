import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';

/** 区块标题：渐变竖条 + 文字（工作台统一节标题）。 */
export function SectionTitle({ children }: { children: string }): ReactElement {
  return (
    <h3
      style={{
        margin: '0 0 12px',
        fontSize: tokens.fontTitle,
        fontWeight: 600,
        color: tokens.textPrimary,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span style={{ width: 3, height: 14, borderRadius: tokens.radiusDot, background: tokens.gradientAccent }} />
      {children}
    </h3>
  );
}
