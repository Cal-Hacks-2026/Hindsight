import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { AddressInfo } from 'node:net';
import { test } from 'node:test';

import { loadConfig, scrubEnv } from '../src/config.ts';
import type { Job } from '../src/prompt.ts';
import { HourlyBudget, QueueFull, RunQueue } from '../src/queue.ts';
import { createAgentServer } from '../src/server.ts';

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

function deferredQueue(limit = 3) {
  const ran: string[] = [];
  let release: () => void = () => undefined;
  const queue = new RunQueue(
    async (job: Job) => {
      ran.push(job.runId);
      await new Promise<void>((r) => (release = r));
    },
    limit,
  );
  return { queue, ran, release: () => release() };
}

test('runs one at a time and folds identical waiting requests', async () => {
  const { queue, ran, release } = deferredQueue();
  assert.deepEqual(queue.enqueue({ runId: id(1), campus: 'sjsu', trigger: 'schedule' }), { runId: id(1), position: 0 });
  assert.deepEqual(queue.enqueue({ runId: id(2), campus: 'sjsu', trigger: 'schedule' }), { runId: id(2), position: 1 });
  assert.deepEqual(queue.enqueue({ runId: id(3), campus: 'sjsu', trigger: 'schedule' }), { runId: id(2), position: 1 });
  queue.enqueue({ runId: id(4), campus: 'berkeley', trigger: 'schedule' });
  assert.deepEqual(queue.status(), { running: id(1), pending: 2 });
  for (let i = 0; i < 3; i++) {
    release();
    await new Promise((r) => setImmediate(r));
  }
  await queue.idle();
  assert.deepEqual(ran, [id(1), id(2), id(4)]);
});

test('a manual request folds into a running or recent manual run for that campus', async () => {
  let clock = 0;
  let release: () => void = () => undefined;
  const ran: string[] = [];
  const queue = new RunQueue(
    async (job: Job) => {
      ran.push(job.runId);
      await new Promise<void>((r) => (release = r));
    },
    5,
    () => undefined,
    120_000,
    () => clock,
  );
  queue.enqueue({ runId: id(1), campus: 'sjsu', trigger: 'manual' });
  assert.deepEqual(queue.enqueue({ runId: id(2), campus: 'sjsu', trigger: 'manual' }), { runId: id(1), position: 0 });
  assert.equal(queue.enqueue({ runId: id(3), campus: 'berkeley', trigger: 'manual' }).runId, id(3));
  release();
  await new Promise((r) => setImmediate(r));
  clock = 60_000; // finished, but within the cooldown
  assert.equal(queue.enqueue({ runId: id(4), campus: 'sjsu', trigger: 'manual' }).runId, id(1));
  assert.equal(queue.enqueue({ runId: id(5), campus: 'sjsu', trigger: 'schedule' }).runId, id(5), 'schedule is not folded');
  clock = 200_000;
  assert.equal(queue.enqueue({ runId: id(6), campus: 'sjsu', trigger: 'manual' }).runId, id(6));
  for (let i = 0; i < 3; i++) {
    release();
    await new Promise((r) => setImmediate(r));
  }
  await queue.idle();
  assert.deepEqual(ran, [id(1), id(3), id(5), id(6)]);
});

test('refuses work beyond the limit', () => {
  const { queue } = deferredQueue(1);
  queue.enqueue({ runId: id(1), campus: 'sjsu', trigger: 'manual' });
  queue.enqueue({ runId: id(2), campus: 'berkeley', trigger: 'manual' });
  assert.throws(() => queue.enqueue({ runId: id(3), campus: 'sjsu', trigger: 'schedule' }), QueueFull);
});

async function withServer(fn: (url: string, queue: RunQueue) => Promise<void>) {
  const { queue, release } = deferredQueue(1);
  const server = createAgentServer(queue, 's3cret');
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  try {
    await fn(`http://127.0.0.1:${(server.address() as AddressInfo).port}`, queue);
  } finally {
    release();
    server.close();
  }
}

const post = (url: string, body: unknown, secret = 's3cret') =>
  fetch(`${url}/runs`, { method: 'POST', headers: { 'x-agent-secret': secret }, body: JSON.stringify(body) });

test('POST /runs needs the secret and a valid body', async () => {
  await withServer(async (url) => {
    assert.equal((await fetch(`${url}/health`)).status, 200);
    assert.equal((await post(url, {}, 'wrong')).status, 401);
    assert.equal((await post(url, { run_id: 'x', campus: 'sjsu', trigger: 'manual' })).status, 422);
    assert.equal((await post(url, { run_id: id(1), campus: 'stanford', trigger: 'manual' })).status, 422);
    assert.equal((await post(url, { run_id: id(1), campus: 'sjsu', trigger: 'schedule' })).status, 422);
    assert.equal((await post(url, { run_id: id(1), campus: 'sjsu', trigger: 'profile_created' })).status, 422);
    const ok = await post(url, { run_id: id(1), campus: 'sjsu', trigger: 'profile_created', profile_id: id(9) });
    assert.equal(ok.status, 202);
    assert.deepEqual(await ok.json(), { run_id: id(1), position: 0 });
    assert.equal((await post(url, { run_id: id(2), campus: 'sjsu', trigger: 'manual' })).status, 202);
    assert.equal((await post(url, { run_id: id(3), campus: 'berkeley', trigger: 'manual' })).status, 429);
  });
});

test('config defaults and validation', () => {
  const env = { AGENT_SECRET: 's', FACTORY_API_KEY: 'fk' };
  const config = loadConfig(env);
  assert.equal(config.intervalMinutes, 120);
  assert.deepEqual(config.campuses, ['sjsu', 'berkeley']);
  assert.match(config.extractorsDir, /apps\/api\/app\/services\/radar\/extractors$/);
  assert.equal(loadConfig({ ...env, AGENT_INTERVAL_MINUTES: '0' }).intervalMinutes, 0);
  assert.throws(() => loadConfig({ ...env, AGENT_INTERVAL_MINUTES: '-5' }), /AGENT_INTERVAL_MINUTES/);
  assert.throws(() => loadConfig({ ...env, AGENT_CAMPUSES: 'mit' }), /unknown campus/);
  assert.throws(() => loadConfig({ FACTORY_API_KEY: 'fk' }), /AGENT_SECRET/);
});

test('AGENT_SECRET_FILE is read once and deleted', () => {
  const file = path.join(mkdtempSync(path.join(tmpdir(), 'secret-')), 'agent-secret');
  writeFileSync(file, 'from-file\n');
  assert.equal(loadConfig({ FACTORY_API_KEY: 'fk', AGENT_SECRET_FILE: file }).agentSecret, 'from-file');
  assert.equal(existsSync(file), false);
});

test('scrubEnv leaves Droid no secrets', () => {
  const env: NodeJS.ProcessEnv = {
    PATH: '/bin', HOME: '/root', LC_ALL: 'C', FACTORY_API_KEY: 'fk', AGENT_SECRET: 's',
    SUPABASE_SERVICE_ROLE_KEY: 'k', APIFY_TOKEN: 't', ANTHROPIC_API_KEY: 'a',
  };
  scrubEnv(env);
  assert.deepEqual(Object.keys(env).sort(), ['HOME', 'LC_ALL', 'PATH']);
});

test('the hourly budget refills after an hour', () => {
  let t = 0;
  const budget = new HourlyBudget(2, () => t);
  assert.deepEqual([budget.take(), budget.take(), budget.take()], [true, true, false]);
  t = 3_600_000;
  assert.equal(budget.take(), true);
});
