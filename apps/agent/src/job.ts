// One Droid run: start a scoped session, hand it the job, and log what happens.
import {
  AutonomyLevel,
  DroidMessageType,
  OutputFormatType,
  createSession,
  type CreateSessionOptions,
  type DroidMessage,
} from '@factory/droid-sdk/node';

import type { HindsightApi } from './api.ts';
import type { Config } from './config.ts';
import { changesSince, snapshot } from './diffs.ts';
import { RunLog } from './events.ts';
import { EditScope, MCP_SERVER } from './policy.ts';
import { RESULT_SCHEMA, buildPrompt, type Job } from './prompt.ts';
import { hindsightTools, type JobState } from './tools.ts';

export interface SessionLike {
  stream(prompt: string, options?: { outputFormat?: unknown; abortSignal?: AbortSignal }): AsyncIterable<DroidMessage>;
  close(): Promise<void>;
}

export type StartSession = (options: CreateSessionOptions) => Promise<SessionLike>;

export interface JobDeps {
  config: Pick<Config, 'factoryApiKey' | 'droidPath' | 'extractorsDir' | 'modelId' | 'maxPatchesPerRun' | 'runTimeoutMs'>;
  api: Pick<HindsightApi, 'scan' | 'rescan' | 'raw' | 'rank' | 'alerts' | 'event'>;
  startSession?: StartSession;
  secrets?: string[]; // redacted from every event, on top of RunLog's key patterns
}

function short(value: unknown, max = 300): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function describeToolCall(name: string, input: unknown): string {
  const i = (input ?? {}) as Record<string, unknown>;
  const target = i.file_path ?? i.path ?? i.pattern ?? i.patterns ?? '';
  return `Droid used ${name}${target ? ` on ${short(target, 120)}` : ''}`;
}

function todos(input: unknown): string[] {
  const list = (input as { todos?: unknown })?.todos;
  if (typeof list === 'string') return list.split('\n').map((l) => l.trim()).filter(Boolean);
  if (Array.isArray(list)) return list.map((t) => (typeof t === 'string' ? t : String((t as { content?: unknown }).content ?? short(t))));
  return [];
}

/** The final structured summary also arrives as assistant text; the result event carries it. */
function isStructuredEcho(text: string): boolean {
  try {
    const value = JSON.parse(text);
    return typeof value === 'object' && value !== null && 'summary' in value;
  } catch {
    return false;
  }
}

export async function runJob(job: Job, deps: JobDeps): Promise<void> {
  const { config, api } = deps;
  const startSession = deps.startSession ?? (createSession as unknown as StartSession);
  const log = new RunLog(api, job.runId, [config.factoryApiKey, ...(deps.secrets ?? [])]);
  const scope = new EditScope(config.extractorsDir, config.maxPatchesPerRun);
  const state: JobState = { everFailing: new Set() };
  const before = await snapshot(config.extractorsDir);
  const patched = new Set<string>();
  const timeout = AbortSignal.timeout(config.runTimeoutMs);

  async function recordDiffs(): Promise<void> {
    for (const d of await changesSince(before, config.extractorsDir)) {
      patched.add(d.file);
      await log.diff(`Droid patched ${d.file} (+${d.added} −${d.removed})`, { file: d.file, diff: d.diff, added: d.added, removed: d.removed });
    }
  }

  // No profile id here: it acts as a bearer token and this log is public.
  await log.step(`Run started: ${job.trigger === 'profile_created' ? 'new profile' : `${job.trigger} scan`} for ${job.campus}`, {
    trigger: job.trigger,
    campus: job.campus,
  });

  let session: SessionLike | undefined;
  try {
    session = await startSession({
      cwd: config.extractorsDir,
      apiKey: config.factoryApiKey,
      execPath: config.droidPath,
      modelId: config.modelId,
      autonomyLevel: AutonomyLevel.Off, // every call with a side effect goes through permissionHandler
      disableBuiltinSkills: true,
      mcpServers: [hindsightTools(job, api, log, scope, state)],
      permissionHandler: async (request) => {
        const decision = scope.decide(request);
        if (!decision.denied.length) return { selectedOption: decision.outcome };
        await log.step(`Blocked: ${decision.denied.join('; ')}`, { denied: decision.denied });
        return { selectedOption: decision.outcome, comment: `Blocked by Hindsight policy: ${decision.denied.join('; ')}` };
      },
      askUserHandler: () => ({ cancelled: true, answers: [] }), // nobody is watching a scheduled run
      abortSignal: timeout,
    });
    for await (const message of session.stream(buildPrompt(job), {
      outputFormat: { type: OutputFormatType.JsonSchema, schema: RESULT_SCHEMA },
      abortSignal: timeout,
    })) {
      switch (message.type) {
        case DroidMessageType.ToolCall:
          if (message.name === 'TodoWrite') {
            const steps = todos(message.input);
            await log.plan(steps.length ? steps.join('\n') : 'Plan updated', { todos: message.input });
          } else if (!message.name.startsWith(`${MCP_SERVER}___`)) {
            await log.step(describeToolCall(message.name, message.input));
          }
          break;
        case DroidMessageType.ToolResult:
          await recordDiffs();
          break;
        case DroidMessageType.Assistant:
          if (message.text.trim() && !isStructuredEcho(message.text)) await log.step(`Droid: ${short(message.text.trim(), 600)}`);
          break;
        case DroidMessageType.Error:
          await log.error(`Droid error: ${message.message}`);
          break;
        case DroidMessageType.Result: {
          await recordDiffs();
          const out = message.structuredOutput as { summary?: string } | undefined;
          const payload = {
            output: out ?? null,
            patched: [...patched],
            editable: scope.allowedFiles(),
            alerts_new: state.alertsNew ?? null,
            duration_ms: message.durationMs,
            token_usage: message.tokenUsage,
          };
          if (message.success) await log.result(out?.summary ?? short(message.text || 'Run finished.', 1000), payload);
          else await log.error(`Run ended: ${message.subtype}${message.error ? ` (${message.error.message})` : ''}`, payload);
          break;
        }
      }
    }
  } catch (e) {
    await log.error(timeout.aborted ? `Run stopped after ${config.runTimeoutMs / 60_000} minutes` : `Run failed: ${(e as Error).message}`);
  } finally {
    await recordDiffs().catch(() => undefined);
    await session?.close().catch(() => undefined);
    await log.flush();
  }
}

/**
 * A new profile when the hourly budget for Droid runs is spent (POST /profiles is public,
 * so profile runs must not be an unbounded way to spend credits): rank and alert for
 * that profile directly, without a Droid session.
 */
export async function runDirect(job: Job, deps: Pick<JobDeps, 'api' | 'secrets'>): Promise<void> {
  const log = new RunLog(deps.api, job.runId, deps.secrets ?? []);
  await log.step(`Run started: new profile for ${job.campus} (hourly Droid budget reached; ranking directly, no Droid session)`, {
    trigger: job.trigger,
    campus: job.campus,
  });
  try {
    const ranked = await deps.api.rank(job.campus, job.profileId);
    await log.step(`Ranked opportunities for ${ranked.profiles.length} profile(s)`, ranked);
    const alerts = await deps.api.alerts(job.campus, job.profileId);
    await log.step(`Wrote ${alerts.new} new alert(s) (${alerts.alerts.length} due in total; rule: ${alerts.rule})`, alerts);
    await log.result(`Ranked and wrote ${alerts.new} new alert(s) without Droid.`, { alerts_new: alerts.new });
  } catch (e) {
    await log.error(`Run failed: ${(e as Error).message}`);
  }
  await log.flush();
}
