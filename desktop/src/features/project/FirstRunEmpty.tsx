/** 首启三步空态（规格 09-10 §4.2）：空库不是「这里空空如也」，是把下三步说清楚。 */
import { FolderAddOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';

const STEPS: readonly { numeral: string; title: string; desc: string }[] = [
  { numeral: '①', title: '新建项目', desc: '选中剧集所在文件夹，选好即建' },
  { numeral: '②', title: '自动扫描素材', desc: '识别剧集文件并排好集数，不用手动整理' },
  { numeral: '③', title: '分析后出片', desc: '转写与规划跑完，选方案渲染成片' },
];

export function FirstRunEmpty({ onCreate }: { onCreate: () => void }): ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: tokens.spaceXl,
        padding: `${tokens.space3xl} ${tokens.spaceLg}`,
        border: `1px dashed ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        textAlign: 'center',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        <span style={{ fontSize: tokens.text.cardTitle.size, lineHeight: tokens.text.cardTitle.leading, fontWeight: 600, color: tokens.textPrimary }}>
          还没有剧
        </span>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          三步开跑
        </span>
      </div>
      <div style={{ display: 'flex', gap: tokens.spaceXl, flexWrap: 'wrap', justifyContent: 'center' }}>
        {STEPS.map((step) => (
          <div
            key={step.title}
            style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, maxWidth: 220, alignItems: 'center' }}
          >
            <span style={{ fontSize: tokens.text.cardTitle.size, lineHeight: tokens.text.cardTitle.leading, color: tokens.colorPrimary }}>
              {step.numeral}
            </span>
            <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>
              {step.title}
            </span>
            <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
              {step.desc}
            </span>
          </div>
        ))}
      </div>
      <Button type="primary" icon={<FolderAddOutlined />} onClick={onCreate}>
        新建项目
      </Button>
    </div>
  );
}
