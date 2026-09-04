/** 崩溃重启策略（纯状态机，docs/desktop/00 §5）：≤3 次、退避 2/4/6s、稳定 60s 清零。 */

export interface RestartDecision {
  readonly action: 'restart' | 'give-up';
  readonly delayMs: number;
}

export class RestartPolicy {
  private attempts = 0;
  private lastStartAt: number | null = null;

  constructor(
    private readonly maxAttempts = 3,
    private readonly stableMs = 60_000,
    private readonly baseDelayMs = 2_000,
    private readonly now: () => number = Date.now,
  ) {}

  /** 每次成功拉起（hello 就绪）后调用。 */
  recordStart(): void {
    this.lastStartAt = this.now();
  }

  /** 失败后决策：restart（带退避）或 give-up。稳定运行达标时清零计数。 */
  onFailure(): RestartDecision {
    if (this.lastStartAt !== null && this.now() - this.lastStartAt >= this.stableMs) {
      this.attempts = 0;
    }
    this.attempts += 1;
    if (this.attempts > this.maxAttempts) {
      return { action: 'give-up', delayMs: 0 };
    }
    return { action: 'restart', delayMs: this.baseDelayMs * this.attempts };
  }

  /** 当前连续失败次数（调试/展示用）。 */
  get attemptCount(): number {
    return this.attempts;
  }
}
