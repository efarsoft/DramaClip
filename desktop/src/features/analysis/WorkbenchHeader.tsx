/** 工作台顶部：返回/项目信息/转写档位/批量操作/导出转写 + 横向步骤导航。 */
import { Button, Tag } from 'antd';
import { DownloadOutlined, LeftOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import type { TranscribeTier } from './analysisView';
import { StepsNav } from './StepsNav';
import { TierPicker } from './TierPicker';

interface HeaderProps {
  projectId: string;
  project: Project | null;
  total: number;
  doneCount: number;
  running: boolean;
  progressPercent: number;
  tier: TranscribeTier;
  onTierChange: (next: TranscribeTier) => void;
  onBatchAnalyze: () => void;
  onCancel: () => void;
  onExportTranscripts: () => void;
}

export function WorkbenchHeader({
  projectId,
  project,
  total,
  doneCount,
  running,
  progressPercent,
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
        <Button size="small" icon={<LeftOutlined />} onClick={() => { void navigate('/projects'); }}>
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
            <Button size="small" disabled={total === 0} onClick={onBatchAnalyze}>
              {tier === 'recommended' ? '预筛后精转推荐集' : '批量分析所选'}
            </Button>
          )}
        </span>
      </div>
      <StepsNav projectId={projectId} stepReady={doneCount > 0} />
    </div>
  );
}

/** 页标题：与 PageHeader 同一档（§1.1 唯一用处），中文走 500。 */
const PAGE_TITLE = {
  margin: 0,
  fontSize: tokens.text.pageTitle.size,
  lineHeight: tokens.text.pageTitle.leading,
  fontWeight: tokens.text.pageTitle.weight,
  color: tokens.textPrimary,
} as const;

const TEXT_META = {
  fontSize: tokens.text.meta.size,
  lineHeight: tokens.text.meta.leading,
} as const;

/** 计数与百分比的数字位（§1.3）：只包数字，中文留给界面字体。 */
const NUM = { fontFamily: tokens.fontFamilyMono } as const;
