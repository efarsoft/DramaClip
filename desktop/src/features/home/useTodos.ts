import { useMemo } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';

export interface TodoItem {
  readonly key: string;
  readonly text: string;
  readonly severity: 'error' | 'warning' | 'info';
}

/** 工作台待办提醒：由系统状态派生，无独立后端概念（docs/desktop/03 §7.1）。 */
export function useTodos(
  models: ModelInfo[] | null,
  llmConfigured: boolean,
  serviceDown: boolean,
): TodoItem[] {
  return useMemo(() => {
    const items: TodoItem[] = [];
    if (serviceDown) {
      items.push({ key: 'svc', text: 'Python 服务不可用，功能暂不可用', severity: 'error' });
    }
    const missing = (models ?? []).filter((m) => m.required && m.status !== 'installed');
    if (missing.length > 0) {
      items.push({
        key: 'models',
        text: `推荐模型未安装：${missing.map((m) => m.name).join('、')}（引擎中心可下载或导入）`,
        severity: 'warning',
      });
    }
    if (!llmConfigured) {
      items.push({
        key: 'llm',
        text: 'LLM 未配置：文案将使用关键词降级（引擎中心可配置端点）',
        severity: 'info',
      });
    }
    return items;
  }, [models, llmConfigured, serviceDown]);
}
