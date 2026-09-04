/**
 * DramaClip RPC 协议类型（TS 侧）。
 *
 * 唯一真相源是 ../schemas/*.json —— 任何变更先改 schema 再同步本文件
 * （CI 契约测试校验 METHOD_NAMES 与 schema x-methods 集合相等）。
 * 规范全文：docs/03-IPC协议规范.md
 */

export type JsonRpcVersion = '2.0';

export interface RpcError {
  readonly code: number;
  readonly message: string;
  readonly data?: unknown;
}

export type MethodName = (typeof METHOD_NAMES)[number];

export interface RpcRequest {
  readonly jsonrpc: JsonRpcVersion;
  readonly id: string;
  readonly method: MethodName;
  readonly params?: Readonly<Record<string, unknown>>;
}

export interface RpcResponse {
  readonly jsonrpc: JsonRpcVersion;
  readonly id: string | null;
  readonly result?: unknown;
  readonly error?: RpcError;
}

export type NotificationName = (typeof NOTIFICATION_NAMES)[number];

export interface RpcNotification {
  readonly jsonrpc: JsonRpcVersion;
  readonly method: NotificationName;
  readonly params?: Readonly<Record<string, unknown>>;
}

/** system.ping 返回体 */
export interface PingResult {
  readonly service_version: string;
  readonly protocol_version: number;
}

/** system.health 返回体（扩展字段按需出现） */
export interface HealthResult {
  readonly status: string;
  readonly uptime_s: number;
  readonly gpu?: string;
  readonly vram_free_mb?: number;
  readonly disk_free_gb?: number;
  readonly models_ok?: boolean;
}

/** 主进程 → 渲染层事件（service:event 通道） */
export type ServiceEvent =
  | { readonly type: 'service-state'; readonly state: ServiceState }
  | {
      readonly type: 'notification';
      readonly method: NotificationName;
      readonly params: Record<string, unknown>;
    };

export type ServiceState = 'starting' | 'ready' | 'restarting' | 'unavailable';

export const METHOD_NAMES = ['system.ping', 'system.health', 'system.shutdown'] as const;

export const NOTIFICATION_NAMES = ['progress.update', 'log.append', 'models.download_progress'] as const;

export const PROTOCOL_VERSION = 1;
