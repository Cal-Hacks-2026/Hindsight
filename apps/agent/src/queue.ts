// Runs execute one at a time (one Droid session, one writer of extractors/).
// A request identical to one already waiting (same campus, trigger, profile) folds
// into it, and a manual request folds into a manual run for that campus that is running
// or started within the cooldown, so repeated "Run now" clicks cost one run, not many.
import type { Job } from './prompt.ts';

export class QueueFull extends Error {}

export class RunQueue {
  private readonly pending: Job[] = [];
  private active: Job | undefined;
  private drained: Promise<void> = Promise.resolve();
  private readonly lastManual = new Map<string, { runId: string; startedAt: number }>();

  constructor(
    private readonly execute: (job: Job) => Promise<void>,
    private readonly limit: number,
    private readonly onQueued: (job: Job, position: number) => void = () => undefined,
    private readonly manualCooldownMs = 0,
    private readonly now: () => number = Date.now,
  ) {}

  /** Returns the run id that will carry this request and its place in line (0 = starting now). */
  enqueue(job: Job): { runId: string; position: number } {
    const same = this.pending.findIndex(
      (p) => p.campus === job.campus && p.trigger === job.trigger && p.profileId === job.profileId,
    );
    if (same >= 0) return { runId: this.pending[same].runId, position: same + 1 };
    const recent = job.trigger === 'manual' ? this.lastManual.get(job.campus) : undefined;
    if (recent && (recent.runId === this.active?.runId || this.now() - recent.startedAt < this.manualCooldownMs)) {
      return { runId: recent.runId, position: 0 };
    }
    if (this.pending.length >= this.limit) throw new QueueFull(`queue is full (${this.limit} waiting)`);
    this.pending.push(job);
    const position = this.active ? this.pending.length : 0;
    this.onQueued(job, position);
    if (!this.active) this.drained = this.drain();
    return { runId: job.runId, position };
  }

  status(): { running: string | null; pending: number } {
    return { running: this.active?.runId ?? null, pending: this.pending.length };
  }

  /** Resolves once nothing is running or waiting. */
  idle(): Promise<void> {
    return this.drained;
  }

  private async drain(): Promise<void> {
    while ((this.active = this.pending.shift())) {
      if (this.active.trigger === 'manual') {
        this.lastManual.set(this.active.campus, { runId: this.active.runId, startedAt: this.now() });
      }
      try {
        await this.execute(this.active);
      } catch (e) {
        console.error(`run ${this.active.runId} crashed: ${(e as Error).message}`);
      }
    }
  }
}

/** At most `limit` uses in any rolling hour. */
export class HourlyBudget {
  private readonly uses: number[] = [];

  constructor(
    private readonly limit: number,
    private readonly now: () => number = Date.now,
  ) {}

  take(): boolean {
    const t = this.now();
    while (this.uses.length && t - this.uses[0] >= 3_600_000) this.uses.shift();
    if (this.uses.length >= this.limit) return false;
    this.uses.push(t);
    return true;
  }
}
