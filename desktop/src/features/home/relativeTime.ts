/** 相对时间：只到"几天前"这一档。
 *
 * 更细的精度对"我上次在哪部剧"这个问题没有增益，而"3 天 4 小时 12 分"这种
 * 精度会让人以为它是实时的——它不是，它只在页面挂载时算一次。
 * 负差（本机时钟被往前调过）一律收敛成"刚刚"，不输出"-5 分钟前"。
 */
export function whenLabel(visitedAtMs: number, nowMs: number): string {
  const minutes = Math.max(Math.floor((nowMs - visitedAtMs) / 60_000), 0);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${String(minutes)} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${String(hours)} 小时前`;
  return `${String(Math.floor(hours / 24))} 天前`;
}
