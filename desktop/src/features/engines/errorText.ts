/** 服务端 rpc 拒绝时带 [code] 原文——原样上屏，比前端猜一句「失败」有用（§10.5：原话纪律）。 */
export function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message !== '' ? error.message : fallback;
}
