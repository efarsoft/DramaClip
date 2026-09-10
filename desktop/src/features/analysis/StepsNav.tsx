/** 横向步骤导航：1 分析 → 2 解说文案 → 3 渲染调整 → 4 成片。 */
import { Link } from 'react-router-dom';
import { tokens } from '../../styles/theme';

interface StepSpec {
  readonly key: string;
  readonly label: string;
  readonly path?: string;
}

const STEPS: readonly StepSpec[] = [
  { key: 'analyze', label: '素材导入 & AI 分析' },
  { key: 'mode', label: '选择出片模式', path: 'produce' },
  { key: 'render', label: 'AI 编排 & 渲染', path: 'produce' },
  { key: 'export', label: '成片查看 / 导出', path: '/works' },
];

function StepDot({ index }: { index: number }): React.ReactElement {
  return (
    <span
      style={{
        width: 18,
        height: 18,
        borderRadius: tokens.fontIcon,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: tokens.fontMicro,
        marginRight: 7,
        background: index === 0 ? tokens.colorPrimary : tokens.bgElevated,
        color: index === 0 ? '#FFFFFF' : tokens.textTertiary,
      }}
    >
      {String(index + 1)}
    </span>
  );
}

export function StepsNav({ projectId, stepReady }: { projectId: string; stepReady: boolean }): React.ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center' }}>
      {STEPS.map((step, index) => {
        const unlocked = index === 0 || stepReady;
        const body = (
          <>
            <StepDot index={index} />
            {step.label}
          </>
        );
        const color = index === 0 ? tokens.colorPrimary : unlocked ? tokens.textSecondary : tokens.textTertiary;
        return (
          <span key={step.key} style={{ display: 'flex', alignItems: 'center' }}>
            {index > 0 && (
              <span
                style={{
                  width: 34,
                  height: 1,
                  margin: '0 10px',
                  background: unlocked ? tokens.colorPrimary : tokens.border,
                }}
              />
            )}
            {unlocked && step.path !== undefined ? (
              <Link
                to={step.path.startsWith('/') ? step.path : `/projects/${projectId}/produce`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  fontSize: tokens.fontBody,
                  color,
                  textDecoration: 'none',
                }}
              >
                {body}
              </Link>
            ) : (
              <span style={{ display: 'flex', alignItems: 'center', fontSize: tokens.fontBody, color }}>{body}</span>
            )}
          </span>
        );
      })}
    </div>
  );
}
