/** 轮询节奏与终态判定：出片两步（规划 / 渲染）都用同一套作业状态词。 */
export const POLL_INTERVAL_MS = 1500;

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

export const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

export function isTerminal(status: string): boolean {
  return TERMINAL.has(status);
}

/** 失败要说人话：原文为空或全空白时退回兜底，不把空白当原因显示给用户。 */
export function reasonOr(text: string | undefined, fallback: string): string {
  const trimmed = text?.trim() ?? '';
  return trimmed === '' ? fallback : trimmed;
}
