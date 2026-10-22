/** 路由清单：与 navItems.ts 一起构成信息架构的两份数据真相源。 */

export const TOP_LEVEL_ROUTES = ['/', '/projects', '/works', '/queue', '/tools', '/engines', '/settings', '/about'] as const;

export const DETAIL_ROUTES = [
  '/drama/:projectId',
  '/engines/:tab',
  '/works/:exportId',
] as const;

export const LEGACY_REDIRECTS: Readonly<Record<string, string>> = {
  '/models': '/engines',
};

export const LEGACY_PARAM_REDIRECTS: readonly { from: string; to: string }[] = [
  { from: '/models/:tab', to: '/engines/:tab' },
  // 剧空间合一（W3）：旧双路由重定向到 /drama/:id（focus 分流在 DramaShell 内不再需要——
  // 阶段条锚点已覆盖；旧入口直接落到页顶即可）
  { from: '/projects/:projectId/analysis', to: '/drama/:projectId' },
  { from: '/projects/:projectId/produce', to: '/drama/:projectId' },
];

export function dramaEntryPath(projectId: string): string {
  return `/drama/${projectId}?focus=analysis`;
}

export function dramaProducePath(projectId: string): string {
  return `/drama/${projectId}?focus=planning`;
}
