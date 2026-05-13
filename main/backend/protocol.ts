/**
 * JSON-RPC 协议编解码
 */

export interface JsonRpcRequest {
  jsonrpc: '2.0';
  method: string;
  params?: Record<string, unknown>;
  id: number | string;
}

export interface JsonRpcResponse {
  jsonrpc: '2.0';
  result?: unknown;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
  id: number | string;
}

export interface JsonRpcNotification {
  jsonrpc: '2.0';
  method: string;
  params?: Record<string, unknown>;
}

export class JSONRPCProtocol {
  encodeRequest(method: string, params?: Record<string, unknown>, id?: number): string {
    const request: JsonRpcRequest = {
      jsonrpc: '2.0',
      method,
      id: id ?? Date.now(),
    };

    if (params) {
      request.params = params;
    }

    return JSON.stringify(request);
  }

  encodeResponse(id: number | string, result: unknown): string {
    const response: JsonRpcResponse = {
      jsonrpc: '2.0',
      result,
      id,
    };
    return JSON.stringify(response);
  }

  encodeError(id: number | string, code: number, message: string, data?: unknown): string {
    const response: JsonRpcResponse = {
      jsonrpc: '2.0',
      error: { code, message, data },
      id,
    };
    return JSON.stringify(response);
  }

  decodeMessage(data: string): JsonRpcRequest | JsonRpcResponse | JsonRpcNotification | null {
    try {
      const parsed = JSON.parse(data);

      if (parsed.jsonrpc !== '2.0') {
        return null;
      }

      // 通知（无 id）或请求（有 id）
      if (parsed.method) {
        return parsed as JsonRpcRequest | JsonRpcNotification;
      }

      // 响应
      return parsed as JsonRpcResponse;
    } catch {
      return null;
    }
  }

  isRequest(obj: unknown): obj is JsonRpcRequest {
    return (
      typeof obj === 'object' &&
      obj !== null &&
      (obj as JsonRpcRequest).jsonrpc === '2.0' &&
      typeof (obj as JsonRpcRequest).method === 'string' &&
      'id' in obj
    );
  }

  isResponse(obj: unknown): obj is JsonRpcResponse {
    return (
      typeof obj === 'object' &&
      obj !== null &&
      (obj as JsonRpcResponse).jsonrpc === '2.0' &&
      'id' in obj &&
      ('result' in obj || 'error' in obj)
    );
  }

  isNotification(obj: unknown): obj is JsonRpcNotification {
    return (
      typeof obj === 'object' &&
      obj !== null &&
      (obj as JsonRpcNotification).jsonrpc === '2.0' &&
      typeof (obj as JsonRpcNotification).method === 'string' &&
      !('id' in obj)
    );
  }
}

// 错误码定义
export const JSON_RPC_ERROR_CODES = {
  // 系统级错误 (-32000 ~ -32099)
  INTERNAL_ERROR: -32000,
  BACKEND_NOT_READY: -32001,
  FILE_NOT_FOUND: -32002,
  PERMISSION_DENIED: -32003,

  // 项目错误 (-32100 ~ -32199)
  PROJECT_NOT_FOUND: -32101,
  PROJECT_ALREADY_EXISTS: -32102,

  // 分析错误 (-32200 ~ -32299)
  ASR_FAILED: -32201,
  UNSUPPORTED_VIDEO_FORMAT: -32202,

  // 剪辑错误 (-32300 ~ -32399)
  INSUFFICIENT_HIGHLIGHTS: -32301,
  TTS_SYNTHESIS_FAILED: -32302,

  // 导出错误 (-32400 ~ -32499)
  FFMPEG_EXECUTION_FAILED: -32401,
  INSUFFICIENT_DISK_SPACE: -32402,

  // JSON-RPC 标准错误
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_RPC_ERROR: -32603,
} as const;
