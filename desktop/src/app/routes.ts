/** 路由清单：与 navItems.ts 一起构成信息架构的两份数据真相源。 */

export const TOP_LEVEL_ROUTES = ['/', '/projects', '/works', '/engines', '/settings', '/about'] as const;

export const DETAIL_ROUTES = [
  '/projects/:projectId/analysis',
  '/projects/:projectId/produce',
  '/engines/:tab',
] as const;

export const LEGACY_REDIRECTS: Readonly<Record<string, string>> = {
  '/models': '/engines',
};

export const LEGACY_PARAM_REDIRECTS: readonly { from: string; to: string }[] = [
  { from: '/models/:tab', to: '/engines/:tab' },
];

export function dramaEntryPath(projectId: string): string {
  return `/projects/${projectId}/analysis`;
}

export function dramaProducePath(projectId: string): string {
  return `/projects/${projectId}/produce`;
}
