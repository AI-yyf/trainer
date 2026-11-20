export const DEFAULT_TYPING_QUIET_WINDOW_MS = 15_000;

/**
 * Tracks active typing bursts so proactive coaching nudges yield while the
 * learner is mid-edit or within a short quiet cooldown window.
 */
export class CodingGapTracker {
  private lastEditAtMs: number | null = null;

  constructor(
    private readonly quietWindowMs: number = DEFAULT_TYPING_QUIET_WINDOW_MS,
    private readonly now: () => number = () => Date.now(),
  ) {}

  recordEdit(atMs: number = this.now()): void {
    this.lastEditAtMs = atMs;
  }

  isActivelyTyping(atMs: number = this.now()): boolean {
    if (this.lastEditAtMs === null) {
      return false;
    }
    return atMs - this.lastEditAtMs < this.quietWindowMs;
  }

  quietDurationMs(atMs: number = this.now()): number | null {
    if (this.lastEditAtMs === null) {
      return null;
    }
    return Math.max(0, atMs - this.lastEditAtMs);
  }

  reset(): void {
    this.lastEditAtMs = null;
  }
}
