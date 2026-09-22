/** 工作台顶部：返回/项目信息/批量操作 + 横向步骤导航。 */
import { Button, Tag } from 'antd';
import { LeftOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { Project } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { StepsNav } from './StepsNav';

export function WorkbenchHeader({
  projectId,
  project,
  total,
  doneCount,
  running,
  progressPercent,
  onBatchAnalyze,
  onCancel,
}: {
  projectId: string;
  project: Project | null;
  total: number;
  doneCount: number;
  running: boolean;
  progressPercent: number;
  onBatchAnalyze: () => void;
  onCancel: () => void;
}): React.ReactElement {
  const navigate = useNavigate();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
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
        {running ? (
          <Button size="small" danger style={{ marginLeft: 'auto' }} onClick={onCancel}>
            取消分析
          </Button>
        ) : (
          <Button
            size="small"
            style={{ marginLeft: 'auto' }}
            disabled={total === 0}
            onClick={onBatchAnalyze}
          >
            批量分析所选
          </Button>
        )}
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
