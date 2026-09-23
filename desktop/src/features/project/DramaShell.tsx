/** 剧空间壳（卷三意见 06 第一刀）：只管布局，不动分析/出片两个域页内部。
 *
 * 壳 = 顶部只读大阶段条 + children。用组合而不是嵌套路由：router.tsx 的 path
 * 字面量与 IA 登记表（iaContract）零漂移，域页一行未改——属主纪律：第一刀只加壳，
 * 第二刀再谈状态提升与路由嵌套。
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
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
        />
      )}
      <div>{children}</div>
    </div>
  );
}
