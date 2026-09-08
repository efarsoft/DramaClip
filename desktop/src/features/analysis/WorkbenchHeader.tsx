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
}: {
  projectId: string;
  project: Project | null;
  total: number;
  doneCount: number;
  running: boolean;
  progressPercent: number;
  onBatchAnalyze: () => void;
}): React.ReactElement {
  const navigate = useNavigate();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Button size="small" icon={<LeftOutlined />} onClick={() => { void navigate('/projects'); }}>
          项目
        </Button>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: tokens.textPrimary }}>
          {project?.name ?? '…'}
        </h1>
        <Tag color="blue">共 {String(total)} 集</Tag>
        <Tag color={doneCount === total && total > 0 ? 'success' : 'processing'}>
          已分析 {String(doneCount)}/{String(total)}
        </Tag>
        {running && (
          <span style={{ fontSize: 12, color: tokens.colorInfo }}>
            分析中 {String(Math.round(progressPercent))}%
          </span>
        )}
        <Button
          size="small"
          style={{ marginLeft: 'auto' }}
          disabled={running || total === 0}
          onClick={onBatchAnalyze}
        >
          批量分析所选
        </Button>
      </div>
      <StepsNav projectId={projectId} stepReady={doneCount > 0} />
    </div>
  );
}
