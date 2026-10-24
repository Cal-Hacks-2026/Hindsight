// The run log: every plan / step / diff / result / error goes to agent_events via the API.
// Writes are serialized (so the log keeps its order) and never throw: a logging
// failure must not stop a run, so it goes to stderr instead.
import type { EventKind, HindsightApi } from './api.ts';

const MAX_MESSAGE = 2000;

export class RunLog {
  private chain: Promise<void> = Promise.resolve();

  constructor(
    private readonly api: Pick<HindsightApi, 'event'>,
    readonly runId: string,
  ) {}

  private write(kind: EventKind, message: string, payload?: unknown): Promise<void> {
    const text = message.length > MAX_MESSAGE ? `${message.slice(0, MAX_MESSAGE - 1)}…` : message;
    console.log(`[${this.runId.slice(0, 8)}] ${kind}: ${text.split('\n')[0]}`);
    this.chain = this.chain.then(() =>
      this.api.event(this.runId, kind, text, payload).then(
        () => undefined,
        (e: Error) => console.error(`[${this.runId.slice(0, 8)}] could not log ${kind} event: ${e.message}`),
      ),
    );
    return this.chain;
  }

  plan = (message: string, payload?: unknown) => this.write('plan', message, payload);
  step = (message: string, payload?: unknown) => this.write('step', message, payload);
  diff = (message: string, payload?: unknown) => this.write('diff', message, payload);
  result = (message: string, payload?: unknown) => this.write('result', message, payload);
  error = (message: string, payload?: unknown) => this.write('error', message, payload);

  flush(): Promise<void> {
    return this.chain;
  }
}
