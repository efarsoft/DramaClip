/** 封面补拍涓流器：服务端 ensure_covers 单次有时间预算（8 秒收手、remaining 报欠账——
 * RPC dispatch 单线程，补拍长堵会把 system.health 一起堵死，ServiceManager 便误判
 * 服务已死、杀进程重启），欠账在渲染层分轮续拍。
 *
 * 进展纪律：remaining>0 且本轮 generated>0 才约下一轮——无进展说明剩下的全是
 * 死路径（外置盘离线/源文件被删）或截帧必败，无限重试不配；失败说一次现象即可。
 * cancel()（返回值）在卸载时掐掉定时器与迟到回调。
 */

export interface CoverBackfillResult {
  readonly generated: number;
  readonly remaining?: number;
}

export interface CoverBackfillOptions {
  readonly onFailure?: () => void;
  /** 轮数上限：防服务端账目异常（永远报进展）时渲染层陪跑无穷。 */
  readonly maxRounds?: number;
  readonly delayMs?: number;
}

export function scheduleCoverBackfill(
  call: () => Promise<CoverBackfillResult>,
  onProgress: () => void,
  options: CoverBackfillOptions = {},
): () => void {
  const maxRounds = options.maxRounds ?? 40;
  const delayMs = options.delayMs ?? 1500;
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const run = (round: number): void => {
    void call()
      .then((result) => {
        if (cancelled) return;
        onProgress();
        const remaining = result.remaining ?? 0;
        if (remaining > 0 && result.generated > 0 && round + 1 < maxRounds) {
          timer = setTimeout(() => {
            run(round + 1);
          }, delayMs);
        }
      })
      .catch(() => {
        if (!cancelled) options.onFailure?.();
      });
  };
  run(0);
  return () => {
    cancelled = true;
    if (timer !== undefined) clearTimeout(timer);
  };
}
