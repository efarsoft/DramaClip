/** 作业进度条：规划和渲染共用，口径是「可离开页面，任务在后台继续」。 */
import { Progress } from 'antd';
import { tokens } from '../../styles/theme';

export function StageProgress({ percent, stageText }: { percent: number; stageText: string }) {
  return (
    <div style={{ marginTop: tokens.spaceLg }}>
      <Progress percent={Math.round(percent)} status="active" />
      <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary, marginTop: tokens.spaceSm }}>
        {stageText === '' ? '排队中' : stageText} · 可离开本页面，任务在后台继续
      </div>
    </div>
  );
}
