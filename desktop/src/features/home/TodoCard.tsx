import { Alert, Card } from 'antd';
import { useMemo } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

export interface TodoItem {
  readonly key: string;
  readonly text: string;
  readonly severity: 'error' | 'warning' | 'info';
}

/** 工作台待办提醒（docs/desktop/03 §7.1 区块三右列）：由系统状态派生，无独立后端概念。 */
export function useTodos(
  models: ModelInfo[] | null,
  llmConfigured: boolean,
  failedJobs: number,
  serviceDown: boolean,
): TodoItem[] {
  return useMemo(() => {
    const items: TodoItem[] = [];
    if (serviceDown) {
      items.push({ key: 'svc', text: 'Python 服务未运行，功能不可用', severity: 'error' });
    }
    if (failedJobs > 0) {
      items.push({
        key: 'failed',
        text: `有 ${String(failedJobs)} 个任务失败，请到对应页面重试`,
        severity: 'error',
      });
    }
    const missing = (models ?? []).filter(
      (m) => m.required && m.status !== 'installed',
    );
    if (missing.length > 0) {
      items.push({
        key: 'models',
        text: `推荐模型未安装：${missing.map((m) => m.name).join('、')}（模型管理页可下载或手动导入）`,
        severity: 'warning',
      });
    }
    if (!llmConfigured) {
      items.push({
        key: 'llm',
        text: 'LLM 未配置：文案将使用关键词降级（系统设置可切换）',
        severity: 'info',
      });
    }
    return items;
  }, [models, llmConfigured, failedJobs, serviceDown]);
}

/** 待办提醒卡片（HomePage 右列）。 */
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
