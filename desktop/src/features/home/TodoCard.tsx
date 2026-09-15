import { Alert, Button, Card } from 'antd';
import { useNavigate } from 'react-router-dom';
import { restartService } from '../../services/client';
import { tokens } from '../../styles/theme';
import type { TodoItem } from './todos';

/** 待办卡片：每条待办附可执行动作（导航或重启服务）。 */
export function TodoCard({ items }: { items: TodoItem[] }) {
  const navigate = useNavigate();
  if (items.length === 0) {
    return (
      <Card size="small">
        <div style={{ textAlign: 'center', color: tokens.textTertiary, padding: 8 }}>暂无待办事项</div>
      </Card>
    );
  }
  return (
    <Card size="small">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map((item) => (
          <Alert
            key={item.key}
            type={item.severity}
            showIcon
            title={item.text}
            description={item.detail}
            style={{ padding: '6px 12px' }}
            action={
              item.action && (
                <Button
                  size="small"
                  danger={item.severity === 'error'}
                  onClick={() => {
                    if (item.action?.kind === 'navigate' && item.action.path) void navigate(item.action.path);
                    else void restartService();
                  }}
                >
                  {item.action.label}
                </Button>
              )
            }
          />
        ))}
      </div>
    </Card>
  );
}
