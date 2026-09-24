/** 剧管理菜单共享件（卡档/列表档同一份动作，不另做一套）：
 * MenuHandlers 词汇 + menuFor 菜单项构造。纯数据无 JSX——
 * 组件（MoreButton）另放一文件，守 react-refresh「组件文件只导出组件」。 */
import type { MenuProps } from 'antd';
import type { Project } from '@dramaclip/protocol';

export interface MenuHandlers {
  onRename: (project: Project) => void;
  onDuplicate: (project: Project) => void;
  onDelete: (project: Project) => void;
}

export function menuFor(project: Project, { onRename, onDuplicate, onDelete }: MenuHandlers): MenuProps['items'] {
  return [
    {
      key: 'rename',
      label: '重命名',
      onClick: () => {
        onRename(project);
      },
    },
    {
      key: 'duplicate',
      label: '复制',
      onClick: () => {
        onDuplicate(project);
      },
    },
    { type: 'divider' as const },
    {
      key: 'delete',
      label: '删除',
      danger: true,
      onClick: () => {
        onDelete(project);
      },
    },
  ];
}
