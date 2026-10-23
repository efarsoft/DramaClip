/** 导轨清单：全站信息架构的唯一真相源。 */
import type { ComponentType, CSSProperties } from 'react';
import {
  CloudServerOutlined,
  DashboardOutlined,
  FolderOutlined,
  InfoOutlined,
  PlaySquareOutlined,
  SettingOutlined,
  ToolOutlined,
} from '@ant-design/icons';

export type NavGroup = 'loop' | 'config';

export interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly icon: ComponentType<{ style?: CSSProperties }>;
  readonly group: NavGroup;
  /** 这些路径段前缀也让本项保持高亮。合一后的单剧详情是 `/drama/:id`，
   *  与列表项 `/dramas` 不同段名，不登记别名进详情页导轨会整条熄灭。 */
  readonly alsoActiveFor?: readonly string[];
}

export const NAV_GROUPS: readonly NavGroup[] = ['loop', 'config'];

export const NAV_ITEMS: readonly NavItem[] = [
  { path: '/', label: '工作台', icon: DashboardOutlined, group: 'loop' },
  { path: '/dramas', label: '剧库', icon: FolderOutlined, group: 'loop', alsoActiveFor: ['/drama'] },
  { path: '/works', label: '成品', icon: PlaySquareOutlined, group: 'loop' },
  { path: '/tools', label: '工具箱', icon: ToolOutlined, group: 'loop' },
  { path: '/engines', label: '引擎', icon: CloudServerOutlined, group: 'config' },
  { path: '/settings', label: '设置', icon: SettingOutlined, group: 'config' },
  { path: '/about', label: '关于', icon: InfoOutlined, group: 'config' },
];

export function navByGroup(group: NavGroup): readonly NavItem[] {
  return NAV_ITEMS.filter((item) => item.group === group);
}

/** 前缀只按路径段边界算命中：`/works` 不认 `/works-archive`。 */
function hitPrefix(prefix: string, pathname: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function isNavActive(item: NavItem, pathname: string): boolean {
  if (item.path === '/') return pathname === '/';
  if (hitPrefix(item.path, pathname)) return true;
  return (item.alsoActiveFor ?? []).some((prefix) => hitPrefix(prefix, pathname));
}
