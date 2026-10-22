/** 剧空间壳（W3·档3 结构手术 §3.2-1）：单路由 /drama/:id，两块内容上下堆叠。
 *
 * 阶段条是纯锚点：?focus= 由 StageBar/入口路径携带（analysis/intake → 分析区块，
 * planning/export → 出片区块内部锚由 useFocusScroll 接管），滚动监听把「当前段」
 * 归到真实滚动位置——①④ 可达性问题由构造消失（旧双路由把 ①②③④ 切歪）。
 * 剧找不到时横幅压顶但区块照渲染：壳是加法，不替域页做「渲染与否」的决定。
 */
import { Alert, Button } from 'antd';
import { useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { tokens } from '../../styles/theme';
import { StageBar } from '../stages/StageBar';
import { type StageKey } from '../stages/stageState';
import { useDramaFacts } from './useDramaFacts';

export function DramaShell({
  analysis,
  produce,
}: {
  analysis: ReactNode;
  produce: ReactNode;
}): ReactElement {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const id = projectId ?? '';
  const { state } = useDramaFacts(id);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [current, setCurrent] = useState<StageKey>('analysis');

  // focus 锚点：analysis/intake → 分析区块顶；planning/export → 出片区块内部的
  // useFocusScroll 自管（它读同一 query），这里只负责滚到区块骨架。
  const focus = searchParams.get('focus');
  useEffect(() => {
    if (focus !== 'analysis' && focus !== 'intake') return;
    document.getElementById('drama-section-analysis')?.scrollIntoView({ block: 'start' });
  }, [focus]);

  // 滚动监听 → current（§3.2-1：current 由实际滚动区块决定，不由路由后缀）
  const onScroll = (): void => {
    const container = containerRef.current;
    if (container === null) return;
    const boundary = container.getBoundingClientRect().top + 96;
    let best: StageKey = 'analysis';
    const production = document.getElementById('drama-section-produce');
    if (production !== null && production.getBoundingClientRect().top <= boundary) {
      best = 'planning';
    }
    setCurrent(best);
  };

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
      <div
        ref={containerRef}
        onScroll={onScroll}
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: tokens.space2xl }}
      >
        <section id="drama-section-analysis" style={{ display: 'flex', flexDirection: 'column' }}>
          {analysis}
        </section>
        <section id="drama-section-produce" style={{ display: 'flex', flexDirection: 'column' }}>
          {produce}
        </section>
      </div>
    </div>
  );
}
