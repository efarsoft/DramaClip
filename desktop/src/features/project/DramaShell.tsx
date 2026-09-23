/** 剧空间壳（卷三意见 06）：布局 + 大阶段条；第二刀完成任务账状态提升。
 *
 * 壳 = 顶部大阶段条 + 子区滚动容器。用组合而不是嵌套路由：router.tsx 的 path
 * 字面量与 IA 登记表（iaContract）零漂移。任务账来自全局 stores/jobs（JobsFeed
 * 唯一轮询点），壳不自拉 jobs.list——阶段灯随快照实时点亮。
 * 高度链要显式接管：分析页根部 height:100% 需要确定高度的父级，出片页长内容
 * 在壳内滚动（main 不再二次滚动）——壳不给高度链，域页会被压扁。
 * 剧找不到时横幅压顶但 children 照渲染：壳是加法，不替域页做「渲染与否」的决定，
 * 账本暂时取不到也不连坐白屏。
 */
import { Alert, Button } from 'antd';
import type { ReactElement, ReactNode } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { tokens } from '../../styles/theme';
import { StageBar } from '../stages/StageBar';
import type { StageKey } from '../stages/stageState';
import { useDramaFacts } from './useDramaFacts';

export function DramaShell({ children }: { children: ReactNode }): ReactElement {
  const { projectId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const id = projectId ?? '';
  const { state } = useDramaFacts(id);
  // 路由决定「现在在哪一段」：出片页覆盖③规划与④出片，高亮取③（进入出片先面对规划）
  const current: StageKey = location.pathname.endsWith('/produce') ? 'planning' : 'analysis';

  return (
    <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      {state.kind === 'missing' && (
        <Alert
          type="warning"
          showIcon
          title={`这部剧对不上账：${state.reason}`}
          description="下方页面照常渲染，用它自己的数据口径说话；剧库有实时列表。"
          action={
            <Button
              size="small"
              onClick={() => {
                void navigate('/projects');
              }}
            >
              回剧库
            </Button>
          }
        />
      )}
      {state.kind !== 'missing' && (
        <StageBar
          projectId={id}
          stages={state.kind === 'ok' ? state.stages : null}
          note={state.kind === 'ok' ? state.note : null}
          factsError={state.kind === 'ok' ? state.factsError : null}
          current={current}
          activeStage={state.kind === 'ok' ? state.activeStage : null}
          activeProgress={state.kind === 'ok' ? state.activeProgress : null}
        />
      )}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>{children}</div>
    </div>
  );
}
