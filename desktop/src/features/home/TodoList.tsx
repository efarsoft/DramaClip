/** 今日待办：每条 = 状态点 + 一行结论 + 右侧 ghost 动作（规格 §4.1、DSS §3.1/§4.3）。
 *
 * 与被它取代的 TodoCard 的区别不是样式：旧版用 AntD Alert，只能"通知"、点不动。
 * 本版每条必须带一个可执行动作——没有落点的状态不进待办（取舍见 todos.ts 顶部注释）。
 *
 * 行结构复用 mixins.listRow，与环境就绪度行、素材列表行同构（DSS §4.3）。
 * 状态点颜色按 §3.2 色彩纪律；#FF4D4F 是钩子语义专用色，本页不得出现。
 *
 * 导航由 onNavigate 注入而不是在组件内 useNavigate：这样它能在 MemoryRouter 之外
 * 也被渲染测试，也让"点了跳哪"这条规则在 todos.ts 里可单测。
 */
import type { ReactElement } from 'react';
import { PageSection } from '../../components/layout/PageKit';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import type { TodoAction, TodoItem } from './todos';

const DOT_COLOR: Readonly<Record<TodoItem['severity'], string>> = {
  error: tokens.colorError,
  warning: tokens.colorWarning,
  info: tokens.colorInfo,
};

export function TodoList({
  items,
  onNavigate,
  onRestartService,
}: {
  items: readonly TodoItem[];
  onNavigate: (path: string) => void;
  onRestartService: () => void;
}): ReactElement | null {
  // 空数组整块不渲染：一个写着"暂无待办"的卡片是噪音，不是信息。
  if (items.length === 0) return null;
  return (
    <PageSection title="今日待办" extra={<span style={mixins.chip()}>{`${String(items.length)} 条`}</span>}>
      <div>
        {items.map((item) => (
          <TodoRow key={item.key} item={item} onNavigate={onNavigate} onRestartService={onRestartService} />
        ))}
      </div>
    </PageSection>
  );
}

function TodoRow({
  item,
  onNavigate,
  onRestartService,
}: {
  item: TodoItem;
  onNavigate: (path: string) => void;
  onRestartService: () => void;
}): ReactElement {
  return (
    <div style={{ ...mixins.listRow(), padding: `0 ${tokens.spaceLg}` }}>
      <span data-testid="severity-dot" style={mixins.statusDot(DOT_COLOR[item.severity])} />
      <span
        title={item.detail === '' ? undefined : item.detail}
        style={{
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: tokens.text.body.size,
          lineHeight: tokens.text.body.leading,
          color: tokens.textPrimary,
        }}
      >
        {item.text}
      </span>
      {item.action && (
        <GhostAction action={item.action} onNavigate={onNavigate} onRestartService={onRestartService} />
      )}
    </div>
  );
}

/** ghost = 纯文字主色（DSS §3.1）。它不是按钮层级里的 secondary，所以不用 AntD
 *  Button——"每屏 primary 至多 1 个"这条规矩靠视觉权重就能守住，不必靠组件类型。 */
function GhostAction({
  action,
  onNavigate,
  onRestartService,
}: {
  action: TodoAction;
  onNavigate: (path: string) => void;
  onRestartService: () => void;
}): ReactElement {
  const click = (): void => {
    if (action.kind === 'navigate') onNavigate(action.path ?? '');
    else onRestartService();
  };
  return (
    <button
      type="button"
      onClick={click}
      style={{
        marginLeft: 'auto',
        flexShrink: 0,
        background: 'none',
        border: 'none',
        padding: 0,
        color: tokens.colorPrimary,
        fontSize: tokens.text.meta.size,
        lineHeight: tokens.text.meta.leading,
        cursor: 'pointer',
      }}
    >
      {action.label}
    </button>
  );
}
