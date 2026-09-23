/** 成片详情·自检四项分区：徽章三态 + 度量原文整段上屏（不截断），未检可补测、跑完可刷新。 */
import type { ReactElement } from 'react';
import { Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { SelfCheck } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { SelfCheckChip } from './WorkCard';
import { selfCheckBadges } from './worksView';

export function SelfCheckSection({
  selfcheck,
  onSelfcheck,
  onReload,
}: {
  selfcheck: SelfCheck | null | undefined;
  onSelfcheck: () => void;
  onReload: () => void;
}): ReactElement {
  const badges = selfCheckBadges(selfcheck);
  return (
    <PageSection
      title="自检四项"
      extra={
        <span style={{ display: 'flex', gap: tokens.spaceSm }}>
          <Button size="small" icon={<ReloadOutlined />} onClick={onReload}>
            刷新
          </Button>
          <Button size="small" onClick={onSelfcheck}>
            {selfcheck === null || selfcheck === undefined ? '补测此片' : '重测此片'}
          </Button>
        </span>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        {badges.map((badge) => (
          <div key={badge.key} style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
            <SelfCheckChip badge={badge} />
            <span
              style={{
                fontSize: tokens.text.meta.size,
                lineHeight: tokens.text.meta.leading,
                color: tokens.textTertiary,
              }}
            >
              {badge.detail}
            </span>
          </div>
        ))}
        <span
          style={{
            fontSize: tokens.text.badge.size,
            lineHeight: tokens.text.badge.leading,
            color: tokens.textTertiary,
          }}
        >
          {selfcheck === null || selfcheck === undefined
            ? '从未自检——「补测此片」排入自检作业，跑完点「刷新」看成绩单'
            : `测于 ${new Date(selfcheck.checked_at).toLocaleString()} · 判据与回归门禁同源（时长/配音/静音/冻结）`}
        </span>
      </div>
    </PageSection>
  );
}
