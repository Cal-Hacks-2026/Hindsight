// The run log: every plan / step / diff / result / error goes to agent_events via the API.
// Writes are serialized (so the log keeps its order) and never throw: a logging
// failure must not stop a run, so it goes to stderr instead.
// The log is public (/agent/events) and carries Droid's own words, so known secrets and
// anything shaped like an API key are redacted first.
import type { EventKind, HindsightApi } from './api.ts';

const MAX_MESSAGE = 2000;
const KEY_SHAPES = [
  /sk-ant-[\w-]{16,}/g, // Anthropic
  /sb_secret_[\w-]{16,}/g, // Supabase
  /apify_api_[\w-]{16,}/g, // Apify
  /fk-[\w-]{16,}/g, // Factory
  /eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}/g, // JWTs (Supabase legacy service-role keys)
];

export function redact(text: string, secrets: string[] = []): string {
  let out = text;
  for (const secret of secrets) if (secret.length >= 8) out = out.split(secret).join('[redacted]');
  for (const shape of KEY_SHAPES) out = out.replace(shape, '[redacted]');
  return out;
}

export class RunLog {
  private chain: Promise<void> = Promise.resolve();

  constructor(
    private readonly api: Pick<HindsightApi, 'event'>,
    readonly runId: string,
    private readonly secrets: string[] = [],
  ) {}

  private write(kind: EventKind, rawMessage: string, rawPayload?: unknown): Promise<void> {
    const message = redact(rawMessage, this.secrets);
    const payload = rawPayload === undefined ? undefined : JSON.parse(redact(JSON.stringify(rawPayload), this.secrets));
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
