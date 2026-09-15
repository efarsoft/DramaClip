/** 导轨清单：全站信息架构的唯一真相源。 */
import type { ComponentType, CSSProperties } from 'react';
import {
  CloudServerOutlined,
  DashboardOutlined,
  FolderOutlined,
  InfoOutlined,
  PlaySquareOutlined,
  SettingOutlined,
} from '@ant-design/icons';

export type NavGroup = 'loop' | 'config';

export interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly icon: ComponentType<{ style?: CSSProperties }>;
  readonly group: NavGroup;
}

export const NAV_GROUPS: readonly NavGroup[] = ['loop', 'config'];

export const NAV_ITEMS: readonly NavItem[] = [
  { path: '/', label: '工作台', icon: DashboardOutlined, group: 'loop' },
  { path: '/projects', label: '项目', icon: FolderOutlined, group: 'loop' },
  { path: '/works', label: '成品', icon: PlaySquareOutlined, group: 'loop' },
  { path: '/engines', label: '引擎', icon: CloudServerOutlined, group: 'config' },
  { path: '/settings', label: '设置', icon: SettingOutlined, group: 'config' },
  { path: '/about', label: '关于', icon: InfoOutlined, group: 'config' },
];

export function navByGroup(group: NavGroup): readonly NavItem[] {
  return NAV_ITEMS.filter((item) => item.group === group);
}

export function isNavActive(item: NavItem, pathname: string): boolean {
  if (item.path === '/') return pathname === '/';
  return pathname === item.path || pathname.startsWith(`${item.path}/`);
}
