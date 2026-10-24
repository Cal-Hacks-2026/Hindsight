import assert from 'node:assert/strict';
import { mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';

import { ToolConfirmationOutcome as O, ToolConfirmationType as T, type CreateSessionOptions } from '@factory/droid-sdk/node';

import type { ScanReport, SourceReport } from '../src/api.ts';
import { redact } from '../src/events.ts';
import { runDirect, runJob, type SessionLike } from '../src/job.ts';
import { buildPrompt } from '../src/prompt.ts';
import type { Job } from '../src/prompt.ts';

const RUN = '11111111-1111-4111-8111-111111111111';
const OPTIONS = [O.ProceedOnce, O.Cancel].map((value) => ({ value, label: value }));
const BROKEN = 'def extract(raw, source):\n    return [x for x in raw.get("json", {}).get("events", [])]\n';
const FIXED = 'def extract(raw, source):\n    return [x for x in raw.get("json", {}).get("items", [])]\n';

function report(localist: SourceReport['status']): ScanReport {
  const src = (source_id: string, kind: string, status: SourceReport['status']): SourceReport => ({
    source_id, kind, extractor: `${kind}.py`, status, parsed: status === 'ok' ? 3 : 0, kept: status === 'ok' ? 3 : 0,
  });
  return {
    apify_run_id: 'apifyRun1', stored: 9, skipped: {},
    sources: [src('sjsu-events-ai-tech', 'localist', localist), src('sjsu-devpost', 'devpost', 'ok'), src('sjsu-club-events', 'campusgroups_rss', 'fetch_failed')],
  };
}

function fakeApi() {
  const events: { kind: string; message: string; payload?: unknown }[] = [];
  const calls: string[] = [];
  return {
    events,
    calls,
    api: {
      scan: async () => (calls.push('scan'), report('empty')),
      rescan: async (_c: string, id: string) => (calls.push(`rescan:${id}`), report('ok')),
      raw: async (_id: string, source: string) => (calls.push(`raw:${source}`), { items: [{ json: { items: [] } }] }),
      rank: async () => (calls.push('rank'), { profiles: [{ ranked: 5, top: [] }] }),
      alerts: async () => (calls.push('alerts'), { alerts: [], new: 2, rule: 'top 5' }),
      event: async (runId: string, kind: string, message: string, payload?: unknown) => {
        assert.equal(runId, RUN);
        events.push({ kind, message, payload });
        return { ok: true as const };
      },
    },
  };
}

/** A scripted stand-in for Droid: asks permission like the CLI does, calls our MCP tools, edits a file. */
function fakeDroid(dir: string, opts: { seen?: CreateSessionOptions[] } = {}) {
  return async (options: CreateSessionOptions): Promise<SessionLike> => {
    opts.seen?.push(options);
    const server = options.mcpServers?.[0] as unknown as { name: string; tools: { name: string; handler: (i: unknown) => Promise<string> }[] };
    const ask = (details: unknown) =>
      Promise.resolve(options.permissionHandler!({ options: OPTIONS, toolUses: [{ details }] } as never)).then(
        (r) => (typeof r === 'object' ? (r as { selectedOption: O }).selectedOption : r),
      );
    const mcp = async (name: string, input: unknown = {}) => {
      assert.equal(await ask({ type: T.McpTool, toolName: name, serverName: server.name, actualToolName: name }), O.ProceedOnce);
      return server.tools.find((t) => t.name === name)!.handler(input);
    };
    const file = path.join(dir, 'localist.py');
    return {
      close: async () => undefined,
      async *stream() {
        yield { type: 'tool_call', name: 'TodoWrite', toolUseId: 't1', input: { todos: [{ content: 'Scan sjsu' }, { content: 'Repair failing extractors' }] } } as never;
        const scanned = await mcp('scan_campus');
        assert.match(scanned, /Editable files now: localist\.py/);
        assert.match(await mcp('scan_campus'), /Already scanned/);
        yield { type: 'tool_result', toolUseId: 't2', toolName: 'hindsight___scan_campus', content: scanned, isError: false } as never;
        assert.match(await mcp('get_source_raw', { source_id: 'sjsu-events-ai-tech' }), /^UNTRUSTED PAGE DATA/);
        yield { type: 'tool_call', name: 'Read', toolUseId: 't3', input: { file_path: file } } as never;
        // Blocked: a shell command, and an edit to an extractor that isn't failing.
        assert.equal(await ask({ type: T.Execute, command: 'curl', fullCommand: 'curl https://evil.example' }), O.Cancel);
        assert.equal(await ask({ type: T.ApplyPatch, filePath: path.join(dir, 'devpost.py'), fileName: 'devpost.py', patchContent: `*** Update File: ${path.join(dir, 'devpost.py')}\n` }), O.Cancel);
        // Allowed: the failing source's extractor, updated in place.
        assert.equal(await ask({ type: T.ApplyPatch, filePath: file, fileName: 'localist.py', patchContent: `*** Update File: ${file}\n@@\n-events\n+items\n` }), O.ProceedOnce);
        await writeFile(file, FIXED);
        yield { type: 'tool_result', toolUseId: 't4', toolName: 'ApplyPatch', content: 'ok', isError: false } as never;
        assert.match(await mcp('rescan'), /No source needs an extractor repair/);
        await mcp('rank_profiles');
        await mcp('write_alerts');
        yield { type: 'assistant', text: '{"summary":"echo of the structured output"}', message: {} } as never;
        yield {
          type: 'result', subtype: 'success', success: true, interrupted: false, error: null, sessionId: 's', durationMs: 1234,
          tokenUsage: null, messages: [], text: '', turnCount: 3,
          structuredOutput: { summary: 'Repaired localist.py; 2 new alerts.', sources_repaired: ['sjsu-events-ai-tech'], sources_still_failing: [], alerts_written: 2 },
        } as never;
      },
    };
  };
}

async function extractorsDir() {
  const dir = await realpath(await mkdtemp(path.join(tmpdir(), 'extractors-')));
  await writeFile(path.join(dir, 'localist.py'), BROKEN);
  await writeFile(path.join(dir, 'devpost.py'), 'def extract(raw, source):\n    return []\n');
  return dir;
}

const config = (dir: string) => ({ factoryApiKey: 'fk', droidPath: 'droid', extractorsDir: dir, maxPatchesPerRun: 4, runTimeoutMs: 60_000 });
const JOB: Job = { runId: RUN, campus: 'sjsu', trigger: 'schedule' };

test('a self-healing run: plan, scan, blocked attempts, one scoped patch with its diff, re-run, rank, alerts, result', async () => {
  const dir = await extractorsDir();
  const { api, events, calls } = fakeApi();
  const seen: CreateSessionOptions[] = [];
  try {
    await runJob(JOB, { config: config(dir), api, startSession: fakeDroid(dir, { seen }) });
    assert.deepEqual(calls, ['scan', 'raw:sjsu-events-ai-tech', 'rescan:apifyRun1', 'rank', 'alerts']);
    assert.equal(await readFile(path.join(dir, 'localist.py'), 'utf8'), FIXED);

    const kinds = events.map((e) => e.kind);
    assert.equal(kinds[0], 'step');
    assert.match(events[0].message, /Run started: schedule scan for sjsu/);
    assert.ok(kinds.includes('plan'));
    assert.equal(kinds.at(-1), 'result');
    assert.equal(events.at(-1)!.message, 'Repaired localist.py; 2 new alerts.');
    assert.deepEqual((events.at(-1)!.payload as { patched: string[] }).patched, ['localist.py']);

    const diffs = events.filter((e) => e.kind === 'diff');
    assert.equal(diffs.length, 1, 'one diff row for the one patch');
    const d = diffs[0].payload as { file: string; diff: string; added: number; removed: number };
    assert.equal(d.file, 'localist.py');
    assert.match(d.diff, /-.*"events"/);
    assert.match(d.diff, /\+.*"items"/);
    assert.deepEqual([d.added, d.removed], [1, 1]);

    assert.ok(!events.some((e) => e.message.includes('echo of the structured output')));

    const blocked = events.filter((e) => e.message.startsWith('Blocked:')).map((e) => e.message);
    assert.equal(blocked.length, 2);
    assert.match(blocked[0], /exec is not allowed/);
    assert.match(blocked[1], /outside the allowed extractors: .*devpost\.py/);

    // Session is scoped: cwd is the extractors folder, autonomy off (every side effect asks the
    // handler), and no disabledToolIds (in droid 0.249 they hide ApplyPatch).
    assert.equal(seen[0].cwd, dir);
    assert.equal(seen[0].autonomyLevel, 'off');
    assert.equal(seen[0].disabledToolIds, undefined);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a profile_created run skips the scan and cannot edit anything', async () => {
  const dir = await extractorsDir();
  const { api, events, calls } = fakeApi();
  const job: Job = { runId: RUN, campus: 'sjsu', trigger: 'profile_created', profileId: '22222222-2222-4222-8222-222222222222' };
  try {
    await runJob(job, {
      config: config(dir),
      api,
      startSession: async (options) => {
        const server = options.mcpServers?.[0] as unknown as { tools: { name: string; handler: (i: unknown) => Promise<string> }[] };
        const call = (name: string) => server.tools.find((t) => t.name === name)!.handler({});
        return {
          close: async () => undefined,
          async *stream() {
            assert.match(await call('scan_campus'), /Not needed/);
            const file = path.join(dir, 'localist.py');
            const r = await options.permissionHandler!({ options: OPTIONS, toolUses: [{ details: { type: T.ApplyPatch, filePath: file, fileName: 'localist.py', patchContent: `*** Update File: ${file}\n` } }] } as never);
            assert.equal((r as { selectedOption: O }).selectedOption, O.Cancel);
            await call('rank_profiles');
            await call('write_alerts');
            yield { type: 'result', subtype: 'success', success: true, interrupted: false, error: null, text: 'Done.', durationMs: 1, tokenUsage: null, messages: [], turnCount: 1, sessionId: 's' } as never;
          },
        };
      },
    });
    assert.deepEqual(calls, ['rank', 'alerts']);
    assert.match(events[0].message, /Run started: new profile for sjsu/);
    assert.equal(events.at(-1)!.kind, 'result');
    assert.equal(events.filter((e) => e.kind === 'diff').length, 0);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('failures become error events and the session still closes', async () => {
  const dir = await extractorsDir();
  const { api, events } = fakeApi();
  let closed = false;
  try {
    await runJob(JOB, {
      config: config(dir),
      api: { ...api, scan: async () => { throw new Error('APIFY_TOKEN is not set'); } },
      startSession: async (options) => {
        const server = options.mcpServers?.[0] as unknown as { tools: { name: string; handler: (i: unknown) => Promise<string> }[] };
        return {
          close: async () => void (closed = true),
          async *stream() {
            assert.match(await server.tools[0].handler({}), /^ERROR: scan_campus failed/);
            yield { type: 'error', message: 'model overloaded', errorType: 'x', timestamp: '' } as never;
            throw new Error('droid exited');
          },
        };
      },
    });
    const errors = events.filter((e) => e.kind === 'error').map((e) => e.message);
    assert.deepEqual(errors, ['scan_campus failed: APIFY_TOKEN is not set', 'Droid error: model overloaded', 'Run failed: droid exited']);
    assert.ok(closed);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a run that cannot start Droid logs why', async () => {
  const dir = await extractorsDir();
  const { api, events } = fakeApi();
  try {
    await runJob(JOB, { config: config(dir), api, startSession: async () => { throw new Error('No Factory API key found'); } });
    assert.equal(events.at(-1)!.kind, 'error');
    assert.match(events.at(-1)!.message, /No Factory API key/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

const PROFILE = '22222222-2222-4222-8222-222222222222';

test('profile ids never reach the public log or the prompt (they act as bearer tokens)', async () => {
  const dir = await extractorsDir();
  const { api, events } = fakeApi();
  const job: Job = { runId: RUN, campus: 'sjsu', trigger: 'profile_created', profileId: PROFILE };
  try {
    assert.ok(!buildPrompt(job).includes(PROFILE));
    await runDirect(job, { api });
    await runJob(job, {
      config: config(dir),
      api,
      startSession: async () => ({ close: async () => undefined, async *stream() {} }),
    });
    assert.ok(events.length > 0);
    assert.ok(!JSON.stringify(events).includes(PROFILE));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('runDirect ranks and alerts without Droid', async () => {
  const { api, events, calls } = fakeApi();
  await runDirect({ runId: RUN, campus: 'sjsu', trigger: 'profile_created', profileId: PROFILE }, { api });
  assert.deepEqual(calls, ['rank', 'alerts']);
  assert.match(events[0].message, /no Droid session/);
  assert.equal(events.at(-1)!.kind, 'result');
});

test('secrets and key-shaped strings are redacted from the run log', async () => {
  const dir = await extractorsDir();
  const { api, events } = fakeApi();
  const leak = 'here: fk-abcdefghijklmnopqrstu sk-ant-api03-abcdefghijklmnopqrstuvwx agent-secret-value-123';
  try {
    await runJob(JOB, {
      config: config(dir),
      api,
      secrets: ['agent-secret-value-123'],
      startSession: async () => ({
        close: async () => undefined,
        async *stream() {
          yield { type: 'assistant', text: leak, message: {} } as never;
          yield { type: 'result', subtype: 'success', success: true, interrupted: false, error: null, text: leak, durationMs: 1, tokenUsage: null, messages: [], turnCount: 1, sessionId: 's' } as never;
        },
      }),
    });
    const all = JSON.stringify(events);
    for (const secret of ['fk-abcdefghijklmnopqrstu', 'sk-ant-api03', 'agent-secret-value-123']) assert.ok(!all.includes(secret), secret);
    assert.ok(all.includes('[redacted]'));
    assert.equal(redact('token fk-short'), 'token fk-short', 'short strings are left alone');
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
