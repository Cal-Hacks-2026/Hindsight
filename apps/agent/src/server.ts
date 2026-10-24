// HTTP triggers from the API (same container; bound to 127.0.0.1 by default).
//   POST /runs   {run_id, campus, trigger: "manual" | "profile_created", profile_id?}
//   GET  /health
// Every request but /health needs X-Agent-Secret.
import { timingSafeEqual } from 'node:crypto';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';

import { z } from 'zod';

import { CAMPUSES } from './config.ts';
import { QueueFull, type RunQueue } from './queue.ts';

const MAX_BODY = 10_000;

const RunRequest = z
  .object({
    run_id: z.string().uuid(),
    campus: z.enum(CAMPUSES),
    trigger: z.enum(['manual', 'profile_created']),
    profile_id: z.string().uuid().nullish(),
  })
  .refine((r) => (r.trigger === 'profile_created') === Boolean(r.profile_id), {
    message: 'profile_id is required for profile_created runs, and only for them',
  });

function send(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

function authorized(req: IncomingMessage, secret: string): boolean {
  const given = Buffer.from(String(req.headers['x-agent-secret'] ?? ''));
  const expected = Buffer.from(secret);
  return given.length === expected.length && timingSafeEqual(given, expected);
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > MAX_BODY) throw new Error('body too large');
    chunks.push(chunk as Buffer);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || 'null');
}

export function createAgentServer(queue: RunQueue, secret: string): Server {
  return createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://agent');
    if (req.method === 'GET' && url.pathname === '/health') return send(res, 200, { ok: true, ...queue.status() });
    if (!authorized(req, secret)) return send(res, 401, { detail: 'Bad agent secret' });
    if (req.method !== 'POST' || url.pathname !== '/runs') return send(res, 404, { detail: 'Not found' });

    let body: unknown;
    try {
      body = await readJson(req);
    } catch (e) {
      return send(res, 400, { detail: (e as Error).message });
    }
    const parsed = RunRequest.safeParse(body);
    if (!parsed.success) return send(res, 422, { detail: parsed.error.issues.map((i) => i.message).join('; ') });
    const { run_id, campus, trigger, profile_id } = parsed.data;
    try {
      const queued = queue.enqueue({ runId: run_id, campus, trigger, profileId: profile_id ?? undefined });
      return send(res, 202, { run_id: queued.runId, position: queued.position });
    } catch (e) {
      if (e instanceof QueueFull) return send(res, 429, { detail: e.message });
      throw e;
    }
  });
}
