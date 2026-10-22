/** 工作台顶部：返回/项目信息/转写档位/批量操作/导出转写 + 横向步骤导航。 */
import { Button, Tag } from 'antd';
import { DownloadOutlined, LeftOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import type { TranscribeTier } from './analysisView';
import { TierPicker } from './TierPicker';

interface HeaderProps {
  project: Project | null;
  total: number;
  doneCount: number;
  running: boolean;
  progressPercent: number;
  /** 已选集数与 canStart（规格 §1.4）：勾 0 集点「批量分析」是静默 no-op——按钮禁用 + 回声。 */
  selectedCount: number;
  canStart: boolean;
  tier: TranscribeTier;
  onTierChange: (next: TranscribeTier) => void;
  onBatchAnalyze: () => void;
  onCancel: () => void;
  onExportTranscripts: () => void;
}

export function WorkbenchHeader({
  project,
  total,
  doneCount,
  running,
  progressPercent,
  selectedCount,
  canStart,
  tier,
  onTierChange,
  onBatchAnalyze,
  onCancel,
  onExportTranscripts,
}: HeaderProps): React.ReactElement {
  const navigate = useNavigate();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, flexWrap: 'wrap' }}>
        <Button size="small" icon={<LeftOutlined />} onClick={() => { void navigate('/dramas'); }}>
          项目
        </Button>
        <h1 style={PAGE_TITLE}>{project?.name ?? '…'}</h1>
        <Tag color="blue">共 <span style={NUM}>{String(total)}</span> 集</Tag>
        <Tag color={doneCount === total && total > 0 ? 'success' : 'processing'}>
          已分析 <span style={NUM}>{String(doneCount)}/{String(total)}</span>
        </Tag>
        {running && (
          <span style={{ ...TEXT_META, color: tokens.colorInfo }}>
            分析中 <span style={NUM}>{String(Math.round(progressPercent))}%</span>
          </span>
        )}
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
          <Button size="small" icon={<DownloadOutlined />} disabled={doneCount === 0} onClick={onExportTranscripts}>
            导出转写
          </Button>
          <TierPicker tier={tier} onTierChange={onTierChange} disabled={running} />
          {running ? (
            <Button size="small" danger onClick={onCancel}>
              取消分析
            </Button>
          ) : (
            <>
              <span style={{ ...TEXT_META, color: tokens.textTertiary }}>
                已选 <span style={NUM}>{String(selectedCount)}/{String(total)}</span> 集
              </span>
              <Button size="small" disabled={!canStart} onClick={onBatchAnalyze}>
                {tier === 'recommended' ? '预筛后精转推荐集' : '批量分析所选'}
              </Button>
            </>
          )}
        </span>
      </div>
    </div>
  );
}

/** 项目名：sectionTitle 档（20px/600）——工作台头部是工具栏语义（small 按钮与小徽标并排），
 * 页面主标题档（28px）在这里断层突兀（真机业主反馈）；仍高于下方区块标题一档。 */
const PAGE_TITLE = {
  margin: 0,
  fontSize: tokens.text.sectionTitle.size,
  lineHeight: tokens.text.sectionTitle.leading,
  fontWeight: tokens.text.sectionTitle.weight,
  color: tokens.textPrimary,
} as const;

const TEXT_META = {
  fontSize: tokens.text.meta.size,
  lineHeight: tokens.text.meta.leading,
} as const;

/** 计数与百分比的数字位（§1.3）：只包数字，中文留给界面字体。 */
const NUM = { fontFamily: tokens.fontFamilyMono, fontVariantNumeric: 'tabular-nums' } as const;
