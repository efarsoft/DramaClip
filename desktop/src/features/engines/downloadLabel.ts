/** 下载进度的上屏文案（进度三件套，§10.6）：百分比 + 速度 + ETA；估不出 ETA 显示「—」，不瞎猜。 */
import type { ModelDownloadState } from '../../stores/ui';

export function downloadingLabel(download: ModelDownloadState): string {
  const speed = download.speed !== '' ? ` · ${download.speed}` : '';
  const eta = download.eta !== '' ? `剩 ${download.eta}` : '剩 —';
  return `下载中 ${String(Math.floor(download.percent))}%${speed} · ${eta}`;
}
