import { Alert, Card } from 'antd';
import { tokens } from '../../styles/theme';
import type { TodoItem } from './useTodos';

/** 待办提醒卡片（HomePage）。 */
export function TodoCard({ items }: { items: TodoItem[] }) {
  if (items.length === 0) {
    return (
      <Card size="small">
        <div style={{ textAlign: 'center', color: tokens.textTertiary, padding: 8 }}>
          暂无待办事项
        </div>
      </Card>
    );
  }
  return (
    <Card size="small">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map((item) => (
          <Alert
            key={item.key}
            type={item.severity === 'info' ? 'info' : item.severity}
            showIcon
            title={item.text}
            style={{ padding: '6px 12px' }}
          />
        ))}
      </div>
    </Card>
  );
}
