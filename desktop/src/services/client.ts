/** 渲染层唯一 IPC 出口（docs/desktop/01 §4）。组件禁止直接调 window.dramaclip。 */
import type { DramaClipBridge, HealthResult, PingResult, ServiceEvent } from '@dramaclip/protocol';

function bridge(): DramaClipBridge {
  return window.dramaclip;
}

export function rpc<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  return bridge().rpc(method, params) as Promise<T>;
}

export function appVersion(): Promise<string> {
  return bridge().appVersion();
}

export function restartService(): Promise<void> {
  return bridge().restartService();
}

export function onServiceEvent(callback: (event: ServiceEvent) => void): () => void {
  return bridge().onServiceEvent(callback);
}

export const systemApi = {
  ping: (): Promise<PingResult> => rpc<PingResult>('system.ping'),
  health: (): Promise<HealthResult> => rpc<HealthResult>('system.health'),
} as const;
