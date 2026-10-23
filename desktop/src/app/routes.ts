/** 路由清单：与 navItems.ts 一起构成信息架构的两份数据真相源。 */

export const TOP_LEVEL_ROUTES = ['/', '/dramas', '/works', '/tools', '/engines', '/settings', '/about'] as const;

export const DETAIL_ROUTES = [
  '/drama/:projectId',
  '/engines/:tab',
  '/works/:exportId',
] as const;

export const LEGACY_REDIRECTS: Readonly<Record<string, string>> = {
  '/models': '/engines',
  '/projects': '/dramas',
};

export const LEGACY_PARAM_REDIRECTS: readonly { from: string; to: string }[] = [
  { from: '/models/:tab', to: '/engines/:tab' },
  // 剧空间合一（W3）：旧双路由重定向到 /drama/:id（focus 分流在 DramaShell 内不再需要——
  // 阶段条锚点已覆盖；旧入口直接落到页顶即可）
  { from: '/projects/:projectId/analysis', to: '/drama/:projectId' },
  { from: '/projects/:projectId/produce', to: '/drama/:projectId' },
];

/** 剧空间合一后的详情路径唯一写法：`focus` 是区块锚点，取值见 DramaShell。
 *  各处「跳去那一页」都必须经这里拼，别处再写一遍 `/drama/…?focus=…` 就是第二处真相。 */
export function dramaFocusPath(projectId: string, focus: string): string {
  return `/drama/${projectId}?focus=${focus}`;
}

export function dramaEntryPath(projectId: string): string {
  return dramaFocusPath(projectId, 'analysis');
}

export function dramaProducePath(projectId: string): string {
  return dramaFocusPath(projectId, 'planning');
}
